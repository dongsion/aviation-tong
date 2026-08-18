#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - NOTAM 订阅管理器

管理用户的 NOTAM 订阅，支持按地理围栏（多边形）、FIR 代码、关键词
三个维度筛选。提供 match_notam 方法判断新 NOTAM 是否命中订阅条件，
并具备完整的 CRUD 操作。

订阅数据持久化于 data/subscriptions.json

地理围栏匹配采用纯标准库实现（射线法 + 线段相交检测），不依赖 shapely。
"""
import json
import os
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# 路径配置
# ============================================================
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, 'data')
SUBSCRIPTIONS_FILE = os.path.join(DATA_DIR, 'subscriptions.json')


# ============================================================
# 订阅数据模型
# ============================================================
@dataclass
class Subscription:
    """NOTAM 订阅定义"""
    id: str = ""                                          # 订阅唯一标识
    name: str = ""                                        # 订阅名称
    user_id: str = ""                                     # 所属用户 ID
    area_polygon: Optional[Dict] = None                   # 地理围栏 GeoJSON Polygon（None=不限区域）
    fir_codes: List[str] = field(default_factory=list)    # FIR 代码筛选（空=不限）
    keywords: List[str] = field(default_factory=list)     # 关键词筛选（空=不限）
    channels: List[str] = field(default_factory=list)     # 通知渠道（NotificationChannel 值列表）
    email: str = ""                                       # 邮件推送目标地址
    webhook_url: str = ""                                 # Webhook 推送目标 URL
    created_at: str = ""                                  # 创建时间 ISO 格式

    def __post_init__(self):
        """自动生成 ID 与创建时间"""
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """转为字典（用于 JSON 序列化）"""
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "area_polygon": self.area_polygon,
            "fir_codes": self.fir_codes,
            "keywords": self.keywords,
            "channels": self.channels,
            "email": self.email,
            "webhook_url": self.webhook_url,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Subscription":
        """从字典构建订阅对象"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            user_id=data.get("user_id", ""),
            area_polygon=data.get("area_polygon"),
            fir_codes=data.get("fir_codes", []),
            keywords=data.get("keywords", []),
            channels=data.get("channels", []),
            email=data.get("email", ""),
            webhook_url=data.get("webhook_url", ""),
            created_at=data.get("created_at", ""),
        )


# ============================================================
# 地理围栏匹配工具（纯标准库实现，不依赖 shapely）
# ============================================================
# GeoJSON 坐标格式为 [lon, lat]，与项目 main.py 保持一致

def _point_in_polygon(
    point: Tuple[float, float],
    ring: List[Tuple[float, float]],
) -> bool:
    """
    射线法判断点是否在多边形环内部

    Args:
        point: (lon, lat) 坐标
        ring:  多边形顶点列表 [(lon, lat), ...]

    Returns:
        点是否在多边形内
    """
    x, y = point
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        # 判断射线是否穿过当前边
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def _cross_product(o: Tuple[float, float],
                   a: Tuple[float, float],
                   b: Tuple[float, float]) -> float:
    """计算向量 OA x OB 的叉积"""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    p4: Tuple[float, float],
) -> bool:
    """
    判断线段 p1-p2 与 p3-p4 是否相交（含端点共线情况）

    使用叉积方向判定法：两线段相交当且仅当每条线段的两个端点
    分别在另一条线段的两侧（叉积异号）。
    """
    d1 = _cross_product(p3, p4, p1)
    d2 = _cross_product(p3, p4, p2)
    d3 = _cross_product(p1, p2, p3)
    d4 = _cross_product(p1, p2, p4)

    # 严格相交（叉积异号）
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # 共线/端点触碰的情况（叉积为零）
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True

    return False


def _on_segment(
    p: Tuple[float, float],
    q: Tuple[float, float],
    r: Tuple[float, float],
) -> bool:
    """判断点 r 是否在线段 pq 上（已知共线时调用）"""
    return (min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and
            min(p[1], q[1]) <= r[1] <= max(p[1], q[1]))


