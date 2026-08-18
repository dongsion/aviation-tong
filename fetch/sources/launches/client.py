"""
Launch Library 2 API 数据源客户端
获取即将发射的火箭/卫星发射计划
API 文档: https://ll.thespacedevs.com/2.2.0/
"""
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List

from ..base import DataSource, FetchResult

logger = logging.getLogger(__name__)


class LaunchRecord:
    """发射记录数据结构"""
    def __init__(self, name, net, status, rocket_name, mission_name,
                 mission_desc, mission_type, orbit, provider, provider_type,
                 pad_name, latitude, longitude, location_name, country_code,
                 window_start, window_end, slug, image_url, webcast_live):
        self.name = name
        self.net = net                      # 发射时间 (ISO 8601)
        self.status = status                # 状态 (Go/Success/TBD等)
        self.rocket_name = rocket_name      # 火箭名称
        self.mission_name = mission_name    # 任务名称
        self.mission_desc = mission_desc    # 任务描述
        self.mission_type = mission_type    # 任务类型
        self.orbit = orbit                  # 轨道
        self.provider = provider            # 发射服务商
        self.provider_type = provider_type  # 服务商类型
        self.pad_name = pad_name            # 发射台名称
        self.latitude = latitude            # 纬度
        self.longitude = longitude         # 经度
        self.location_name = location_name  # 发射场名称
        self.country_code = country_code   # 国家代码
        self.window_start = window_start    # 发射窗口开始
        self.window_end = window_end        # 发射窗口结束
        self.slug = slug                   # URL slug
        self.image_url = image_url          # 图片URL
        self.webcast_live = webcast_live    # 是否有直播


class LaunchLibrarySource(DataSource):
    """Launch Library 2 数据源 - 获取即将发射的火箭/卫星"""

    name = "launches"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get('base_url',
            'https://ll.thespacedevs.com/2.2.0/launch/upcoming/')
        self.timeout = int(config.get('timeout', 20))
        self.retries = int(config.get('retries', 3))
        self.limit = int(config.get('limit', 50))  # 获取数量
        # 发射状态筛选: 1=Go, 2=TBD, 8=待定, 5=即将发射
        self.status_filter = config.get('status_filter', '')

    def fetch(self, icao_codes: List[str] = None) -> FetchResult:
        """从 Launch Library 2 获取即将发射的火箭/卫星数据"""
        all_launches = []
        offset = 0
        page = 1
        max_pages = 5  # 最多获取5页

        while page <= max_pages:
            try:
                data = self._request(offset)
                results = data.get('results', []) if isinstance(data, dict) else []

                if not results:
                    break

                for launch in results:
                    record = self._parse_launch(launch)
                    if record:
                        all_launches.append(record)

                # 检查是否还有更多数据
                count = data.get('count', 0) if isinstance(data, dict) else 0
                if offset + len(results) >= count:
                    break

                offset += self.limit
                page += 1
                time.sleep(0.5)  # 礼貌延迟

            except Exception as e:
                logger.warning(f"Launch Library 第 {page} 页获取失败: {e}")
                break

        logger.info(f"Launch Library: 获取 {len(all_launches)} 条即将发射记录")

        # FetchResult 不太适合发射数据，直接返回带 launch_records 的结果
        result = FetchResult(records=[], source=self.name)
        result.launch_records = all_launches
        return result

    def _request(self, offset: int = 0) -> dict:
        """发送 Launch Library 2 API 请求"""
        params = {
            'format': 'json',
            'limit': str(self.limit),
            'offset': str(offset),
            'ordering': 'net',  # 按发射时间排序
        }

        # 状态筛选
        if self.status_filter:
            params['status'] = self.status_filter

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (AviationTong Launch Tracker)',
        }

        last_error = None
        for attempt in range(self.retries):
            try:
                resp = requests.get(
                    self.base_url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"Launch Library 第 {attempt+1} 次请求失败: {e}")
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)

        raise last_error or Exception("Launch Library API 未知错误")

    def _parse_launch(self, launch: dict) -> LaunchRecord:
        """解析单条发射记录"""
        try:
            # 发射场坐标
            pad = launch.get('pad', {}) or {}
            latitude = pad.get('latitude')
            longitude = pad.get('longitude')

            # 如果没有发射台坐标，跳过
            if not latitude or not longitude:
                return None

            latitude = float(latitude)
            longitude = float(longitude)

            # 发射场信息
            location = pad.get('location', {}) or {}

            # 状态
            status_info = launch.get('status', {}) or {}

            # 火箭
            rocket = launch.get('rocket', {}) or {}
            config = rocket.get('configuration', {}) or {}

            # 任务
            mission = launch.get('mission', {}) or {}
            orbit_info = mission.get('orbit', {}) or {}

            # 发射服务商
            provider = launch.get('launch_service_provider', {}) or {}

            return LaunchRecord(
                name=launch.get('name', ''),
                net=launch.get('net', ''),
                status=status_info.get('name', ''),
                rocket_name=config.get('full_name', config.get('name', '')),
                mission_name=mission.get('name', ''),
                mission_desc=mission.get('description', ''),
                mission_type=mission.get('type', ''),
                orbit=orbit_info.get('name', ''),
                provider=provider.get('name', ''),
                provider_type=provider.get('type', ''),
                pad_name=pad.get('name', ''),
                latitude=latitude,
                longitude=longitude,
                location_name=location.get('name', ''),
                country_code=location.get('country_code', '') or pad.get('country_code', ''),
                window_start=launch.get('window_start', ''),
                window_end=launch.get('window_end', ''),
                slug=launch.get('slug', ''),
                image_url=launch.get('image', ''),
                webcast_live=launch.get('webcast_live', False),
            )

        except Exception as e:
            logger.warning(f"解析发射记录失败: {e}")
            return None
