"""
CelesTrak TLE 数据源客户端
获取卫星 TLE (Two-Line Element) 轨道数据
API 文档: https://celestrak.org/NORAD/elements/
"""
import time
import logging
import requests
from typing import List

from ..base import DataSource, FetchResult

logger = logging.getLogger(__name__)

# CelesTrak 卫星分组配置
SATELLITE_GROUPS = {
    'stations': '空间站 (ISS, 天宫等)',
    'visual': '最亮的可视卫星',
    'active': '所有活跃卫星',
    'starlink': '星链',
    'weather': '天气卫星',
    'gps': 'GPS导航',
    'beidou': '北斗',
}


class SatelliteRecord:
    """卫星 TLE 记录数据结构"""
    def __init__(self, satellite_name, norad_id, tle_line1, tle_line2,
                 category):
        self.satellite_name = satellite_name  # 卫星名称
        self.norad_id = norad_id              # NORAD 编号
        self.tle_line1 = tle_line1            # TLE 第一行
        self.tle_line2 = tle_line2            # TLE 第二行
        self.category = category              # 分组类别


class CelesTrakSource(DataSource):
    """CelesTrak TLE 数据源 - 获取卫星轨道数据"""

    name = "satellites"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get('base_url',
            'https://celestrak.org/NORAD/elements/gp.php')
        self.timeout = int(config.get('timeout', 20))
        self.retries = int(config.get('retries', 3))
        # 获取的分组列表（支持逗号分隔的字符串或列表）
        groups = config.get('groups', '')
        if isinstance(groups, str):
            self.groups = [g.strip() for g in groups.split(',') if g.strip()]
        else:
            self.groups = groups
        if not self.groups:
            self.groups = list(SATELLITE_GROUPS.keys())

    def fetch(self, icao_codes: List[str] = None) -> FetchResult:
        """从 CelesTrak 获取卫星 TLE 数据"""
        all_satellites = []

        for group in self.groups:
            try:
                tle_text = self._request(group)
                if not tle_text:
                    logger.warning(f"CelesTrak 分组 {group} 无数据")
                    continue

                records = self._parse_tle(tle_text, group)
                all_satellites.extend(records)
                logger.info(f"CelesTrak 分组 {group}: 获取 {len(records)} 条卫星记录")

                time.sleep(1.0)  # 礼貌延迟，避免被封

            except Exception as e:
                logger.warning(f"CelesTrak 分组 {group} 获取失败: {e}")
                continue

        logger.info(f"CelesTrak: 共获取 {len(all_satellites)} 条卫星 TLE 记录")

        # FetchResult 不太适合卫星数据，直接返回带 satellite_records 的结果
        result = FetchResult(records=[], source=self.name)
        result.satellite_records = all_satellites
        return result

    def _request(self, group: str) -> str:
        """发送 CelesTrak API 请求，返回 TLE 文本"""
        params = {
            'GROUP': group,
            'FORMAT': 'tle',
        }

        headers = {
            'Accept': 'text/plain',
            'User-Agent': 'Mozilla/5.0 (AviationTong Satellite Tracker)',
        }

        last_error = None
        for attempt in range(self.retries):
            try:
                resp = requests.get(
                    self.base_url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.text

            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"CelesTrak 分组 {group} 第 {attempt+1} 次请求失败: {e}")
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)

        raise last_error or Exception("CelesTrak API 未知错误")

    def _parse_tle(self, tle_text: str, category: str) -> List[SatelliteRecord]:
        """解析 TLE 格式数据(每3行一组: 名称行 + 两行TLE)"""
        records = []
        lines = [line.strip() for line in tle_text.splitlines() if line.strip()]

        i = 0
        while i + 2 < len(lines):
            name_line = lines[i]
            line1 = lines[i + 1]
            line2 = lines[i + 2]

            # 校验 TLE 行格式: 第一行以 "1 " 开头, 第二行以 "2 " 开头
            if not (line1.startswith('1 ') and line2.startswith('2 ')):
                i += 1
                continue

            # 从 TLE 第一行提取 NORAD 编号
            # TLE 行格式: "1 25544U 98067A ..." — 第二个字段是 NORAD编号+分类字母
            try:
                norad_raw = line1.split()[1]
                # 分类字母是末尾的大写字母 (U=未分类, A=保密, etc)
                # NORAD ID 是纯数字部分
                norad_id = ''
                for c in norad_raw:
                    if c.isdigit():
                        norad_id += c
                    else:
                        break
            except IndexError:
                i += 1
                continue

            record = SatelliteRecord(
                satellite_name=name_line,
                norad_id=norad_id,
                tle_line1=line1,
                tle_line2=line2,
                category=category,
            )
            records.append(record)
            i += 3

        return records