def _bounding_box(
    ring: List[Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """
    计算多边形环的边界框

    Returns:
        (min_lon, min_lat, max_lon, max_lat)
    """
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return min(lons), min(lats), max(lons), max(lats)


def _polygons_intersect(
    ring_a: List[Tuple[float, float]],
    ring_b: List[Tuple[float, float]],
) -> bool:
    """
    判断两个多边形是否相交

    策略：
      1. 边界框快速排除（不相交则直接返回 False）
      2. 检查 A 的顶点是否在 B 内（覆盖关系）
      3. 检查 B 的顶点是否在 A 内（反向覆盖）
      4. 检查所有边的线段相交
    """
    # 1. 边界框快速排除
    bb_a = _bounding_box(ring_a)
    bb_b = _bounding_box(ring_b)
    if (bb_a[0] > bb_b[2] or bb_a[2] < bb_b[0] or
            bb_a[1] > bb_b[3] or bb_a[3] < bb_b[1]):
        return False

    # 2. A 的顶点是否在 B 内
    for pt in ring_a:
        if _point_in_polygon(pt, ring_b):
            return True

    # 3. B 的顶点是否在 A 内
    for pt in ring_b:
        if _point_in_polygon(pt, ring_a):
            return True

    # 4. 检查边相交
    na = len(ring_a)
    nb = len(ring_b)
    for i in range(na):
        a1 = ring_a[i]
        a2 = ring_a[(i + 1) % na]
        for j in range(nb):
            b1 = ring_b[j]
            b2 = ring_b[(j + 1) % nb]
            if _segments_intersect(a1, a2, b1, b2):
                return True

    return False


def _geojson_polygon_rings(
    geometry: Optional[dict],
) -> List[List[Tuple[float, float]]]:
    """
    从 GeoJSON Polygon 几何对象提取所有环

    GeoJSON Polygon 的 coordinates 为 [[ring1], [ring2], ...]，
    第一环为外环，其余为内环（孔洞）。
    """
    if not geometry or geometry.get("type") != "Polygon":
        return []
    coords = geometry.get("coordinates", [])
    rings = []
    for ring in coords:
        rings.append([(pt[0], pt[1]) for pt in ring])
    return rings


def _geojson_point(
    geometry: Optional[dict],
) -> Optional[Tuple[float, float]]:
    """从 GeoJSON Point 几何对象提取 (lon, lat) 坐标"""
    if not geometry or geometry.get("type") != "Point":
        return None
    coords = geometry.get("coordinates", [])
    if len(coords) >= 2:
        return (coords[0], coords[1])
    return None


def _geometry_intersects_polygon(
    geometry: Optional[dict],
    polygon: Optional[dict],
) -> bool:
    """
    判断 GeoJSON 几何对象是否与 GeoJSON Polygon 相交

    支持 Point（点在面内）和 Polygon（面面相交）两种类型。
    """
    if not polygon:
        return True  # 没有围栏 = 不限制区域

    sub_rings = _geojson_polygon_rings(polygon)
    if not sub_rings:
        return True

    if not geometry:
        return False

    geo_type = geometry.get("type", "")

    # Point 类型：点在面内
    if geo_type == "Point":
        pt = _geojson_point(geometry)
        if pt is None:
            return False
        return _point_in_polygon(pt, sub_rings[0])

    # Polygon 类型：面面相交检测
    if geo_type == "Polygon":
        notam_rings = _geojson_polygon_rings(geometry)
        if not notam_rings:
            return False
        # 外环相交判断
        return _polygons_intersect(notam_rings[0], sub_rings[0])

    # MultiPolygon / LineString 等其他类型 —— 保守放行
    return True


# ============================================================
# 订阅管理器
# ============================================================
class SubscriptionManager:
    """
    NOTAM 订阅管理器 —— CRUD 操作 + NOTAM 匹配

    订阅数据持久化于 data/subscriptions.json
    """

    def __init__(self, subscriptions_file: Optional[str] = None):
        """
        初始化订阅管理器

        Args:
            subscriptions_file: 订阅 JSON 文件路径，默认为 data/subscriptions.json
        """
        self.subscriptions_file = subscriptions_file or SUBSCRIPTIONS_FILE
        self._subscriptions: Dict[str, Subscription] = {}  # id -> Subscription
        self._load()

    # --------------------------------------------------------
    # 数据加载与持久化
    # --------------------------------------------------------
    def _load(self) -> None:
        """从 JSON 文件加载订阅数据"""
        if not os.path.exists(self.subscriptions_file):
            logger.info("订阅文件不存在，将使用空订阅表: %s", self.subscriptions_file)
            self._subscriptions = {}
            return

        try:
            with open(self.subscriptions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            subs_list = data.get("subscriptions", []) if isinstance(data, dict) else []
            for sub_data in subs_list:
                sub = Subscription.from_dict(sub_data)
                self._subscriptions[sub.id] = sub

            logger.info("已加载 %d 条订阅", len(self._subscriptions))
        except Exception as e:
            logger.error("加载订阅文件失败: %s", e)
            self._subscriptions = {}

    def _save(self) -> None:
        """保存订阅数据到 JSON 文件"""
        os.makedirs(os.path.dirname(self.subscriptions_file), exist_ok=True)
        data = {
            "subscriptions": [s.to_dict() for s in self._subscriptions.values()]
        }
        try:
            with open(self.subscriptions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存订阅文件失败: %s", e)

    # --------------------------------------------------------
    # CRUD 操作
    # --------------------------------------------------------
    def create_subscription(
        self,
        name: str,
        user_id: str,
        area_polygon: Optional[Dict] = None,
        fir_codes: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        channels: Optional[List[str]] = None,
        email: str = "",
        webhook_url: str = "",
    ) -> Subscription:
        """
        创建新订阅

        Args:
            name:           订阅名称
            user_id:        所属用户 ID
            area_polygon:   地理围栏 GeoJSON Polygon（可选）
            fir_codes:      FIR 代码列表（可选）
            keywords:       关键词列表（可选）
            channels:       通知渠道列表（可选）
            email:          邮件推送目标地址（可选）
            webhook_url:    Webhook 推送目标 URL（可选）

        Returns:
            创建的 Subscription 对象
        """
        sub = Subscription(
            name=name,
            user_id=user_id,
            area_polygon=area_polygon,
            fir_codes=fir_codes or [],
            keywords=keywords or [],
            channels=channels or [],
            email=email,
            webhook_url=webhook_url,
        )
        self._subscriptions[sub.id] = sub
        self._save()
        logger.info("创建订阅: %s (%s) 用户: %s", sub.id, sub.name, user_id)
        return sub

    def get_subscription(self, sub_id: str) -> Optional[Subscription]:
        """根据 ID 获取订阅"""
        return self._subscriptions.get(sub_id)

    def update_subscription(
        self,
        sub_id: str,
        **kwargs,
    ) -> Optional[Subscription]:
        """
        更新订阅属性

        支持更新 name, area_polygon, fir_codes, keywords,
        channels, email, webhook_url 等字段。

        Args:
            sub_id: 订阅 ID
            **kwargs: 要更新的字段键值对

        Returns:
            更新后的 Subscription 对象，订阅不存在则返回 None
        """
        sub = self._subscriptions.get(sub_id)
        if sub is None:
            return None

        for key, val in kwargs.items():
            if hasattr(sub, key) and key not in ("id", "user_id", "created_at"):
                setattr(sub, key, val)

        self._save()
        logger.info("更新订阅: %s", sub_id)
        return sub

    def delete_subscription(self, sub_id: str) -> bool:
        """删除订阅"""
        if sub_id in self._subscriptions:
            del self._subscriptions[sub_id]
            self._save()
            logger.info("删除订阅: %s", sub_id)
            return True
        return False

    # --------------------------------------------------------
    # 查询接口
    # --------------------------------------------------------
    def get_user_subscriptions(self, user_id: str) -> List[Subscription]:
        """获取指定用户的所有订阅列表"""
        return [s for s in self._subscriptions.values()
                if s.user_id == user_id]

    def get_all_subscriptions(self) -> List[Subscription]:
        """获取全部订阅列表"""
        return list(self._subscriptions.values())

    # --------------------------------------------------------
    # NOTAM 匹配
    # --------------------------------------------------------
    @staticmethod
    def match_notam(
        notam_feature: dict,
        subscription: Subscription,
    ) -> bool:
        """
        检查 NOTAM 是否匹配订阅条件

        匹配逻辑采用 AND 语义：地理围栏 + FIR + 关键词
        三项条件中，凡用户配置了（非空）的条件均需满足。
        未配置的条件视为"不限"，自动通过。

        Args:
            notam_feature: NOTAM GeoJSON Feature 对象（含 geometry + properties）
            subscription:  订阅对象

        Returns:
            是否匹配
        """
        if not notam_feature:
            return False

        props = notam_feature.get("properties", {})
        geometry = notam_feature.get("geometry")

        # 1. FIR 代码匹配
        if subscription.fir_codes:
            notam_fir = props.get("fir", "")
            if notam_fir and notam_fir not in subscription.fir_codes:
                return False

        # 2. 关键词匹配（大小写不敏感，在原始文本 + 编号中搜索）
        if subscription.keywords:
            raw = props.get("raw_message", "")
            code = props.get("notam_code", "")
            text = f"{raw} {code}".upper()
            matched = any(kw.upper() in text for kw in subscription.keywords)
            if not matched:
                return False

        # 3. 地理围栏匹配
        if subscription.area_polygon:
            if not _geometry_intersects_polygon(geometry, subscription.area_polygon):
                return False

        return True

    def find_matching_subscriptions(
        self,
        notam_feature: dict,
    ) -> List[Subscription]:
        """
        查找所有匹配某条 NOTAM 的订阅

        遍历全部订阅，返回 match_notam 为 True 的列表。
        用于新 NOTAM 到达时触发批量通知。

        Args:
            notam_feature: NOTAM GeoJSON Feature 对象

        Returns:
            匹配的 Subscription 列表
        """
        return [s for s in self._subscriptions.values()
                if self.match_notam(notam_feature, s)]
