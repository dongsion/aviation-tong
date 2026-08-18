# -*- coding: utf-8 -*-
"""
飞行计划 NOTAM 影响分析器 (premium/flight_plan.py)

功能概述:
    给定一份飞行计划 (出发机场、到达机场、巡航高度、航路点) 和一批 NOTAM
    GeoJSON 要素，自动找出影响该飞行计划的 NOTAM，计算航路偏距离、高度冲突，
    并生成中文简报文本。

设计要点:
    - 全部使用 Python 标准库，无需第三方依赖
    - ICAO 机场坐标使用内置查找表 (中国主要机场 + 国际主要机场)
    - 距离计算采用 Haversine 公式 (球面距离)
    - 点到航路距离采用 cross-track / along-track 球面距离公式
    - NOTAM 时间与飞行计划时间做区间重叠判断
    - 高度统一换算到米后比较

Python 3.11+ 兼容
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

# ============================================================
#  常量
# ============================================================

# 地球平均半径 (海里)
EARTH_RADIUS_NM = 3440.065  # ≈ 6371.0088 km

# 英尺 → 米
FT_TO_M = 0.3048

# 米 → 海里
M_TO_NM = 0.0005399568

# 影响等级判定阈值 (海里)
DISTANCE_CRITICAL_NM = 0.0       # 0 海里 = 航路直接穿过 NOTAM 区域
DISTANCE_WARNING_NM = 50.0       # 50 海里以内
DISTANCE_INFO_NM = 100.0         # 100 海里以内

# NOTAM 高度 "无限制" 对应的等效上限 (米)
ALT_UNLIMITED_M = 100_000  # 100 km，足以覆盖所有飞行高度


# ============================================================
#  ICAO 机场坐标查找表
# ============================================================

# 格式: { "ICAO代码": (纬度, 经度, "机场中文名") }
ICAO_AIRPORTS: Dict[str, Tuple[float, float, str]] = {
    # ---- 中国主要机场 ----
    "ZBAA": (40.0801, 116.5846, "北京首都国际机场"),
    "ZBAD": (39.5098, 116.4106, "北京大兴国际机场"),
    "ZBNY": (39.1196, 116.6122, "北京南苑机场"),  # 已关闭，保留历史
    "ZBTJ": (39.1244, 117.3458, "天津滨海国际机场"),
    "ZBSJ": (38.2825, 114.7028, "石家庄正定国际机场"),
    "ZBYN": (37.7375, 112.6297, "太原武宿国际机场"),
    "ZBHH": (40.4297, 111.8203, "呼和浩特白塔国际机场"),
    "ZSSS": (31.1979, 121.3360, "上海虹桥国际机场"),
    "ZSPD": (31.1443, 121.8083, "上海浦东国际机场"),
    "ZSNJ": (31.7420, 118.8623, "南京禄口国际机场"),
    "ZSHC": (30.2295, 120.4344, "杭州萧山国际机场"),
    "ZSOF": (31.7498, 117.3144, "合肥新桥国际机场"),
    "ZSNB": (29.8266, 121.4569, "宁波栎社国际机场"),
    "ZSWZ": (27.9122, 120.8510, "温州永强机场"),
    "ZSAM": (24.5440, 118.1274, "厦门高崎国际机场"),
    "ZSFZ": (25.9351, 119.6633, "福州长乐国际机场"),
    "ZSQD": (36.2660, 120.3744, "青岛流亭国际机场"),
    "ZJQD": (36.3814, 120.3830, "青岛胶东国际机场"),
    "ZSYT": (37.4044, 120.3838, "烟台蓬莱国际机场"),
    "ZSJN": (36.8571, 116.8520, "济南遥墙国际机场"),
    "ZGGG": (23.3924, 113.2988, "广州白云国际机场"),
    "ZGSZ": (22.6395, 113.8108, "深圳宝安国际机场"),
    "ZGOW": (23.4266, 116.5166, "汕头外砂机场"),
    "ZGHA": (28.1892, 113.2196, "长沙黄花国际机场"),
    "ZHCC": (34.5197, 113.8408, "郑州新郑国际机场"),
    "ZHHH": (30.7838, 114.2081, "武汉天河国际机场"),
    "ZGSY": (18.3031, 109.4124, "三亚凤凰国际机场"),
    "ZJHK": (19.9349, 110.4589, "海口美兰国际机场"),
    "ZGKL": (25.1803, 110.0394, "桂林两江国际机场"),
    "ZGNN": (22.6083, 108.1722, "南宁吴圩国际机场"),
    "ZUCK": (29.7192, 106.6417, "重庆江北国际机场"),
    "ZUUU": (30.5785, 103.9471, "成都双流国际机场"),
    "ZUCT": (30.3127, 104.4416, "成都天府国际机场"),
    "ZUMY": (31.4298, 104.5407, "绵阳南郊机场"),
    "ZUGY": (26.5385, 106.8008, "贵阳龙洞堡国际机场"),
    "ZUKD": (27.1134, 102.7408, "昆明长水国际机场"),
    "ZUKM": (25.0022, 102.9294, "昆明巫家坝机场"),  # 已关闭
    "ZULS": (29.0697, 102.4661, "丽江三义机场"),
    "ZLXY": (34.4471, 108.7517, "西安咸阳国际机场"),
    "ZLIC": (38.3214, 106.3922, "银川河东国际机场"),
    "ZLXN": (36.5303, 102.0057, "西宁曹家堡机场"),
    "ZLLL": (36.5156, 103.6200, "兰州中川国际机场"),
    "ZLHZ": (37.5378, 106.3978, "固原六盘山机场"),
    "ZWSH": (43.9072, 87.4742, "乌鲁木齐地窝堡国际机场"),
    "ZWHM": (44.8736, 87.4781, "乌鲁木齐米东机场"),
    "ZWYN": (43.9573, 81.3379, "伊宁机场"),
    "ZWTN": (37.0528, 79.8589, "和田机场"),
    "ZWSN": (41.1142, 85.7122, "库尔勒梨城机场"),
    "ZYTX": (41.6398, 123.4836, "沈阳桃仙国际机场"),
    "ZYCC": (43.8788, 125.6856, "长春龙嘉国际机场"),
    "ZYHB": (45.6234, 126.2503, "哈尔滨太平国际机场"),
    "ZYDL": (42.1042, 121.0078, "朝阳机场"),
    "ZYMD": (44.5669, 129.5683, "牡丹江海浪机场"),

    # ---- 港澳台 ----
    "VHHH": (22.3080, 113.9185, "香港赤鱲角国际机场"),
    "VMMC": (22.1496, 113.5926, "澳门国际机场"),
    "RCTP": (25.0797, 121.2342, "台湾桃园国际机场"),
    "RCSS": (25.0496, 121.5519, "台北松山机场"),
    "RCKH": (22.5771, 120.3499, "高雄国际机场"),

    # ---- 国际主要机场 ----
    # 北美
    "KLAX": (33.9425, -118.4081, "洛杉矶国际机场"),
    "KJFK": (40.6413, -73.7781, "纽约肯尼迪国际机场"),
    "KORD": (41.9742, -87.9073, "芝加哥奥黑尔国际机场"),
    "KATL": (33.6407, -84.4277, "亚特兰大哈茨菲尔德机场"),
    "KSFO": (37.6213, -122.3790, "旧金山国际机场"),
    "KMIA": (25.7959, -80.2870, "迈阿密国际机场"),
    "KSEA": (47.4502, -122.3088, "西雅图塔科马国际机场"),
    "KBOS": (42.3656, -71.0096, "波士顿洛根国际机场"),
    "CYYZ": (43.6777, -79.6248, "多伦多皮尔逊国际机场"),
    "CYVR": (49.1939, -123.1844, "温哥华国际机场"),

    # 欧洲
    "EGLL": (51.4700, -0.4543, "伦敦希思罗机场"),
    "EGKK": (51.1481, -0.1903, "伦敦盖特威克机场"),
    "EDDF": (50.0379, 8.5622, "法兰克福机场"),
    "EDDM": (48.3538, 11.7861, "慕尼黑机场"),
    "LFPG": (49.0097, 2.5479, "巴黎戴高乐机场"),
    "LFPO": (48.7233, 2.3794, "巴黎奥利机场"),
    "EHAM": (52.3105, 4.7683, "阿姆斯特丹史基浦机场"),
    "LEMD": (40.4983, -3.5676, "马德里巴拉哈斯机场"),
    "LIRF": (41.8003, 12.2389, "罗马菲乌米奇诺机场"),
    "LIMC": (45.6306, 8.7281, "米兰马尔彭萨机场"),
    "LSZH": (47.4647, 8.5492, "苏黎世机场"),
    "EDDH": (53.6304, 9.9881, "汉堡机场"),
    "ESSA": (59.6519, 17.9186, "斯德哥尔摩阿兰达机场"),
    "ENGM": (60.1939, 11.1004, "奥斯陆加勒穆恩机场"),
    "EKCH": (55.6181, 12.6561, "哥本哈根凯斯楚普机场"),
    "EFHK": (60.3172, 24.9633, "赫尔辛基万塔机场"),
    "UUEE": (55.9726, 37.4146, "莫斯科谢列梅捷沃机场"),
    "UUDD": (55.4146, 37.9019, "莫斯科多莫杰多沃机场"),

    # 亚太
    "RJTT": (35.5494, 139.7798, "东京羽田机场"),
    "RJAA": (35.7720, 140.3929, "东京成田国际机场"),
    "RJBB": (34.4347, 135.2329, "大阪关西国际机场"),
    "RJOO": (34.7855, 135.4382, "大阪伊丹机场"),
    "RJCC": (42.7752, 141.6923, "札幌新千岁机场"),
    "RKSI": (37.4602, 126.4407, "首尔仁川国际机场"),
    "RKSS": (37.5583, 126.7906, "首尔金浦国际机场"),
    "VTBS": (13.6900, 100.7501, "曼谷素万那普机场"),
    "VTBD": (13.6912, 100.6027, "曼谷廊曼机场"),
    "WSSS": (1.3644, 103.9915, "新加坡樟宜机场"),
    "WMKK": (2.7456, 101.7099, "吉隆坡国际机场"),
    "VTSP": (18.7831, 98.9623, "清迈国际机场"),
    "VVOO": (17.9884, 102.5630, "万象瓦岱机场"),
    "VNNB": (19.9010, 102.5630, "琅勃拉邦机场"),
    "VIDP": (28.5562, 77.1000, "德里英迪拉甘地国际机场"),
    "VABB": (19.0896, 72.8656, "孟买贾特拉帕蒂希瓦吉机场"),
    "VECC": (22.6547, 88.4467, "加尔各答内塔吉苏巴斯钱德拉鲍斯机场"),
    "VOMM": (12.9941, 80.1709, "金奈国际机场"),
    "VTBU": (13.0710, 100.6100, "乌塔保机场"),
    "RPLL": (14.5086, 121.0198, "马尼拉尼诺伊阿基诺国际机场"),
    "WIII": (-6.1256, 106.6558, "雅加达苏加诺哈达国际机场"),
    "YSSY": (-33.9461, 151.1772, "悉尼金斯福德史密斯机场"),
    "YMML": (-37.6733, 144.8433, "墨尔本机场"),
    "YBBN": (-27.3842, 153.1175, "布里斯班机场"),
    "YPPH": (-31.9385, 115.9672, "珀斯机场"),
    "NZAA": (-37.0082, 174.7850, "奥克兰机场"),
    "NZCH": (-43.4894, 172.5320, "基督城机场"),

    # 中东 / 非洲
    "OMDB": (25.2532, 55.3657, "迪拜国际机场"),
    "OMAA": (24.4330, 54.6511, "阿布扎比国际机场"),
    "OTHH": (25.2730, 51.6080, "多哈哈马德国际机场"),
    "OERK": (24.9576, 46.6988, "利雅得哈立德国王国际机场"),
    "FAOR": (-26.1392, 28.2460, "约翰内斯堡奥利弗坦博国际机场"),
    "FACT": (-33.9715, 18.6021, "开普敦国际机场"),
    "HECA": (30.1219, 31.4056, "开罗国际机场"),
    "HKJK": (-1.3192, 36.9278, "内罗毕乔莫肯雅塔国际机场"),

    # 南美
    "SBGR": (-23.4356, -46.4731, "圣保罗瓜鲁柳斯国际机场"),
    "SBGL": (-22.8099, -43.2506, "里约热内卢加利昂国际机场"),
    "SAEZ": (-34.8222, -58.5358, "布宜诺斯艾利斯埃塞萨国际机场"),
    "SCEL": (-33.3928, -70.7858, "圣地亚哥阿图罗梅里诺贝尼特斯机场"),
    "SKBO": (4.7016, -74.1469, "波哥大埃尔多拉多国际机场"),
    "LEBL": (41.2974, 2.0833, "巴塞罗那埃尔普拉特机场"),
}


def lookup_airport(icao: str) -> Optional[Tuple[float, float, str]]:
    """
    根据 ICAO 代码查找机场坐标和名称

    参数:
        icao: 四字母 ICAO 机场代码 (如 "ZBAA")

    返回:
        (纬度, 经度, 机场中文名) 或 None (未找到时)
    """
    return ICAO_AIRPORTS.get(icao.strip().upper())


# ============================================================
#  数据结构定义
# ============================================================

class ImpactLevel(Enum):
    """NOTAM 影响等级"""
    CRITICAL = "critical"   # 严重 — 航路直接受影响，需要绕飞
    WARNING = "warning"     # 警告 — 接近航路，需关注
    INFO = "info"           # 提示 — 距离较远，仅供参考

    @property
    def label_cn(self) -> str:
        """中文标签"""
        return {
            ImpactLevel.CRITICAL: "严重",
            ImpactLevel.WARNING: "警告",
            ImpactLevel.INFO: "提示",
        }[self]


@dataclass
class FlightPlan:
    """
    飞行计划数据结构

    属性:
        departure_icao:     出发机场 ICAO 代码 (如 "ZBAA")
        arrival_icao:       到达机场 ICAO 代码 (如 "ZSPD")
        departure_time:     出发时间 (datetime 或 ISO 8601 字符串)
        arrival_time:       到达时间 (datetime 或 ISO 8601 字符串)
        cruise_altitude_ft: 巡航高度 (英尺)
        route_waypoints:    航路点列表，每项为 (lat, lon) 或 ICAO 代码字符串；
                            为空时航路为出发→到达直飞
    """
    departure_icao: str
    arrival_icao: str
    departure_time: Union[datetime, str]
    arrival_time: Union[datetime, str]
    cruise_altitude_ft: float = 0.0
    route_waypoints: List[Union[Tuple[float, float], str]] = field(default_factory=list)


@dataclass
class AffectedNotam:
    """
    单条受影响 NOTAM 的分析详情
    """
    notam_code: str                       # NOTAM 编号
    notam_type: str                        # NOTAM 类型标识
    type_name_cn: str                      # NOTAM 类型中文名
    impact_level: ImpactLevel              # 影响等级
    distance_to_route_nm: float            # 距航路最短距离 (海里)
    altitude_conflict: bool                # 是否存在高度冲突
    time_overlap: bool                     # 飞行时间是否与 NOTAM 有效期重叠
    altitude_range: str                    # NOTAM 高度范围原文
    time_range: str                        # NOTAM 有效期原文
    raw_message: str                       # NOTAM 原始文本
    fir: str                               # 飞行情报区
    geometry_centroid: Optional[Tuple[float, float]] = None  # NOTAM 区域中心点 (lat, lon)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典 (用于 JSON 序列化)"""
        return {
            "notam_code": self.notam_code,
            "notam_type": self.notam_type,
            "type_name_cn": self.type_name_cn,
            "impact_level": self.impact_level.value,
            "impact_level_cn": self.impact_level.label_cn,
            "distance_to_route_nm": round(self.distance_to_route_nm, 2),
            "altitude_conflict": self.altitude_conflict,
            "time_overlap": self.time_overlap,
            "altitude_range": self.altitude_range,
            "time_range": self.time_range,
            "raw_message": self.raw_message,
            "fir": self.fir,
            "geometry_centroid": list(self.geometry_centroid) if self.geometry_centroid else None,
        }


