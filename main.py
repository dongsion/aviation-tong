#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - NOTAM 航空通告实时可视化系统
主程序: 抓取数据 -> 解析坐标 -> 分类 -> 生成 GeoJSON -> 保存到 data/
"""
import configparser
import json
import os
import re
import sys
import logging
from datetime import datetime, timezone
from typing import List, Dict, Tuple

# 确保项目根目录在 path 中
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from fetch.sources import SourceManager
from fetch.sources.common import (
    parse_point, extract_coordinates, parse_time_window,
    extract_altitude, classify_notam, coordinates_in_range
)

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('航空通')

# ============================================================
# 路径配置
# ============================================================
DATA_DIR = os.path.join(REPO_ROOT, 'data')
DATA_FILE = os.path.join(DATA_DIR, 'notams.json')
LEGEND_FILE = os.path.join(DATA_DIR, 'legend.json')
LAUNCHES_FILE = os.path.join(DATA_DIR, 'launches.json')


# ============================================================
# NOTAM 类型颜色映射
# ============================================================
TYPE_COLORS = {
    'danger':     {'color': '#FF1744', 'name': '临时危险区',    'desc': '火箭发射、导弹试射等临时危险区域'},
    'restricted': {'color': '#FF6D00', 'name': '限制区',        'desc': '军事活动限制区域'},
    'warning':    {'color': '#FFD600', 'name': '警告区',        'desc': '潜在飞行危险警告区域'},
    'prohibited': {'color': '#AA00FF', 'name': '禁航区',        'desc': '完全禁止飞行的区域'},
    'tfr':        {'color': '#2962FF', 'name': '临时飞行限制', 'desc': '临时飞行限制(TFR)'},
    'airway':     {'color': '#00C853', 'name': '航路变更',      'desc': '航路调整或导航设施变更'},
    'other':      {'color': '#546E7A', 'name': '其他通告',      'desc': '其他类型航空通告'},
}


def load_config() -> configparser.ConfigParser:
    """加载配置文件，环境变量 FAA_API_KEY 可覆盖配置中的 api_key"""
    config_path = os.path.join(REPO_ROOT, 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    # 环境变量覆盖 FAA API 密钥 (用于 GitHub Actions secrets)
    env_api_key = os.environ.get('FAA_API_KEY', '').strip()
    if env_api_key and config.has_section('FAA'):
        config.set('FAA', 'api_key', env_api_key)
        logger.info("已从环境变量加载 FAA API 密钥")

    return config


def get_icao_codes(config) -> List[str]:
    """从配置获取 ICAO 代码列表"""
    codes_str = config.get('ICAO', 'codes', fallback='')
    return [c.strip() for c in codes_str.split() if c.strip()]


def coords_to_geojson_polygon(coords: List[Tuple[float, float]]) -> dict:
    """
    将坐标列表转为 GeoJSON Polygon
    Leaflet 中 [lat, lon]，GeoJSON 中 [lon, lat]
    """
    if len(coords) < 3:
        return None

    # GeoJSON 使用 [经度, 纬度]
    ring = [[lon, lat] for lat, lon in coords]

    # 闭合多边形
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    return {
        "type": "Polygon",
        "coordinates": [ring]
    }


def coords_to_geojson_circle(center: Tuple[float, float], radius_nm: float) -> dict:
    """
    将圆心和半径转为 GeoJSON Polygon (近似圆)
    """
    import math
    lat, lon = center
    radius_deg = radius_nm / 60.0  # 海里转度(近似)

    coords = []
    for i in range(72):  # 5度一个点，72个点
        angle = 2 * math.pi * i / 72
        # 纬度修正
        lat_offset = radius_deg * math.cos(angle)
        lon_offset = radius_deg * math.sin(angle) / max(math.cos(math.radians(lat)), 0.01)

        new_lon = lon + lon_offset
        new_lat = lat + lat_offset
        coords.append([new_lon, new_lat])

    coords.append(coords[0])  # 闭合

    return {
        "type": "Polygon",
        "coordinates": [coords]
    }


def record_to_geojson_feature(record) -> dict:
    """将单条 NOTAM 记录转为 GeoJSON Feature"""
    coords = extract_coordinates(record.coordinates)

    if len(coords) >= 3:
        geometry = coords_to_geojson_polygon(coords)
    elif len(coords) == 1:
        # 单点 - 用圆表示(默认半径)
        geometry = coords_to_geojson_circle(coords[0], 10.0)
    elif len(coords) == 2:
        # 两点 - 形成线段缓冲区(简化为矩形)
        lat1, lon1 = coords[0]
        lat2, lon2 = coords[1]
        ring = [[lon1, lat1], [lon2, lat1], [lon2, lat2], [lon1, lat2], [lon1, lat1]]
        geometry = {"type": "Polygon", "coordinates": [ring]}
    else:
        return None

    if not geometry:
        return None

    # 解析时间窗口
    start_ts, end_ts = parse_time_window(record.time)
    time_display = record.time

    notam_type = record.notam_type or 'other'
    color_info = TYPE_COLORS.get(notam_type, TYPE_COLORS['other'])

    # 格式化时间
    start_display = ""
    end_display = ""
    if start_ts and end_ts:
        start_display = datetime.fromtimestamp(start_ts).strftime('%Y-%m-%d %H:%M UTC')
        end_display = datetime.fromtimestamp(end_ts).strftime('%Y-%m-%d %H:%M UTC')

    is_active = False
    now_ts = datetime.now(timezone.utc).timestamp()
    if end_ts and end_ts > now_ts:
        is_active = True
    elif not end_ts:
        is_active = True

    properties = {
        "notam_code": record.code,
        "type": notam_type,
        "type_name": color_info['name'],
        "type_desc": color_info['desc'],
        "color": color_info['color'],
        "fir": record.fir,
        "source": record.source,
        "time": time_display,
        "start": start_display,
        "end": end_display,
        "is_active": is_active,
        "altitude": record.altitude,
        "raw_message": record.raw_message[:500],  # 截断避免过大
    }

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties
    }


def filter_expired(features: List[dict]) -> List[dict]:
    """过滤已过期的 NOTAM (保留当天过期的)"""
    now_ts = datetime.now(timezone.utc).timestamp()
    active = []

    for feat in features:
        props = feat.get('properties', {})
        time_str = props.get('time', '')
        _, end_ts = parse_time_window(time_str)

        # 没有时间或尚未过期 -> 保留
        if not end_ts or end_ts > now_ts:
            active.append(feat)

    return active


# ============================================================
# 火箭/卫星发射计划 - Launch Library 2 API
# ============================================================

# 发射状态中文映射
LAUNCH_STATUS_MAP = {
    'Go': '已确认发射',
    'Go for Launch': '已确认发射',
    'Launch Successful': '发射成功',
    'Launch is Go': '准许发射',
    'TBD': '时间待定',
    'To Be Determined': '时间待定',
    'In Hold': '暂停倒计时',
    ' Scrubbed': '已取消',
    'Launch Scrubbed': '已取消',
    'Live': '直播中',
    'End': '已结束',
}

# 发射场中文名映射
LAUNCH_SITE_MAP = {
    'Jiuquan': '酒泉卫星发射中心',
    'Taiyuan': '太原卫星发射中心',
    'Wenchang': '文昌航天发射场',
    'Xichang': '西昌卫星发射中心',
    'Cape Canaveral': '卡纳维拉尔角',
    'Kennedy Space Center': '肯尼迪航天中心',
    'Vandenberg': '范登堡太空军基地',
    'Boca Chica': '博卡奇卡星舰基地',
    'Kourou': '库鲁航天中心',
    'Baikonur': '拜科努尔航天中心',
    'Vostochny': '东方港航天发射场',
    'Plesetsk': '普列谢茨克航天发射场',
    'Tanegashima': '种子岛宇宙中心',
    'Uchinoura': '内之浦宇宙空间观测所',
    'Naro': '罗老宇航中心',
    'Satish Dhawan': '萨蒂什·达万航天中心',
    'Wallops': '瓦洛普斯飞行设施',
    'Rocket Lab': '火箭实验室发射场',
}

# 火箭中文名映射
ROCKET_NAME_MAP = {
    'Long March': '长征',
    'Falcon 9': '猎鹰9号',
    'Falcon Heavy': '猎鹰重型',
    'Starship': '星舰',
    'Zhuque': '朱雀',
    'Kuaizhou': '快舟',
    'Jielong': '捷龙',
    'Ceres': '谷神星',
    'Ariane': '阿丽亚娜',
    'Soyuz': '联盟号',
    'Proton': '质子号',
    'Angara': '安加拉',
    'H-II': 'H-II',
    'H3': 'H3',
    'Electron': '电子号',
    'Neutron': '中子号',
    'Atlas': '宇宙神',
    'Vulcan': '火神',
    'Delta': '德尔塔',
    'Antares': '安塔瑞斯',
    'Pegasus': '飞马座',
    'Minotaur': '米诺陶',
    'GSLV': 'GSLV',
    'PSLV': 'PSLV',
    'SSLV': 'SSLV',
    'New Glenn': '新格伦',
    'New Shepard': '新谢泼德',
}


def translate_launch_site(name: str) -> str:
    """翻译发射场名称"""
    if not name:
        return ''
    for en, cn in LAUNCH_SITE_MAP.items():
        if en.lower() in name.lower():
            return f"{name} ({cn})"
    return name


def translate_rocket_name(name: str) -> str:
    """翻译火箭名称"""
    if not name:
        return ''
    result = name
    for en, cn in ROCKET_NAME_MAP.items():
        if en.lower() in name.lower():
            result = result.replace(en, cn)
            break
    return result


def fetch_launches(config) -> None:
    """获取火箭/卫星发射计划并生成 launches.json"""
    logger.info("-" * 40)
    logger.info("开始获取火箭/卫星发射计划...")

    try:
        from fetch.sources.launches.client import LaunchLibrarySource

        launch_config = {}
        if config.has_section('LAUNCHES'):
            launch_config = dict(config.items('LAUNCHES'))

        source = LaunchLibrarySource(launch_config)
        result = source.fetch()
        launches = getattr(result, 'launch_records', [])

        if not launches:
            logger.warning("未获取到发射计划数据，生成示例发射数据")
            launches = generate_sample_launches()

        # 转换为 GeoJSON
        features = []
        for launch in launches:
            feature = launch_to_geojson(launch)
            if feature:
                features.append(feature)

        logger.info(f"生成 {len(features)} 个发射计划标记")

        # 统计各国发射数量
        country_counts = {}
        for feat in features:
            cc = feat['properties'].get('country_code', 'UNK')
            country_counts[cc] = country_counts.get(cc, 0) + 1
        logger.info("按国家统计:")
        for cc, count in sorted(country_counts.items(), key=lambda x: -x[1]):
            logger.info(f"  {cc}: {count} 次发射")

        # 生成 GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "metadata": {
                "title": "航空通 - 火箭/卫星发射计划",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "total_features": len(features),
                "data_source": "Launch Library 2",
                "country_counts": country_counts,
            },
            "features": features,
        }

        # 保存
        with open(LAUNCHES_FILE, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        logger.info(f"发射计划已保存到: {LAUNCHES_FILE}")

    except Exception as e:
        logger.error(f"获取发射计划失败: {e}")
        # 生成示例数据
        launches = generate_sample_launches()
        features = [launch_to_geojson(l) for l in launches if l]
        features = [f for f in features if f]
        geojson = {
            "type": "FeatureCollection",
            "metadata": {
                "title": "航空通 - 火箭/卫星发射计划",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "total_features": len(features),
                "data_source": "SAMPLE",
            },
            "features": features,
        }
        with open(LAUNCHES_FILE, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        logger.info(f"示例发射计划已保存到: {LAUNCHES_FILE}")


def launch_to_geojson(launch) -> dict:
    """将发射记录转为 GeoJSON Point Feature"""
    if not hasattr(launch, 'latitude') or not launch.latitude:
        return None

    geometry = {
        "type": "Point",
        "coordinates": [launch.longitude, launch.latitude]
    }

    # 解析发射时间
    net_display = ""
    net_timestamp = 0
    if launch.net:
        try:
            dt = datetime.fromisoformat(launch.net.replace('Z', '+00:00'))
            net_timestamp = dt.timestamp()
            net_display = dt.strftime('%Y-%m-%d %H:%M UTC')
        except Exception:
            net_display = launch.net

    # 计算倒计时
    now_ts = datetime.now(timezone.utc).timestamp()
    countdown = ""
    is_upcoming = False
    if net_timestamp > 0:
        diff = net_timestamp - now_ts
        if diff > 0:
            is_upcoming = True
            days = int(diff // 86400)
            hours = int((diff % 86400) // 3600)
            minutes = int((diff % 3600) // 60)
            if days > 0:
                countdown = f"T-{days}天 {hours}时 {minutes}分"
            elif hours > 0:
                countdown = f"T-{hours}时 {minutes}分"
            else:
                countdown = f"T-{minutes}分"
        else:
            countdown = "已发射"
    else:
        countdown = "时间待定"

    # 翻译
    rocket_cn = translate_rocket_name(launch.rocket_name)
    site_cn = translate_launch_site(launch.location_name)
    status_cn = LAUNCH_STATUS_MAP.get(launch.status, launch.status)

    properties = {
        "name": launch.name,
        "rocket": launch.rocket_name,
        "rocket_cn": rocket_cn,
        "mission_name": launch.mission_name,
        "mission_desc": launch.mission_desc[:300] if launch.mission_desc else '',
        "mission_type": launch.mission_type,
        "orbit": launch.orbit,
        "provider": launch.provider,
        "provider_type": launch.provider_type,
        "pad_name": launch.pad_name,
        "location_name": launch.location_name,
        "location_cn": site_cn,
        "country_code": launch.country_code,
        "net": launch.net,
        "net_display": net_display,
        "countdown": countdown,
        "is_upcoming": is_upcoming,
        "status": launch.status,
        "status_cn": status_cn,
        "window_start": launch.window_start,
        "window_end": launch.window_end,
        "slug": launch.slug,
        "image_url": launch.image_url,
        "remote_image_url": getattr(launch, 'remote_image_url', ''),
        "webcast_live": launch.webcast_live,
    }

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties
    }


def generate_sample_launches():
    """生成示例发射数据"""
    from fetch.sources.launches.client import LaunchRecord

    now = datetime.now(timezone.utc)

    samples = [
        LaunchRecord(
            name="Long March 2C | Earth Observation Satellite",
            net=(now.replace(hour=10, minute=0)).isoformat().replace('+00:00', 'Z'),
            status="Go for Launch",
            rocket_name="Long March 2C",
            mission_name="Earth Observation",
            mission_desc="Earth observation satellite for environmental monitoring.",
            mission_type="Earth Science",
            orbit="Sun-Synchronous Orbit",
            provider="CASC",
            provider_type="Government",
            pad_name="Launch Complex 9",
            latitude=38.863128,
            longitude=111.589567,
            location_name="Taiyuan Satellite Launch Center, China",
            country_code="CHN",
            window_start="",
            window_end="",
            slug="sample-taiyuan",
            image_url="",
            webcast_live=False,
        ),
        LaunchRecord(
            name="Zhuque-3 | Flight 2",
            net=(now.replace(hour=23, minute=35)).isoformat().replace('+00:00', 'Z'),
            status="Go for Launch",
            rocket_name="Zhuque-3",
            mission_name="Flight 2",
            mission_desc="Second test launch of LandSpace ZQ-3 rocket.",
            mission_type="Test Flight",
            orbit="Low Earth Orbit",
            provider="LandSpace",
            provider_type="Commercial",
            pad_name="Launch Area 96B",
            latitude=40.92017,
            longitude=100.25129,
            location_name="Jiuquan Satellite Launch Center, China",
            country_code="CHN",
            window_start="",
            window_end="",
            slug="sample-jiuquan",
            image_url="",
            webcast_live=False,
        ),
        LaunchRecord(
            name="Falcon 9 Block 5 | Starlink Group 17-50",
            net=(now.replace(day=now.day + 1, hour=2, minute=0)).isoformat().replace('+00:00', 'Z'),
            status="Go for Launch",
            rocket_name="Falcon 9 Block 5",
            mission_name="Starlink Group 17-50",
            mission_desc="A batch of 24 satellites for the Starlink mega-constellation.",
            mission_type="Communications",
            orbit="Low Earth Orbit",
            provider="SpaceX",
            provider_type="Commercial",
            pad_name="SLC-4E",
            latitude=34.632,
            longitude=-120.611,
            location_name="Vandenberg SFB, CA, USA",
            country_code="USA",
            window_start="",
            window_end="",
            slug="sample-vandenberg",
            image_url="",
            webcast_live=True,
        ),
        LaunchRecord(
            name="Chang'e 7 | Lunar Mission",
            net=(now.replace(day=now.day + 3, hour=12, minute=0)).isoformat().replace('+00:00', 'Z'),
            status="TBD",
            rocket_name="Long March 5",
            mission_name="Chang'e 7",
            mission_desc="China's lunar exploration mission to the Moon's south pole.",
            mission_type="Lunar Exploration",
            orbit="Lunar Orbit",
            provider="CASC",
            provider_type="Government",
            pad_name="LC-101",
            latitude=19.614,
            longitude=110.951,
            location_name="Wenchang Space Launch Site, China",
            country_code="CHN",
            window_start="",
            window_end="",
            slug="sample-wenchang",
            image_url="",
            webcast_live=False,
        ),
        LaunchRecord(
            name="Ariane 6 | Galileo Satellites",
            net=(now.replace(day=now.day + 5, hour=15, minute=30)).isoformat().replace('+00:00', 'Z'),
            status="TBD",
            rocket_name="Ariane 6",
            mission_name="Galileo",
            mission_desc="Two Galileo navigation satellites for the European constellation.",
            mission_type="Navigation",
            orbit="Medium Earth Orbit",
            provider="ESA",
            provider_type="Government",
            pad_name="ELA-4",
            latitude=5.236,
            longitude=-52.775,
            location_name="Guiana Space Centre, Kourou",
            country_code="GUF",
            window_start="",
            window_end="",
            slug="sample-kourou",
            image_url="",
            webcast_live=False,
        ),
    ]

    return samples


def generate_legend() -> dict:
    """生成图例数据"""
    legend = {
        "types": [
            {
                "key": k,
                "name": v['name'],
                "desc": v['desc'],
                "color": v['color'],
            }
            for k, v in TYPE_COLORS.items()
        ],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return legend


def generate_sample_data() -> List[dict]:
    """
    生成示例数据 - 当 FAA API 不可用时使用
    包含各种类型的示例 NOTAM 区域
    """
    import math

    features = []
    sample_regions = [
        # 临时危险区 - 模拟火箭发射落区 (中国西北)
        {
            "type": "danger",
            "coords": [(40.5, 100.2), (39.8, 100.5), (40.1, 101.3), (40.8, 101.0)],
            "code": "A1234/25",
            "fir": "ZLHW",
            "time": "18 AUG 02:00 2026 UNTIL 18 AUG 04:30 2026",
            "altitude": "0 ~ 无限制 米",
            "raw_message": "A1234/25 NOTAMN Q) ZLHW/OD /W /W /000/999/ A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY: N403000E1001200-N394800E1003000-N400600E1007800-N404800E1006000 BACK TO START. VERTICAL LIMITS:SFC-UNL. 18 AUG 02:00 2026 UNTIL 18 AUG 04:30 2026."
        },
        # 限制区 - 模拟军事活动区 (中国华北)
        {
            "type": "restricted",
            "coords": [(41.2, 116.5), (40.5, 116.8), (40.8, 117.5), (41.5, 117.2)],
            "code": "R5678/25",
            "fir": "ZBPE",
            "time": "18 AUG 06:00 2026 UNTIL 18 AUG 18:00 2026",
            "altitude": "0 ~ 6000 米",
            "raw_message": "R5678/25 NOTAMN Q) ZBPE/OR /W /W /000/200/ TEMPORARY RESTRICTED AREA ESTABLISHED FOR MILITARY OPERATIONS. 18 AUG 06:00 2026 UNTIL 18 AUG 18:00 2026."
        },
        # 临时飞行限制 - TFR (中国华南)
        {
            "type": "tfr",
            "coords": [(23.1, 113.3), (22.5, 113.5), (22.8, 114.2), (23.4, 114.0)],
            "code": "TFR9012/25",
            "fir": "ZGZU",
            "time": "18 AUG 08:00 2026 UNTIL 19 AUG 08:00 2026",
            "altitude": "0 ~ 3000 米",
            "raw_message": "TFR9012/25 NOTAMN TEMPORARY FLIGHT RESTRICTION IN ZGZU FIR. NO FLIGHT OPERATIONS PERMITTED. 18 AUG 08:00 2026 UNTIL 19 AUG 08:00 2026."
        },
        # 警告区 - 模拟潜在危险区 (东海)
        {
            "type": "warning",
            "coords": [(31.0, 125.0), (30.0, 125.5), (30.5, 127.0), (31.5, 126.5)],
            "code": "W3456/25",
            "fir": "ZSHA",
            "time": "18 AUG 00:00 2026 UNTIL 20 AUG 00:00 2026",
            "altitude": "0 ~ 9000 米",
            "raw_message": "W3456/25 NOTAMN WARNING AREA ESTABLISHED. POTENTIAL HAZARD TO FLIGHT OPERATIONS. 18 AUG 00:00 2026 UNTIL 20 AUG 00:00 2026."
        },
        # 禁航区 - 模拟完全禁飞 (西南)
        {
            "type": "prohibited",
            "coords": [(29.5, 106.5), (29.0, 106.8), (29.3, 107.5), (29.8, 107.2)],
            "code": "P7890/25",
            "fir": "ZHWH",
            "time": "18 AUG 00:00 2026 UNTIL 25 AUG 00:00 2026",
            "altitude": "0 ~ 无限制 米",
            "raw_message": "P7890/25 NOTAMN PROHIBITED AREA. NO FLIGHT PERMITTED. 18 AUG 00:00 2026 UNTIL 25 AUG 00:00 2026."
        },
        # 临时危险区 - 模拟南海海域 (火箭落区)
        {
            "type": "danger",
            "coords": [(15.0, 115.0), (14.0, 115.5), (14.5, 117.0), (15.5, 116.5)],
            "code": "A5678/25",
            "fir": "ZSHA",
            "time": "18 AUG 10:00 2026 UNTIL 18 AUG 12:00 2026",
            "altitude": "0 ~ 无限制 米",
            "raw_message": "A5678/25 NOTAMN Q) ZSHA/OD /W /W /000/999/ TEMPORARY DANGER AREA - ROCKET LAUNCH DEBRIS ZONE BOUNDED BY: N150000E1150000-N140000E1153000-N143000E1170000-N153000E1163000 BACK TO START. 18 AUG 10:00 2026 UNTIL 18 AUG 12:00 2026."
        },
        # 航路变更 - 模拟导航设施变更
        {
            "type": "airway",
            "coords": [(36.0, 120.0), (35.5, 120.5), (35.8, 121.5), (36.3, 121.0)],
            "code": "A2345/25",
            "fir": "ZSHA",
            "time": "18 AUG 00:00 2026 UNTIL 22 AUG 00:00 2026",
            "altitude": "3000 ~ 6000 米",
            "raw_message": "A2345/25 NOTAMN AIRWAY ROUTE CHANGE DUE TO NAVIGATION AID MAINTENANCE. 18 AUG 00:00 2026 UNTIL 22 AUG 00:00 2026."
        },
        # 其他类型 - 临时危险区 (东北区域)
        {
            "type": "other",
            "coords": [(45.5, 126.0), (45.0, 126.3), (45.2, 127.0), (45.7, 126.7)],
            "code": "A3456/25",
            "fir": "ZYSH",
            "time": "18 AUG 00:00 2026 UNTIL 19 AUG 00:00 2026",
            "altitude": "0 ~ 5000 米",
            "raw_message": "A3456/25 NOTAMN TEMPORARY AREA FOR AVIATION OPERATIONS. 18 AUG 00:00 2026 UNTIL 19 AUG 00:00 2026."
        },
    ]

    for region in sample_regions:
        color_info = TYPE_COLORS[region['type']]

        start_ts, end_ts = parse_time_window(region['time'])
        start_display = datetime.fromtimestamp(start_ts).strftime('%Y-%m-%d %H:%M UTC') if start_ts else ""
        end_display = datetime.fromtimestamp(end_ts).strftime('%Y-%m-%d %H:%M UTC') if end_ts else ""

        geometry = coords_to_geojson_polygon(region['coords'])
        if not geometry:
            continue

        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "notam_code": region['code'],
                "type": region['type'],
                "type_name": color_info['name'],
                "type_desc": color_info['desc'],
                "color": color_info['color'],
                "fir": region['fir'],
                "source": "SAMPLE",
                "time": region['time'],
                "start": start_display,
                "end": end_display,
                "is_active": True,
                "altitude": region['altitude'],
                "raw_message": region['raw_message'],
                "is_sample": True,
            }
        })

    return features


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("航空通 - NOTAM 航空通告实时可视化系统")
    logger.info("=" * 60)

    # 加载配置
    config = load_config()
    icao_codes = get_icao_codes(config)
    logger.info(f"配置加载完成, ICAO 代码: {len(icao_codes)} 个")

    # 确保数据目录存在
    os.makedirs(DATA_DIR, exist_ok=True)

    # 尝试从数据源获取真实数据
    features = []
    use_real_data = False

    try:
        manager = SourceManager(config)
        logger.info("开始从数据源获取 NOTAM 数据...")

        result = manager.fetch_all(icao_codes)

        if result.is_valid:
            logger.info(f"获取到 {len(result.records)} 条原始 NOTAM")

            # 转换为 GeoJSON
            for record in result.records:
                # 坐标范围过滤
                config_filter = dict(config.items('FILTER')) if config.has_section('FILTER') else {}
                lon_min = float(config_filter.get('lon_min', '60.0'))
                lon_max = float(config_filter.get('lon_max', '180.0'))
                lat_min = float(config_filter.get('lat_min', '-30.0'))
                lat_max = float(config_filter.get('lat_max', '70.0'))

                if not coordinates_in_range(record.coordinates,
                                            lon_min, lon_max, lat_min, lat_max):
                    continue

                feature = record_to_geojson_feature(record)
                if feature:
                    features.append(feature)

            if features:
                use_real_data = True
                logger.info(f"生成 {len(features)} 个有效地图要素")
            else:
                logger.warning("未生成有效地图要素")
    except Exception as e:
        logger.error(f"数据源获取失败: {e}")

    # 如果没有真实数据，使用示例数据
    if not features:
        logger.info("使用示例数据(FAA API 可能不可达)")
        features = generate_sample_data()

    # 过滤过期记录
    features = filter_expired(features)
    logger.info(f"过滤后有效要素: {len(features)} 个")

    # 统计各类型数量
    type_counts = {}
    for feat in features:
        t = feat['properties'].get('type', 'other')
        type_counts[t] = type_counts.get(t, 0) + 1

    logger.info("类型统计:")
    for t, count in sorted(type_counts.items()):
        name = TYPE_COLORS.get(t, {}).get('name', t)
        logger.info(f"  {name}: {count} 个")

    # 生成 GeoJSON
    geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "航空通 - NOTAM 航空通告",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_features": len(features),
            "data_source": "FAA" if use_real_data else "SAMPLE",
            "type_counts": type_counts,
        },
        "features": features,
    }

    # 保存数据
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已保存到: {DATA_FILE}")

    # 生成图例
    legend = generate_legend()
    with open(LEGEND_FILE, 'w', encoding='utf-8') as f:
        json.dump(legend, f, ensure_ascii=False, indent=2)
    logger.info(f"图例已保存到: {LEGEND_FILE}")

    # ============================================================
    # 获取火箭/卫星发射计划 (Launch Library 2 API)
    # 独立运行，即使 NOTAM 抓取失败也能正常获取
    # ============================================================
    fetch_launches(config)

    logger.info("=" * 60)
    logger.info("数据处理完成!")
    logger.info("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
