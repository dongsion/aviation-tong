"""
NOTAM通用解析工具 - 坐标提取、时间解析、类型分类
"""
import re
from datetime import datetime, timezone
from typing import List, Tuple, Optional


def parse_point(pt: str) -> Optional[Tuple[float, float]]:
    """
    解析单个坐标点
    格式: N392852E0955438 或 N3928E09554
    返回: (纬度, 经度) 或 None
    """
    m = re.match(r'([NS])(\d{4,6})([WE])(\d{5,7})', pt.strip())
    if not m:
        return None

    ns, lat_s, ew, lon_s = m.group(1), m.group(2), m.group(3), m.group(4)

    # 纬度解析: 度分秒
    if len(lat_s) == 6:
        deg = int(lat_s[:2])
        minute = int(lat_s[2:4])
        sec = int(lat_s[4:6])
    elif len(lat_s) == 4:
        deg = int(lat_s[:2])
        minute = int(lat_s[2:4])
        sec = 0
    else:
        return None
    lat = deg + minute / 60.0 + sec / 3600.0
    if ns == 'S':
        lat = -lat

    # 经度解析: 度分秒
    if len(lon_s) == 7:
        deg = int(lon_s[:3])
        minute = int(lon_s[3:5])
        sec = int(lon_s[5:7])
    elif len(lon_s) == 5:
        deg = int(lon_s[:3])
        minute = int(lon_s[3:5])
        sec = 0
    else:
        return None
    lon = deg + minute / 60.0 + sec / 3600.0
    if ew == 'W':
        lon = -lon

    return (lat, lon)


def extract_coordinates(text: str) -> List[Tuple[float, float]]:
    """
    从NOTAM文本中提取所有坐标点
    支持: N392852E0955438-N385637E0955854-... 格式
    """
    coords = []
    # 匹配连续坐标序列
    coord_pattern = r'([NS]\d{4,6}[WE]\d{5,7})'
    matches = re.findall(coord_pattern, text)

    for match in matches:
        point = parse_point(match)
        if point:
            coords.append(point)

    return coords


def parse_time_window(time_text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    解析时间区间
    格式: '25 NOV 04:01 2025 UNTIL 25 NOV 04:41 2025'
    返回: (开始时间戳, 结束时间戳) — 统一使用 UTC 时间戳
    """
    try:
        parts = str(time_text).split(" UNTIL ")
        if len(parts) != 2:
            return None, None
        # NOTAM 时间使用 UTC，显式指定 tzinfo=timezone.utc 确保时间戳一致
        start = datetime.strptime(parts[0].strip(), "%d %b %H:%M %Y").replace(tzinfo=timezone.utc).timestamp()
        end = datetime.strptime(parts[1].strip(), "%d %b %H:%M %Y").replace(tzinfo=timezone.utc).timestamp()
        return start, end
    except Exception:
        return None, None


# 高度正则 - 匹配 Q) 行中的高度信息
ALTITUDE_REGEX = re.compile(
    r'Q\)\s*[A-Z]+?/[A-Z]+?/[IVK\s]*?/[NBOMK\s]*?/[AEWK\s]*?/(\d{3}/\d{3})/',
    re.IGNORECASE,
)


def extract_altitude(raw_message: str) -> str:
    """从NOTAM原始文本中提取高度限制信息"""
    match = ALTITUDE_REGEX.search(raw_message)
    if match:
        altitudes = match.group(1).split('/')
        lower, upper = int(altitudes[0]), int(altitudes[1])
        # NOTAM 高度单位为 100 英尺，转换为米
        lower_ft = lower * 100
        upper_ft = upper * 100
        lower_m = round(lower_ft * 0.3048)
        upper_m = round(upper_ft * 0.3048)
        if upper == 999:
            return f"{lower_m} 米 ~ 无限制"
        return f"{lower_m} ~ {upper_m} 米"
    return "未标注"


def classify_notam(raw_message: str) -> str:
    """
    根据NOTAM文本内容分类类型
    返回类型标识: danger, restricted, warning, prohibited, tfr, airway, other
    """
    text = raw_message.upper()

    # 按优先级匹配
    if any(kw in text for kw in ['PROHIBITED', 'P-AREA', 'NO FLIGHT']):
        return 'prohibited'
    if any(kw in text for kw in ['DANGER AREA', 'DNG ZONE', 'DANGER ZONE',
                                  'ROCKET', 'LAUNCH', 'MISSILE',
                                  'DEBRIS', 'FALLING',
                                  'TEMPORARY DANGER']):
        return 'danger'
    if any(kw in text for kw in ['RESTRICTED', 'R-AREA', 'TEMPORARY RESTRICTED']):
        return 'restricted'
    if any(kw in text for kw in ['WARNING AREA', 'W-AREA']):
        return 'warning'
    if any(kw in text for kw in ['TEMPORARY FLIGHT RESTRICTION', 'TFR',
                                  'FLIGHT RESTRICTION']):
        return 'tfr'
    if any(kw in text for kw in ['AIRWAY', 'ROUTE', 'NAVIGATION',
                                  'NAVAID', 'VOR', 'ILS']):
        return 'airway'
    return 'other'


def coordinates_in_range(coord_str: str,
                         lon_min: float = 60.0, lon_max: float = 180.0,
                         lat_min: float = -30.0, lat_max: float = 70.0) -> bool:
    """检查坐标是否在指定范围内(主要过滤亚太区域)"""
    if not coord_str:
        return False
    for part in str(coord_str).split('-'):
        p = parse_point(part.strip())
        if not p:
            continue
        lat, lon = p
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return True
    return False