@dataclass
class AnalysisResult:
    """
    飞行计划 NOTAM 影响分析结果

    属性:
        affected_notams:     受影响的 NOTAM 列表 (AffectedNotam)
        route_deviation_nm:  预计需要绕飞的总偏差距离 (海里)
        altitude_conflicts:  存在高度冲突的 NOTAM 数量
        summary:             分析结果摘要文本
    """
    affected_notams: List[AffectedNotam] = field(default_factory=list)
    route_deviation_nm: float = 0.0
    altitude_conflicts: int = 0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典 (用于 JSON 序列化)"""
        return {
            "affected_notams": [n.to_dict() for n in self.affected_notams],
            "route_deviation_nm": round(self.route_deviation_nm, 2),
            "altitude_conflicts": self.altitude_conflicts,
            "summary": self.summary,
            "total_affected": len(self.affected_notams),
            "critical_count": sum(1 for n in self.affected_notams if n.impact_level == ImpactLevel.CRITICAL),
            "warning_count": sum(1 for n in self.affected_notams if n.impact_level == ImpactLevel.WARNING),
            "info_count": sum(1 for n in self.affected_notams if n.impact_level == ImpactLevel.INFO),
        }


# ============================================================
#  飞行计划 NOTAM 影响分析器
# ============================================================

class FlightPlanAnalyzer:
    """
    飞行计划 NOTAM 影响分析器

    用法::

        analyzer = FlightPlanAnalyzer()
        result = analyzer.analyze(flight_plan, notam_features)
        briefing = analyzer.generate_briefing(result)
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化分析器

        参数:
            data_dir: 项目 data 目录路径 (可选，预留)
        """
        self.data_dir = data_dir

    # ----------------------------------------------------------
    #  公开接口
    # ----------------------------------------------------------

    def analyze(self,
                flight_plan: FlightPlan,
                notam_features: List[Dict[str, Any]]) -> AnalysisResult:
        """
        分析 NOTAM 对飞行计划的影响

        参数:
            flight_plan:    飞行计划对象
            notam_features: NOTAM GeoJSON Feature 列表 (与 data/notams.json 的 features 格式一致)

        返回:
            AnalysisResult 分析结果
        """
        # 1. 构建完整航路 (出发 → 航路点 → 到达)
        route = self._build_route(flight_plan)
        if len(route) < 2:
            return AnalysisResult(
                summary="无法构建航路：出发或到达机场坐标未找到，请检查 ICAO 代码。"
            )

        # 2. 解析飞行时间区间
        dep_time, arr_time = self._parse_flight_times(flight_plan)

        # 3. 巡航高度换算为米
        cruise_alt_m = flight_plan.cruise_altitude_ft * FT_TO_M

        # 4. 遍历每条 NOTAM，计算影响
        affected: List[AffectedNotam] = []
        total_deviation = 0.0
        alt_conflict_count = 0

        for feature in notam_features:
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})

            # 提取 NOTAM 属性
            notam_code = props.get("notam_code", "未知")
            notam_type = props.get("type", "other")
            type_name_cn = props.get("type_name", "其他通告")
            altitude_str = props.get("altitude", "未标注")
            fir = props.get("fir", "")
            raw_message = props.get("raw_message", "")
            time_range = props.get("time", "")

            # 跳过不活跃的 NOTAM (如果明确标记为不活跃)
            if props.get("is_active") is False:
                continue

            # 4a. 计算 NOTAM 区域到航路的最短距离
            notam_points = self._extract_geometry_points(geometry)
            if not notam_points:
                continue

            min_distance_nm = float("inf")
            centroid: Optional[Tuple[float, float]] = None

            for pt in notam_points:
                dist = self._point_to_route_distance(pt, route)
                if dist < min_distance_nm:
                    min_distance_nm = dist

            # 计算几何中心点 (用于报告)
            if notam_points:
                centroid = self._calculate_centroid(notam_points)

            # 超过 INFO 阈值的 NOTAM 直接跳过
            if min_distance_nm > DISTANCE_INFO_NM:
                continue

            # 4b. 检查高度冲突
            alt_conflict = self._check_altitude_conflict(altitude_str, cruise_alt_m)

            # 4c. 检查时间重叠
            time_overlap = self._check_time_overlap(props, dep_time, arr_time)

            # 4d. 确定影响等级
            impact_level = self._determine_impact_level(
                min_distance_nm, alt_conflict, time_overlap
            )

            # 4e. 估算绕飞距离 (仅对 CRITICAL 和 WARNING)
            if impact_level in (ImpactLevel.CRITICAL, ImpactLevel.WARNING):
                # 简化估算: 绕飞距离 ≈ 2 × 距航路距离 (往返偏置)
                deviation = max(min_distance_nm, 5.0) * 2
                total_deviation += deviation

            if alt_conflict:
                alt_conflict_count += 1

            affected.append(AffectedNotam(
                notam_code=notam_code,
                notam_type=notam_type,
                type_name_cn=type_name_cn,
                impact_level=impact_level,
                distance_to_route_nm=min_distance_nm,
                altitude_conflict=alt_conflict,
                time_overlap=time_overlap,
                altitude_range=altitude_str,
                time_range=time_range,
                raw_message=raw_message,
                fir=fir,
                geometry_centroid=centroid,
            ))

        # 5. 按影响等级和距离排序
        level_order = {
            ImpactLevel.CRITICAL: 0,
            ImpactLevel.WARNING: 1,
            ImpactLevel.INFO: 2,
        }
        affected.sort(key=lambda n: (level_order[n.impact_level], n.distance_to_route_nm))

        # 6. 生成摘要
        summary = self._generate_summary(affected, total_deviation, alt_conflict_count)

        return AnalysisResult(
            affected_notams=affected,
            route_deviation_nm=total_deviation,
            altitude_conflicts=alt_conflict_count,
            summary=summary,
        )

    def generate_briefing(self, analysis_result: AnalysisResult) -> str:
        """
        生成中文飞行前 NOTAM 简报文本

        参数:
            analysis_result: 分析结果

        返回:
            格式化的中文简报字符串
        """
        lines: List[str] = []
        lines.append("=" * 60)
        lines.append("            飞行计划 NOTAM 影响简报")
        lines.append("=" * 60)
        lines.append("")

        # 概况
        total = len(analysis_result.affected_notams)
        critical = sum(1 for n in analysis_result.affected_notams if n.impact_level == ImpactLevel.CRITICAL)
        warning = sum(1 for n in analysis_result.affected_notams if n.impact_level == ImpactLevel.WARNING)
        info = sum(1 for n in analysis_result.affected_notams if n.impact_level == ImpactLevel.INFO)

        lines.append(f"  受影响 NOTAM 总数: {total} 条")
        lines.append(f"    - 严重 (需绕飞): {critical} 条")
        lines.append(f"    - 警告 (需关注): {warning} 条")
        lines.append(f"    - 提示 (仅供参考): {info} 条")
        lines.append("")

        if analysis_result.altitude_conflicts > 0:
            lines.append(f"  [!] 高度冲突: 检测到 {analysis_result.altitude_conflicts} 条 NOTAM "
                         f"与巡航高度存在冲突，请核实巡航高度或协调高度层。")
        else:
            lines.append("  [OK] 高度检查: 未检测到高度冲突。")

        if analysis_result.route_deviation_nm > 0:
            lines.append(f"  [!] 预计绕飞距离: {analysis_result.route_deviation_nm:.1f} 海里 "
                         f"(约 {analysis_result.route_deviation_nm * 1.852:.0f} 公里)")
        else:
            lines.append("  [OK] 航路偏移: 无需绕飞。")

        lines.append("")

        # 逐条详情
        if not analysis_result.affected_notams:
            lines.append("  本次飞行计划未检测到受影响的 NOTAM，飞行安全。")
        else:
            lines.append("-" * 60)
            lines.append("  受影响 NOTAM 详情:")
            lines.append("-" * 60)
            for i, notam in enumerate(analysis_result.affected_notams, 1):
                level_marker = {
                    ImpactLevel.CRITICAL: "[严重]",
                    ImpactLevel.WARNING: "[警告]",
                    ImpactLevel.INFO: "[提示]",
                }[notam.impact_level]

                lines.append("")
                lines.append(f"  {i}. {level_marker} {notam.notam_code} ({notam.type_name_cn})")
                lines.append(f"     飞行情报区: {notam.fir}")
                lines.append(f"     距航路距离: {notam.distance_to_route_nm:.1f} 海里")

                alt_status = "存在冲突" if notam.altitude_conflict else "无冲突"
                lines.append(f"     高度范围: {notam.altitude_range} ({alt_status})")
                lines.append(f"     有效时间: {notam.time_range}")
                time_status = "与飞行时间重叠" if notam.time_overlap else "不影响飞行时段"
                lines.append(f"     时间影响: {time_status}")

                if notam.geometry_centroid:
                    lat, lon = notam.geometry_centroid
                    lines.append(f"     区域中心: {lat:.4f}°N, {lon:.4f}°E")

                # 截取原始消息前 120 字符
                raw_short = notam.raw_message[:120]
                if len(notam.raw_message) > 120:
                    raw_short += "..."
                lines.append(f"     原文摘要: {raw_short}")

        lines.append("")
        lines.append("=" * 60)
        lines.append("  简报生成时间: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        lines.append("  请结合 ATC 指令和最新航行情报最终确认。")
        lines.append("=" * 60)

        return "\n".join(lines)

    # ----------------------------------------------------------
    #  航路构建
    # ----------------------------------------------------------

    def _build_route(self, flight_plan: FlightPlan) -> List[Tuple[float, float]]:
        """
        构建完整航路坐标序列

        将出发机场、航路点、到达机场合并为 (lat, lon) 列表。
        航路点支持 (lat, lon) 元组或 ICAO 代码字符串。

        返回:
            [(lat, lon), ...] 航路坐标列表
        """
        route: List[Tuple[float, float]] = []

        # 出发机场
        dep = lookup_airport(flight_plan.departure_icao)
        if dep:
            route.append((dep[0], dep[1]))

        # 中间航路点
        for wp in flight_plan.route_waypoints:
            if isinstance(wp, str):
                # ICAO 代码
                airport = lookup_airport(wp)
                if airport:
                    route.append((airport[0], airport[1]))
                # 否则忽略未知 ICAO 代码
            elif isinstance(wp, (tuple, list)) and len(wp) >= 2:
                route.append((float(wp[0]), float(wp[1])))

        # 到达机场
        arr = lookup_airport(flight_plan.arrival_icao)
        if arr:
            route.append((arr[0], arr[1]))

        return route

    # ----------------------------------------------------------
    #  几何工具
    # ----------------------------------------------------------

    def _extract_geometry_points(self, geometry: Dict[str, Any]) -> List[Tuple[float, float]]:
        """
        从 GeoJSON 几何对象中提取所有坐标点

        支持 Point, MultiPoint, LineString, Polygon, MultiPolygon。
        GeoJSON 坐标顺序为 [经度, 纬度]，转换为 (纬度, 经度)。

        参数:
            geometry: GeoJSON Geometry 对象

        返回:
            [(lat, lon), ...] 坐标点列表
        """
        points: List[Tuple[float, float]] = []
        geom_type = geometry.get("type", "")
        coords = geometry.get("coordinates")

        if not coords:
            return points

        def extract_from_coord(coord: Any) -> List[Tuple[float, float]]:
            """递归提取坐标点"""
            result: List[Tuple[float, float]] = []
            if not isinstance(coord, list):
                return result

            if len(coord) >= 2 and all(isinstance(v, (int, float)) for v in coord[:2]):
                # 这是一个坐标点 [lon, lat]
                result.append((float(coord[1]), float(coord[0])))
            else:
                # 嵌套列表，递归处理
                for item in coord:
                    result.extend(extract_from_coord(item))

            return result

        if geom_type == "Point":
            points = extract_from_coord(coords)
        elif geom_type in ("MultiPoint", "LineString"):
            points = extract_from_coord(coords)
        elif geom_type == "Polygon":
            # Polygon 坐标: [[ring0], [ring1], ...]
            # 取第一个环 (外环) 的所有点
            if isinstance(coords, list) and len(coords) > 0:
                outer_ring = coords[0]
                points = extract_from_coord(outer_ring)
        elif geom_type == "MultiPolygon":
            # 取所有多边形的外环点
            for polygon in coords:
                if isinstance(polygon, list) and len(polygon) > 0:
                    outer_ring = polygon[0]
                    points.extend(extract_from_coord(outer_ring))
        else:
            # 尝试通用提取
            points = extract_from_coord(coords)

        return points

    def _calculate_centroid(self, points: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        计算坐标点集的几何中心 (简单算术平均)

        参数:
            points: [(lat, lon), ...]

        返回:
            (lat, lon) 中心点
        """
        if not points:
            return (0.0, 0.0)
        lat_sum = sum(p[0] for p in points)
        lon_sum = sum(p[1] for p in points)
        n = len(points)
        return (lat_sum / n, lon_sum / n)

    # ----------------------------------------------------------
    #  距离计算
    # ----------------------------------------------------------

    def _calculate_distance(self,
                            lat1: float, lon1: float,
                            lat2: float, lon2: float) -> float:
        """
        使用 Haversine 公式计算两点之间的球面距离 (海里)

        参数:
            lat1, lon1: 点 1 的纬度和经度 (度)
            lat2, lon2: 点 2 的纬度和经度 (度)

        返回:
            距离 (海里)
        """
        lat1_r = math.radians(lat1)
        lat2_r = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return EARTH_RADIUS_NM * c

    def _point_to_route_distance(self,
                                 point: Tuple[float, float],
                                 route_waypoints: List[Tuple[float, float]]) -> float:
        """
        计算点到航路的最短距离 (海里)

        对航路的每一段 (segment) 计算 cross-track 距离，
        取所有段的最小值。

        参数:
            point:           (lat, lon) 目标点
            route_waypoints: [(lat, lon), ...] 航路点序列

        返回:
            最短距离 (海里)
        """
        if len(route_waypoints) == 1:
            # 只有一个航路点，计算直线距离
            return self._calculate_distance(
                point[0], point[1],
                route_waypoints[0][0], route_waypoints[0][1]
            )

        min_dist = float("inf")

        for i in range(len(route_waypoints) - 1):
            seg_start = route_waypoints[i]
            seg_end = route_waypoints[i + 1]
            dist = self._point_to_segment_distance(point, seg_start, seg_end)
            if dist < min_dist:
                min_dist = dist

        return min_dist

    def _point_to_segment_distance(self,
                                    point: Tuple[float, float],
                                    seg_start: Tuple[float, float],
                                    seg_end: Tuple[float, float]) -> float:
        """
        计算点到航路段 (大圆弧段) 的最短距离 (海里)

        使用球面几何的 cross-track 和 along-track 距离公式:
            - cross-track distance: 点到大圆弧的垂直距离
            - along-track distance: 投影点到段起点的弧长距离
        若投影点落在段内 (0 <= along-track <= 段长)，取 cross-track 距离；
        否则取点到段端点的较小距离。

        参数:
            point:     (lat, lon) 目标点
            seg_start: (lat, lon) 段起点
            seg_end:   (lat, lon) 段终点

        返回:
            最短距离 (海里)
        """
        # 段长
        seg_length = self._calculate_distance(
            seg_start[0], seg_start[1],
            seg_end[0], seg_end[1]
        )

        if seg_length < 1e-9:
            # 段退化为点
            return self._calculate_distance(
                point[0], point[1],
                seg_start[0], seg_start[1]
            )

        # 点到段起点的距离
        d13 = self._calculate_distance(
            seg_start[0], seg_start[1],
            point[0], point[1]
        )

        if d13 < 1e-9:
            return 0.0

        # 段起点到段终点的方位角
        bearing12 = self._calculate_bearing(seg_start, seg_end)
        # 段起点到目标点的方位角
        bearing13 = self._calculate_bearing(seg_start, point)

        # cross-track 距离 (点到大圆弧的垂直距离)
        # d_xt = arcsin(sin(d13/R) * sin(Δθ)) * R
        d13_rad = d13 / EARTH_RADIUS_NM
        delta_bearing = bearing13 - bearing12
        d_xt = abs(math.asin(
            math.sin(d13_rad) * math.sin(math.radians(delta_bearing))
        ) * EARTH_RADIUS_NM)

        # along-track 距离 (投影点到段起点的弧长)
        # d_at = arccos(cos(d13/R) / cos(d_xt/R)) * R
        cos_d_xt_r = math.cos(d_xt / EARTH_RADIUS_NM)
        if abs(cos_d_xt_r) < 1e-12:
            d_at = 0.0
        else:
            ratio = math.cos(d13_rad) / cos_d_xt_r
            ratio = max(-1.0, min(1.0, ratio))  # 防止浮点误差
            d_at = math.acos(ratio) * EARTH_RADIUS_NM

        # 判断投影点是否落在段内
        if d_at < 0:
            # 投影点在段起点之前 → 取到起点的距离
            return d13
        elif d_at > seg_length:
            # 投影点在段终点之后 → 取到终点的距离
            d_to_end = self._calculate_distance(
                point[0], point[1],
                seg_end[0], seg_end[1]
            )
            return d_to_end
        else:
            # 投影点在段内 → cross-track 距离即为最短距离
            return d_xt

    def _calculate_bearing(self,
                           point_a: Tuple[float, float],
                           point_b: Tuple[float, float]) -> float:
        """
        计算从 A 点到 B 点的方位角 (初始方位角)

        参数:
            point_a: (lat, lon) 起点
            point_b: (lat, lon) 终点

        返回:
            方位角 (度, 0-360, 正北为 0, 顺时针)
        """
        lat1 = math.radians(point_a[0])
        lat2 = math.radians(point_b[0])
        dlon = math.radians(point_b[1] - point_a[1])

        x = math.sin(dlon) * math.cos(lat2)
        y = (math.cos(lat1) * math.sin(lat2)
             - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

        bearing = math.degrees(math.atan2(x, y))
        return (bearing + 360.0) % 360.0

    # ----------------------------------------------------------
    #  高度冲突检测
    # ----------------------------------------------------------

    def _check_altitude_conflict(self,
                                  notam_alt: Union[str, float],
                                  cruise_alt: float) -> bool:
        """
        检查 NOTAM 高度范围是否与巡航高度冲突

        参数:
            notam_alt:  NOTAM 高度信息。可为字符串 (如 "0 ~ 6000 米")
                        或数值 (米)
            cruise_alt: 巡航高度 (米)

        返回:
            True 如果存在高度冲突 (巡航高度在 NOTAM 高度范围内)
        """
        # 解析 NOTAM 高度范围
        if isinstance(notam_alt, (int, float)):
            lower_m = 0.0
            upper_m = float(notam_alt)
        else:
            lower_m, upper_m = self._parse_altitude_string(str(notam_alt))

        # 巡航高度在 NOTAM 高度范围内 → 冲突
        return lower_m <= cruise_alt <= upper_m

    def _parse_altitude_string(self, alt_str: str) -> Tuple[float, float]:
        """
        解析 NOTAM 高度字符串，返回 (下限米, 上限米)

        支持格式:
            - "0 ~ 6000 米"
            - "0 ~ 无限制 米"
            - "3000 ~ 6000 米"
            - "未标注" → (0, 无限制)
            - 纯数字 → (0, 该数字)

        返回:
            (下限高度米, 上限高度米)
        """
        alt_str = alt_str.strip()

        if "未标注" in alt_str or not alt_str:
            return (0.0, float(ALT_UNLIMITED_M))

        # 尝试匹配 "数字 ~ 数字 米" 或 "数字 ~ 无限制 米"
        # 匹配 "~" 或 "至" 分隔
        pattern = r"([\d.]+)\s*[~至]\s*(无限制|[\d.]+)"
        match = re.search(pattern, alt_str)

        if match:
            lower_str = match.group(1)
            upper_str = match.group(2)

            lower = float(lower_str)
            if upper_str == "无限制":
                upper = float(ALT_UNLIMITED_M)
            else:
                upper = float(upper_str)

            return (lower, upper)

        # 尝试匹配单个数字
        num_match = re.search(r"([\d.]+)", alt_str)
        if num_match:
            val = float(num_match.group(1))
            return (0.0, val)

        return (0.0, float(ALT_UNLIMITED_M))

    # ----------------------------------------------------------
    #  时间重叠检测
    # ----------------------------------------------------------

    def _check_time_overlap(self,
                             notam_props: Dict[str, Any],
                             dep_time: Optional[datetime],
                             arr_time: Optional[datetime]) -> bool:
        """
        检查 NOTAM 有效期是否与飞行时间区间重叠

        参数:
            notam_props: NOTAM 属性字典
            dep_time:    出发时间 (datetime 或 None)
            arr_time:    到达时间 (datetime 或 None)

        返回:
            True 如果时间区间有重叠 (或无法确定时间时保守返回 True)
        """
        if dep_time is None or arr_time is None:
            # 无法确定飞行时间，保守认为有重叠
            return True

        notam_start, notam_end = self._parse_notam_time(notam_props)

        if notam_start is None and notam_end is None:
            # 无法解析 NOTAM 时间，保守认为有重叠
            return True

        # 只有一个边界时，也保守处理
        if notam_start is not None and notam_end is not None:
            # 区间重叠判断: notam_start < arr_time AND notam_end > dep_time
            return notam_start < arr_time and notam_end > dep_time
        elif notam_start is not None:
            return notam_start < arr_time
        elif notam_end is not None:
            return notam_end > dep_time

        return True

    def _parse_notam_time(self,
                           notam_props: Dict[str, Any]
                           ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        从 NOTAM 属性中解析开始和结束时间

        优先解析 start/end 字段 (格式如 "2026-08-18 06:00 UTC")，
        回退到 time 字段 (格式如 "18 AUG 06:00 2026 UNTIL 18 AUG 18:00 2026")。

        返回:
            (开始时间 datetime, 结束时间 datetime) — 解析失败的字段为 None
        """
        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None

        # 尝试从 start/end 字段解析
        start_str = notam_props.get("start", "")
        end_str = notam_props.get("end", "")

        start_dt = self._parse_datetime_str(start_str)
        end_dt = self._parse_datetime_str(end_str)

        # 回退到 time 字段
        if start_dt is None or end_dt is None:
            time_str = notam_props.get("time", "")
            if " UNTIL " in time_str:
                parts = time_str.split(" UNTIL ")
                if len(parts) == 2:
                    if start_dt is None:
                        start_dt = self._parse_notam_time_format(parts[0].strip())
                    if end_dt is None:
                        end_dt = self._parse_notam_time_format(parts[1].strip())

        return (start_dt, end_dt)

    def _parse_datetime_str(self, dt_str: str) -> Optional[datetime]:
        """
        解析日期时间字符串 (如 "2026-08-18 06:00 UTC")

        返回:
            timezone-aware datetime (UTC) 或 None
        """
        if not dt_str:
            return None

        dt_str = dt_str.strip()
        # 去掉 "UTC" 后缀
        dt_str = dt_str.replace("UTC", "").strip()

        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(dt_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        return None

    def _parse_notam_time_format(self, time_str: str) -> Optional[datetime]:
        """
        解析 NOTAM 时间格式 "18 AUG 06:00 2026"

        返回:
            timezone-aware datetime (UTC) 或 None
        """
        try:
            dt = datetime.strptime(time_str.strip(), "%d %b %H:%M %Y")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _parse_flight_times(self,
                             flight_plan: FlightPlan
                             ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        解析飞行计划的出发和到达时间

        参数:
            flight_plan: 飞行计划对象

        返回:
            (出发时间 datetime, 到达时间 datetime)
        """
        dep = self._coerce_datetime(flight_plan.departure_time)
        arr = self._coerce_datetime(flight_plan.arrival_time)
        return (dep, arr)

    def _coerce_datetime(self, dt: Union[datetime, str]) -> Optional[datetime]:
        """
        将 datetime 或字符串统一为 timezone-aware datetime (UTC)
        """
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        if isinstance(dt, str):
            result = self._parse_datetime_str(dt)
            if result is not None:
                return result
            # 尝试 NOTAM 格式
            return self._parse_notam_time_format(dt)

        return None

    # ----------------------------------------------------------
    #  影响等级判定
    # ----------------------------------------------------------

    def _determine_impact_level(self,
                                 distance_nm: float,
                                 altitude_conflict: bool,
                                 time_overlap: bool) -> ImpactLevel:
        """
        根据距离、高度冲突和时间重叠判定影响等级

        判定逻辑:
            - CRITICAL: 距离 < 10 海里 且 高度冲突 且 时间重叠
            - WARNING:  距离 < 50 海里 且 (高度冲突 或 时间重叠)
            - INFO:     距离 < 100 海里

        参数:
            distance_nm:       距航路距离 (海里)
            altitude_conflict: 是否高度冲突
            time_overlap:      是否时间重叠

        返回:
            ImpactLevel 枚举
        """
        if distance_nm <= 10.0 and altitude_conflict and time_overlap:
            return ImpactLevel.CRITICAL

        if distance_nm <= DISTANCE_WARNING_NM and (altitude_conflict or time_overlap):
            return ImpactLevel.WARNING

        return ImpactLevel.INFO

    # ----------------------------------------------------------
    #  摘要生成
    # ----------------------------------------------------------

    def _generate_summary(self,
                           affected: List[AffectedNotam],
                           total_deviation: float,
                           alt_conflict_count: int) -> str:
        """
        生成分析结果摘要文本

        参数:
            affected:           受影响的 NOTAM 列表
            total_deviation:    预计绕飞距离 (海里)
            alt_conflict_count: 高度冲突数量

        返回:
            摘要字符串
        """
        if not affected:
            return "本次飞行计划未检测到受影响的 NOTAM，航路安全。"

        critical = sum(1 for n in affected if n.impact_level == ImpactLevel.CRITICAL)
        warning = sum(1 for n in affected if n.impact_level == ImpactLevel.WARNING)
        info = sum(1 for n in affected if n.impact_level == ImpactLevel.INFO)

        parts: List[str] = []
        parts.append(f"共检测到 {len(affected)} 条影响 NOTAM")

        if critical > 0:
            parts.append(f"其中 {critical} 条为严重级别 (航路直接受影响)")
        if warning > 0:
            parts.append(f"{warning} 条为警告级别")
        if info > 0:
            parts.append(f"{info} 条为提示级别")

        if alt_conflict_count > 0:
            parts.append(f"检测到 {alt_conflict_count} 条高度冲突")

        if total_deviation > 0:
            parts.append(f"预计需绕飞 {total_deviation:.1f} 海里 (约 {total_deviation * 1.852:.0f} 公里)")

        if critical == 0 and warning == 0:
            parts.append("航路不受直接影响，建议保持关注")

        return "，".join(parts) + "。"


# ============================================================
#  便捷函数
# ============================================================

def analyze_flight_plan(flight_plan: FlightPlan,
                        notam_features: List[Dict[str, Any]]) -> AnalysisResult:
    """
    便捷函数: 一行调用分析飞行计划

    参数:
        flight_plan:    飞行计划对象
        notam_features: NOTAM GeoJSON Feature 列表

    返回:
        AnalysisResult 分析结果
    """
    analyzer = FlightPlanAnalyzer()
    return analyzer.analyze(flight_plan, notam_features)


# ============================================================
#  模块自测 / 演示
# ============================================================

if __name__ == "__main__":
    import json
    import os

    # 尝试加载项目 data/notams.json 中的样例 NOTAM
    data_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "notams.json"
    )

    if os.path.exists(data_file):
        with open(data_file, "r", encoding="utf-8") as f:
            notam_data = json.load(f)
        notam_features = notam_data.get("features", [])
    else:
        # 使用内嵌样例
        notam_features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [116.5, 41.2], [116.8, 40.5],
                        [117.5, 40.8], [117.2, 41.5],
                        [116.5, 41.2],
                    ]],
                },
                "properties": {
                    "notam_code": "R5678/25",
                    "type": "restricted",
                    "type_name": "限制区",
                    "fir": "ZBPE",
                    "time": "18 AUG 06:00 2026 UNTIL 18 AUG 18:00 2026",
                    "start": "2026-08-18 06:00 UTC",
                    "end": "2026-08-18 18:00 UTC",
                    "is_active": True,
                    "altitude": "0 ~ 6000 米",
                    "raw_message": "R5678/25 NOTAMN TEMPORARY RESTRICTED AREA ESTABLISHED FOR MILITARY OPERATIONS.",
                },
            },
        ]

    # 构造飞行计划: 北京→上海，途经郑州
    fp = FlightPlan(
        departure_icao="ZBAA",
        arrival_icao="ZSPD",
        departure_time="2026-08-18 08:00 UTC",
        arrival_time="2026-08-18 10:00 UTC",
        cruise_altitude_ft=35000,  # 35000 英尺 ≈ 10668 米
        route_waypoints=[(34.5, 113.8)],  # 郑州附近航路点
    )

    analyzer = FlightPlanAnalyzer()
    result = analyzer.analyze(fp, notam_features)

    print("\n" + "=" * 60)
    print("  飞行计划 NOTAM 影响分析演示")
    print("=" * 60)
    print(f"\n航路: {fp.departure_icao} → {fp.arrival_icao}")
    print(f"巡航高度: {fp.cruise_altitude_ft} 英尺 ({fp.cruise_altitude_ft * FT_TO_M:.0f} 米)")
    print(f"时间: {fp.departure_time} → {fp.arrival_time}")
    print(f"\n受影响 NOTAM: {len(result.affected_notams)} 条")
    print(f"预计绕飞: {result.route_deviation_nm:.1f} 海里")
    print(f"高度冲突: {result.altitude_conflicts} 条")
    print(f"\n摘要: {result.summary}")

    print()
    briefing = analyzer.generate_briefing(result)
    print(briefing)
