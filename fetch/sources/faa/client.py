"""
FAA NOTAM 数据源客户端
支持 FAA NOTAM API v1 (REST) 和传统 NOTAM Search JSON 接口
"""
import re
import time
import logging
import requests
from typing import List

from ..base import DataSource, FetchResult, NotamRecord
from ..common import (
    extract_coordinates, parse_time_window, extract_altitude,
    classify_notam, coordinates_in_range
)

logger = logging.getLogger(__name__)


class FAASource(DataSource):
    """FAA NOTAM 数据源 - 同时支持 API v1 和传统搜索接口"""

    name = "faa"

    def __init__(self, config: dict):
        super().__init__(config)
        self.search_url = config.get('search_url',
            'https://notams.aim.faa.gov/notamSearch/search')
        self.api_v1_url = config.get('api_v1_url',
            'https://external-api.faa.gov/notamapi/v1/notams')
        self.api_key = config.get('api_key', '')  # FAA API 密钥(可选)
        self.timeout = int(config.get('timeout', 15))
        self.retries = int(config.get('retries', 3))
        self.max_workers = int(config.get('max_workers', 3))
        self.max_pages = int(config.get('max_pages', 100))
        self.freeform_terms = config.get('freeform_terms',
            'AEROSPACE,ROCKET,DNG ZONE,DANGER AREA')

    def fetch(self, icao_codes: List[str]) -> FetchResult:
        """从 FAA 获取 NOTAM 数据"""
        all_records = []

        for icao in icao_codes:
            try:
                # 先尝试 API v1 (REST)，失败则回退到传统搜索接口
                records = self._fetch_location_v1(icao)
                if not records:
                    records = self._fetch_location_search(icao)
                all_records.extend(records)
                logger.info(f"FAA {icao}: 获取 {len(records)} 条 NOTAM")
                time.sleep(0.3)  # 礼貌延迟
            except Exception as e:
                logger.error(f"FAA {icao} 获取失败: {e}")

        return FetchResult(records=all_records, source=self.name)

    # ============================================================
    # FAA NOTAM API v1 (REST)
    # ============================================================
    def _fetch_location_v1(self, icao: str) -> List[NotamRecord]:
        """通过 FAA NOTAM API v1 获取数据"""
        records = []
        page = 1

        while page <= self.max_pages:
            try:
                data = self._request_v1(icao, page)
                notams = data.get('notams', []) if isinstance(data, dict) else []

                if not notams:
                    break

                for notam in notams:
                    record = self._parse_notam(notam, icao)
                    if record:
                        records.append(record)

                # 检查分页
                total = data.get('itemCount', 0) if isinstance(data, dict) else 0
                per_page = 20
                if page * per_page >= total:
                    break

                page += 1
                time.sleep(0.2)

            except Exception as e:
                logger.warning(f"FAA API v1 {icao} 第 {page} 页失败: {e}")
                break

        return records

    def _request_v1(self, icao: str, page: int = 1) -> dict:
        """发送 FAA NOTAM API v1 GET 请求"""
        params = {
            'location': icao,
            'sortBy': 'notamNumber',
            'sortOrder': 'asc',
            'pageSize': '100',
            'pageNum': str(page),
        }

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (AviationTong NOTAM Viewer)',
        }
        # 如果配置了 API 密钥，添加到请求头
        if self.api_key:
            headers['x-api-key'] = self.api_key
            headers['client_id'] = self.api_key

        last_error = None
        for attempt in range(self.retries):
            try:
                resp = requests.get(
                    self.api_v1_url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)

        raise last_error or Exception("API v1 未知错误")

    # ============================================================
    # 传统 FAA NOTAM Search (POST 表单)
    # ============================================================
    def _fetch_location_search(self, icao: str) -> List[NotamRecord]:
        """通过传统搜索接口获取数据"""
        records = []
        page = 1
        offset = 0

        while page <= self.max_pages:
            try:
                data = self._request_search(icao, offset)
                notams = data if isinstance(data, list) else []

                if not notams:
                    break

                for notam in notams:
                    record = self._parse_notam(notam, icao)
                    if record:
                        records.append(record)

                if len(notams) < 20:
                    break

                offset += 20
                page += 1
                time.sleep(0.2)

            except Exception as e:
                logger.warning(f"FAA Search {icao} 第 {page} 页失败: {e}")
                break

        return records

    def _request_search(self, icao: str, offset: int = 0) -> list:
        """发送传统 FAA NOTAM Search POST 请求"""
        payload = {
            'searchType': '0',
            'designatorsForLocation': icao,
            'notamType': 'N,R,C',
            'operationMode': '1',
            'offset': str(offset),
            'pageNum': '20',
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (AviationTong NOTAM Viewer)',
        }

        last_error = None
        for attempt in range(self.retries):
            try:
                resp = requests.post(
                    self.search_url,
                    data=payload,
                    headers=headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()

                data = resp.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'notamList' in data:
                    return data['notamList']
                else:
                    return []

            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)

        raise last_error or Exception("Search API 未知错误")

    def _parse_notam(self, notam: dict, fir: str) -> NotamRecord:
        """解析单条 FAA NOTAM 为标准化记录"""
        # FAA JSON 格式字段名可能不同，兼容多种字段名
        code = (notam.get('notamNumber') or
                notam.get('notam_id') or
                notam.get('id') or '')

        raw_message = (notam.get('traditionalMessage') or
                       notam.get('icaoMessage') or
                       notam.get('message') or
                       notam.get('text') or '')

        if not raw_message:
            return None

        # 提取坐标
        coords = extract_coordinates(raw_message)
        if not coords:
            return None

        # 坐标字符串
        coord_str = '-'.join(
            f"{'N' if lat >= 0 else 'S'}{abs(int(lat))}{abs(int((lat % 1) * 60)):02d}"
            f"{'E' if lon >= 0 else 'W'}{abs(int(lon))}{abs(int((lon % 1) * 60)):02d}"
            for lat, lon in coords
        )

        # 提取时间区间
        time_text = self._extract_time(raw_message)

        # 提取高度
        altitude = extract_altitude(raw_message)

        # 分类类型
        notam_type = classify_notam(raw_message)

        # 平台ID(用于唯一标识)
        platid = code or hash(raw_message)

        return NotamRecord(
            code=code,
            coordinates=coord_str,
            time=time_text,
            platid=str(platid),
            raw_message=raw_message,
            altitude=altitude,
            source=self.name.upper(),
            fir=fir,
            notam_type=notam_type,
        )

    def _extract_time(self, text: str) -> str:
        """从 NOTAM 文本中提取时间区间"""
        # 常见格式: 06 JUL 03:18 2023 UNTIL 06 JUL 04:45 2023
        time_pattern = re.compile(
            r'(\d{2}\s+\w{3}\s+\d{2}:\d{2}\s+\d{4})\s+UNTIL\s+'
            r'(\d{2}\s+\w{3}\s+\d{2}:\d{2}\s+\d{4})',
            re.IGNORECASE
        )
        match = time_pattern.search(text)
        if match:
            return f"{match.group(1)} UNTIL {match.group(2)}"
        return ""
