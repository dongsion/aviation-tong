"""
Launch Library 2 API 数据源客户端
获取即将发射的火箭/卫星发射计划
API 文档: https://ll.thespacedevs.com/2.2.0/
"""
import os
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..base import DataSource, FetchResult

logger = logging.getLogger(__name__)

# 本地图片缓存目录
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
IMAGE_CACHE_DIR = os.path.join(REPO_ROOT, 'static', 'images', 'launches')


class LaunchRecord:
    """发射记录数据结构"""
    def __init__(self, name, net, status, rocket_name, mission_name,
                 mission_desc, mission_type, orbit, provider, provider_type,
                 pad_name, latitude, longitude, location_name, country_code,
                 window_start, window_end, slug, image_url, webcast_live,
                 remote_image_url=''):
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
        self.image_url = image_url          # 图片URL (本地缓存路径)
        self.remote_image_url = remote_image_url  # 原始远程图片URL (备用)
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
        # 确保本地图片缓存目录存在
        os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

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

        # 并行下载图片到本地缓存
        self._download_images_parallel(all_launches)

        # FetchResult 不太适合发射数据，直接返回带 launch_records 的结果
        result = FetchResult(records=[], source=self.name)
        result.launch_records = all_launches
        return result

    def _download_images_parallel(self, launches: list) -> None:
        """并行下载所有发射任务的图片到本地缓存"""
        # 收集需要下载的图片
        download_tasks = []
        for launch in launches:
            if launch.remote_image_url and launch.slug:
                # 检查是否已缓存
                safe_slug = ''.join(c if c.isalnum() or c in '-_' else '_' for c in launch.slug)
                filename = f"{safe_slug}.jpg"
                filepath = os.path.join(IMAGE_CACHE_DIR, filename)
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    launch.image_url = f"static/images/launches/{filename}"
                else:
                    download_tasks.append((launch.remote_image_url, launch.slug))

        if not download_tasks:
            logger.info(f"图片缓存: 全部 {len(launches)} 张已存在，跳过下载")
            return

        logger.info(f"图片缓存: 需要下载 {len(download_tasks)} 张 (并行)")

        # 并行下载 (最多8个线程)
        results_map = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(self._download_image, url, slug): slug
                for url, slug in download_tasks
            }
            for future in as_completed(futures, timeout=120):
                slug = futures[future]
                try:
                    local_path = future.result(timeout=30)
                    results_map[slug] = local_path
                except Exception as e:
                    logger.debug(f"图片下载超时/失败 (slug={slug}): {e}")
                    results_map[slug] = ''

        # 更新 launch 记录的 image_url
        for launch in launches:
            if launch.slug in results_map and results_map[launch.slug]:
                launch.image_url = results_map[launch.slug]

        cached = sum(1 for l in launches if l.image_url)
        logger.info(f"图片缓存完成: {cached}/{len(launches)} 张本地缓存成功")

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

            # 图片URL (原始远程URL，稍后并行下载到本地)
            remote_url = launch.get('image', '')
            slug = launch.get('slug', '')

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
                slug=slug,
                image_url='',  # 稍后由 _download_images_parallel 设置
                webcast_live=launch.get('webcast_live', False),
                remote_image_url=remote_url,
            )

        except Exception as e:
            logger.warning(f"解析发射记录失败: {e}")
            return None

    def _download_image(self, url: str, slug: str) -> str:
        """下载图片到本地缓存目录，返回相对路径

        如果图片已存在则直接返回缓存路径。
        下载后自动压缩为 Web 优化格式 (最大800px宽, JPEG质量85)。
        下载失败时返回空字符串。
        """
        try:
            # 统一使用 .jpg 扩展名（压缩后都是 JPEG）
            safe_slug = ''.join(c if c.isalnum() or c in '-_' else '_' for c in slug)
            filename = f"{safe_slug}.jpg"
            filepath = os.path.join(IMAGE_CACHE_DIR, filename)

            # 如果文件已存在且大小 > 0，直接返回缓存
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return f"static/images/launches/{filename}"

            # 下载原始图片
            resp = requests.get(url, timeout=10, stream=True,
                                headers={'User-Agent': 'Mozilla/5.0 (AviationTong Image Cache)'})
            resp.raise_for_status()

            # 写入临时文件
            tmp_path = filepath + '.tmp'
            with open(tmp_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 用 Pillow 压缩优化图片
            try:
                from PIL import Image
                img = Image.open(tmp_path)
                # 转为 RGB（去掉 alpha 通道）
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                # 缩放到最大 800px 宽
                max_width = 800
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_size = (max_width, int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                # 保存为 JPEG 质量 85
                img.save(filepath, 'JPEG', quality=85, optimize=True)
                # 删除临时文件
                os.remove(tmp_path)
            except Exception as pil_err:
                # Pillow 失败时使用原始文件
                logger.debug(f"Pillow 压缩失败，使用原始文件: {pil_err}")
                if os.path.exists(tmp_path):
                    os.rename(tmp_path, filepath)

            file_size = os.path.getsize(filepath)
            logger.debug(f"图片已缓存: {filename} ({file_size} bytes)")
            return f"static/images/launches/{filename}"

        except Exception as e:
            logger.debug(f"图片下载失败 (slug={slug}): {e}")
            return ''
