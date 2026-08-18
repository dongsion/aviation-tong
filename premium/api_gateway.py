# -*- coding: utf-8 -*-
"""
RESTful API 网关 (premium/api_gateway.py)

功能概述:
    为航空通 NOTAM 可视化系统提供统一的 RESTful API 入口，包括:
      - API Key 认证
      - 令牌桶限流 (RateLimiter)
      - NOTAM / 发射计划 / 卫星数据查询
      - 飞行计划 NOTAM 影响分析
      - 订阅管理

设计要点:
    - 全部使用 Python 标准库，无需第三方依赖
    - 标准 JSON 响应格式: {"success": bool, "data": ..., "error": ...}
    - 数据源读取项目 data/ 目录下的 JSON 文件
    - 令牌桶算法: 每个 API Key 独立配额，按时间匀速补充令牌
    - 订阅数据使用内存存储 (可扩展为数据库)

Python 3.11+ 兼容
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

# 导入飞行计划分析器
# 同时支持包内导入 (from premium.api_gateway import ...) 和脚本直接运行
try:
    from .flight_plan import (
        FlightPlan,
        FlightPlanAnalyzer,
        AnalysisResult,
    )
except ImportError:  # 作为脚本直接运行时回退到绝对导入
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from flight_plan import (
        FlightPlan,
        FlightPlanAnalyzer,
        AnalysisResult,
    )


# ============================================================
#  令牌桶限流器
# ============================================================

@dataclass
class TokenBucket:
    """
    令牌桶数据结构

    属性:
        capacity:    桶容量 (最大令牌数)
        tokens:      当前令牌数
        refill_rate:  令牌补充速率 (令牌/秒)
        last_refill:  上次补充时间戳
    """
    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float


class RateLimiter:
    """
    令牌桶限流器

    每个 API Key 拥有独立的令牌桶，按时间匀速补充令牌。
    每次请求消耗 1 个令牌；令牌不足时拒绝 (触发限流)。

    用法::

        limiter = RateLimiter(capacity=100, refill_rate=10)  # 100 令牌, 每秒补 10
        if limiter.allow("user_api_key"):
            # 处理请求
        else:
            # 返回 429 限流
    """

    def __init__(self, capacity: float = 100, refill_rate: float = 10.0):
        """
        初始化限流器

        参数:
            capacity:    默认桶容量 (每个用户的最大令牌数)
            refill_rate: 默认令牌补充速率 (令牌/秒)
        """
        self._default_capacity = float(capacity)
        self._default_refill_rate = float(refill_rate)
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str,
              capacity: Optional[float] = None,
              refill_rate: Optional[float] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        尝试消耗 1 个令牌

        参数:
            key:         API Key / 用户标识
            capacity:    可选的自定义桶容量 (覆盖默认值)
            refill_rate: 可选的自定义补充速率

        返回:
            (是否允许, 信息字典)
            信息字典包含: remaining (剩余令牌), limit (容量), reset_at (重置时间戳)
        """
        with self._lock:
            now = time.monotonic()
            cap = float(capacity) if capacity is not None else self._default_capacity
            rate = float(refill_rate) if refill_rate is not None else self._default_refill_rate

            # 获取或创建令牌桶
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    capacity=cap,
                    tokens=cap,  # 初始满桶
                    refill_rate=rate,
                    last_refill=now,
                )

            bucket = self._buckets[key]

            # 更新桶容量和速率 (支持动态调整)
            if bucket.capacity != cap:
                bucket.capacity = cap
            if bucket.refill_rate != rate:
                bucket.refill_rate = rate

            # 补充令牌
            elapsed = now - bucket.last_refill
            if elapsed > 0:
                bucket.tokens = min(
                    bucket.capacity,
                    bucket.tokens + elapsed * bucket.refill_rate
                )
                bucket.last_refill = now

            # 尝试消耗令牌
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                allowed = True
            else:
                allowed = False

            # 计算重置时间 (令牌桶满需要的时间)
            if bucket.refill_rate > 0:
                seconds_to_full = max(
                    0.0,
                    (bucket.capacity - bucket.tokens) / bucket.refill_rate
                )
                reset_at = time.time() + seconds_to_full
            else:
                reset_at = time.time() + 3600

            info = {
                "remaining": round(bucket.tokens, 1),
                "limit": int(bucket.capacity),
                "reset_at": reset_at,
            }

            return (allowed, info)

    def get_status(self, key: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 Key 的当前限流状态

        返回:
            {"remaining": float, "limit": int, "refill_rate": float} 或 None
        """
        with self._lock:
            if key not in self._buckets:
                return None

            bucket = self._buckets[key]
            now = time.monotonic()
            elapsed = now - bucket.last_refill
            current_tokens = min(
                bucket.capacity,
                bucket.tokens + elapsed * bucket.refill_rate
            )

            return {
                "remaining": round(current_tokens, 1),
                "limit": int(bucket.capacity),
                "refill_rate": bucket.refill_rate,
            }

    def reset(self, key: str) -> None:
        """重置指定 Key 的令牌桶 (令牌填满)"""
        with self._lock:
            if key in self._buckets:
                bucket = self._buckets[key]
                bucket.tokens = bucket.capacity
                bucket.last_refill = time.monotonic()


# ============================================================
#  API Key 用户信息
# ============================================================

@dataclass
class ApiKeyInfo:
    """
    API Key 关联的用户信息

    属性:
        api_key:    API Key 字符串
        user_id:    用户标识
        user_name:  用户名称
        plan:       订阅计划 (free, pro, enterprise)
        rate_capacity:    限流桶容量
        rate_refill:     限流补充速率 (令牌/秒)
    """
    api_key: str
    user_id: str
    user_name: str
    plan: str = "free"
    rate_capacity: float = 60.0
    rate_refill: float = 1.0  # 每秒 1 个令牌 → 每分钟 60 个请求


# ============================================================
#  订阅数据结构
# ============================================================

@dataclass
class Subscription:
    """
    用户订阅记录

    属性:
        subscription_id: 订阅唯一 ID
        user_id:         用户标识
        type:            订阅类型 (notam / launch / satellite)
        filter:          过滤条件 (如 {"fir": "ZBPE", "type": "danger"})
        callback_url:    回调通知 URL (可选)
        created_at:      创建时间
        active:          是否活跃
    """
    subscription_id: str
    user_id: str
    type: str
    filter: Dict[str, Any] = field(default_factory=dict)
    callback_url: str = ""
    created_at: str = ""
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
#  API 响应工具函数
# ============================================================

def success_response(data: Any,
                     status: int = 200,
                     extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    构造成功响应

    返回: {"success": True, "data": ..., "error": None, ...}
    """
    resp = {
        "success": True,
        "data": data,
        "error": None,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        resp.update(extra)
    return resp


def error_response(error: str,
                    status: int = 400,
                    error_code: str = "",
                    extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    构造错误响应

    返回: {"success": False, "data": None, "error": ..., ...}
    """
    resp = {
        "success": False,
        "data": None,
        "error": error,
        "error_code": error_code,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        resp.update(extra)
    return resp


# ============================================================
#  API 网关
# ============================================================

class APIGateway:
    """
    RESTful API 网关

    统一处理所有 API 请求，包含认证、限流、路由分发。

    用法::

        gateway = APIGateway(data_dir="/path/to/aviation-tong/data")

        # 处理请求
        response = gateway.handle_request(
            path="/api/v1/notams",
            method="GET",
            headers={"X-API-Key": "your_key"},
            query_params={"type": "danger"},
            body=None,
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
    """

    # API 版本前缀
    API_PREFIX = "/api/v1"

    def __init__(self,
                 data_dir: Optional[str] = None,
                 api_keys: Optional[Dict[str, ApiKeyInfo]] = None,
                 rate_limiter: Optional[RateLimiter] = None):
        """
        初始化 API 网关

        参数:
            data_dir:     项目 data 目录路径 (读取 JSON 数据文件)
            api_keys:     API Key 字典 {api_key: ApiKeyInfo}
            rate_limiter: 自定义限流器 (不传则使用默认配置)
        """
        # 推断 data 目录路径
        if data_dir is None:
            # 默认: premium/../data/
            premium_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(os.path.dirname(premium_dir), "data")
        self.data_dir = data_dir

        # API Key 注册表
        self._api_keys: Dict[str, ApiKeyInfo] = dict(api_keys) if api_keys else {}

        # 限流器
        self.rate_limiter = rate_limiter or RateLimiter(capacity=60, refill_rate=1.0)

        # 订阅存储 (内存)
        self._subscriptions: Dict[str, Subscription] = {}
        self._sub_lock = threading.Lock()

        # 飞行计划分析器
        self._flight_plan_analyzer = FlightPlanAnalyzer(data_dir=data_dir)

        # 数据缓存 (带过期时间)
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = 60.0  # 缓存 60 秒
        self._cache_lock = threading.Lock()

        # 注册路由: {path: {method: {"handler": callable, "auth": bool}}}
        self._routes: Dict[str, Dict[str, Dict[str, Any]]] = self._register_routes()

        # 请求计数
        self._request_count = 0
        self._request_lock = threading.Lock()

    # ----------------------------------------------------------
    #  路由注册
    # ----------------------------------------------------------

    def _register_routes(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        注册 API 路由表

        返回: {path: {method: {"handler": callable, "auth": bool}}}

        每个路径可注册多个 HTTP 方法 (如 GET + POST)。
        """
        routes: Dict[str, Dict[str, Dict[str, Any]]] = {
            f"{self.API_PREFIX}/notams": {},
            f"{self.API_PREFIX}/launches": {},
            f"{self.API_PREFIX}/satellites": {},
            f"{self.API_PREFIX}/flight-plan/analyze": {},
            f"{self.API_PREFIX}/subscriptions": {},
            f"{self.API_PREFIX}/health": {},
        }

        routes[f"{self.API_PREFIX}/notams"]["GET"] = {
            "handler": self._handle_get_notams,
            "auth": True,
        }
        routes[f"{self.API_PREFIX}/launches"]["GET"] = {
            "handler": self._handle_get_launches,
            "auth": True,
        }
        routes[f"{self.API_PREFIX}/satellites"]["GET"] = {
            "handler": self._handle_get_satellites,
            "auth": True,
        }
        routes[f"{self.API_PREFIX}/flight-plan/analyze"]["POST"] = {
            "handler": self._handle_analyze_flight_plan,
            "auth": True,
        }
        routes[f"{self.API_PREFIX}/subscriptions"]["GET"] = {
            "handler": self._handle_get_subscriptions,
            "auth": True,
        }
        routes[f"{self.API_PREFIX}/subscriptions"]["POST"] = {
            "handler": self._handle_create_subscription,
            "auth": True,
        }
        routes[f"{self.API_PREFIX}/health"]["GET"] = {
            "handler": self._handle_health_check,
            "auth": False,
        }

        return routes

    # ----------------------------------------------------------
    #  主入口
    # ----------------------------------------------------------

    def handle_request(self,
                       path: str,
                       method: str,
                       headers: Optional[Dict[str, str]] = None,
                       query_params: Optional[Dict[str, str]] = None,
                       body: Optional[Union[str, bytes, dict]] = None
                       ) -> Dict[str, Any]:
        """
        统一处理 API 请求

        参数:
            path:         请求路径 (如 "/api/v1/notams")
            method:       HTTP 方法 ("GET", "POST" 等)
            headers:      请求头字典
            query_params: 查询参数字典
            body:         请求体 (字符串、字节或字典)

        返回:
            标准 JSON 响应字典: {"success": bool, "data": ..., "error": ...}
        """
        headers = headers or {}
        query_params = query_params or {}
        method = method.upper().strip()

        # 请求计数
        with self._request_lock:
            self._request_count += 1

        # 1. 路由匹配
        path_routes = self._routes.get(path)
        if path_routes is None:
            return error_response(
                f"未找到路径: {path}",
                status=404,
                error_code="NOT_FOUND"
            )

        # 2. HTTP 方法匹配
        route = path_routes.get(method)
        if route is None:
            # 路径存在但方法不匹配
            allowed_methods = list(path_routes.keys())
            return error_response(
                f"方法不允许: 期望 {', '.join(allowed_methods)}, 收到 {method}",
                status=405,
                error_code="METHOD_NOT_ALLOWED"
            )

        # 3. 认证 (需要认证的路由)
        user_info: Optional[ApiKeyInfo] = None
        if route["auth"]:
            api_key = self._extract_api_key(headers)
            if not api_key:
                return error_response(
                    "缺少 API Key，请在请求头中提供 X-API-Key 或 Authorization: Bearer <key>",
                    status=401,
                    error_code="MISSING_API_KEY"
                )

            user_info = self._authenticate(api_key)
            if user_info is None:
                return error_response(
                    "API Key 无效或已过期",
                    status=401,
                    error_code="INVALID_API_KEY"
                )

            # 4. 限流
            allowed, rate_info = self.rate_limiter.allow(
                api_key,
                capacity=user_info.rate_capacity,
                refill_rate=user_info.rate_refill,
            )
            if not allowed:
                return error_response(
                    "请求频率超限，请稍后重试",
                    status=429,
                    error_code="RATE_LIMITED",
                    extra={"rate_limit": rate_info}
                )

        # 5. 解析请求体
        parsed_body = self._parse_body(body)

        # 6. 调用处理器
        try:
            handler = route["handler"]
            context = {
                "user_info": user_info,
                "headers": headers,
            }
            result = handler(query_params, parsed_body, context)
            return result

        except Exception as e:
            return error_response(
                f"服务器内部错误: {e}",
                status=500,
                error_code="INTERNAL_ERROR"
            )

    # ----------------------------------------------------------
    #  认证
    # ----------------------------------------------------------

    def _authenticate(self, api_key: str) -> Optional[ApiKeyInfo]:
        """
        验证 API Key

        参数:
            api_key: API Key 字符串

        返回:
            ApiKeyInfo 用户信息 (验证成功) 或 None (验证失败)
        """
        return self._api_keys.get(api_key.strip())

    def _extract_api_key(self, headers: Dict[str, str]) -> Optional[str]:
        """
        从请求头中提取 API Key

        优先级:
            1. X-API-Key 头
            2. Authorization: Bearer <key>
            3. Authorization: <key>
        """
        # X-API-Key 头
        api_key = headers.get("X-API-Key") or headers.get("x-api-key")
        if api_key:
            return api_key.strip()

        # Authorization 头
        auth = headers.get("Authorization") or headers.get("authorization")
        if auth:
            auth = auth.strip()
            if auth.startswith("Bearer "):
                return auth[7:].strip()
            return auth

        return None

    # ----------------------------------------------------------
    #  限流
    # ----------------------------------------------------------

    def _rate_limit(self, user_id: str,
                    capacity: Optional[float] = None,
                    refill_rate: Optional[float] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        检查用户请求是否在限流配额内

        参数:
            user_id:   用户标识
            capacity:  可选自定义桶容量
            refill_rate: 可选自定义补充速率

        返回:
            (是否允许, 限流信息字典)
        """
        return self.rate_limiter.allow(user_id, capacity=capacity, refill_rate=refill_rate)

    # ----------------------------------------------------------
    #  请求体解析
    # ----------------------------------------------------------

    def _parse_body(self, body: Optional[Union[str, bytes, dict]]) -> Optional[dict]:
        """
        解析请求体为字典

        支持: dict (直接返回), str/bytes (尝试 JSON 解析)
        """
        if body is None:
            return None

        if isinstance(body, dict):
            return body

        if isinstance(body, (str, bytes)):
            text = body.decode("utf-8") if isinstance(body, bytes) else body
            text = text.strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(f"请求体 JSON 解析失败: {e}")

        return None

    # ----------------------------------------------------------
    #  数据文件加载 (带缓存)
    # ----------------------------------------------------------

    def _load_data_file(self, filename: str) -> Optional[dict]:
        """
        加载 data 目录下的 JSON 文件 (带缓存)

        参数:
            filename: 文件名 (如 "notams.json")

        返回:
            JSON 字典或 None (文件不存在或解析失败)
        """
        # 检查缓存
        cache_key = filename
        with self._cache_lock:
            if cache_key in self._cache:
                data, expire_at = self._cache[cache_key]
                if time.time() < expire_at:
                    return data

        # 读取文件
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        # 写入缓存
        with self._cache_lock:
            self._cache[cache_key] = (data, time.time() + self._cache_ttl)

        return data

    def _clear_cache(self) -> None:
        """清除所有缓存"""
        with self._cache_lock:
            self._cache.clear()

    # ----------------------------------------------------------
    #  端点处理器: NOTAM 列表
    # ----------------------------------------------------------

    def _handle_get_notams(self,
                            query_params: Dict[str, str],
                            body: Optional[dict],
                            context: Dict[str, Any]) -> Dict[str, Any]:
        """
        GET /api/v1/notams - 获取 NOTAM 列表

        支持查询参数:
            type:   按类型过滤 (如 "danger", "restricted", 可逗号分隔多个)
            active: 按活跃状态过滤 ("true" / "false")
            bbox:   按边界框过滤 (min_lon,min_lat,max_lon,max_lat)
            fir:    按飞行情报区过滤
            limit:  返回数量限制 (默认 100)
            offset: 偏移量 (默认 0)
        """
        data = self._load_data_file("notams.json")
        if data is None:
            return error_response("NOTAM 数据文件不可用", status=503, error_code="DATA_UNAVAILABLE")

        features = data.get("features", [])
        metadata = data.get("metadata", {})

        # --- 过滤 ---
        # type 过滤
        type_filter = query_params.get("type", "")
        if type_filter:
            types = {t.strip().lower() for t in type_filter.split(",") if t.strip()}
            features = [
                f for f in features
                if f.get("properties", {}).get("type", "").lower() in types
            ]

        # active 过滤
        active_filter = query_params.get("active", "")
        if active_filter:
            want_active = active_filter.lower() == "true"
            features = [
                f for f in features
                if f.get("properties", {}).get("is_active", True) == want_active
            ]

        # fir 过滤
        fir_filter = query_params.get("fir", "")
        if fir_filter:
            firs = {f.strip().upper() for f in fir_filter.split(",") if f.strip()}
            features = [
                f for f in features
                if f.get("properties", {}).get("fir", "").upper() in firs
            ]

        # bbox 过滤
        bbox_str = query_params.get("bbox", "")
        if bbox_str:
            try:
                parts = [float(x) for x in bbox_str.split(",")]
                if len(parts) == 4:
                    min_lon, min_lat, max_lon, max_lat = parts
                    features = [
                        f for f in features
                        if self._feature_in_bbox(f, min_lon, min_lat, max_lon, max_lat)
                    ]
            except ValueError:
                pass

        # --- 分页 ---
        total = len(features)
        try:
            limit = int(query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        try:
            offset = int(query_params.get("offset", "0"))
        except ValueError:
            offset = 0

        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        page_features = features[offset:offset + limit]

        return success_response({
            "features": page_features,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "returned": len(page_features),
            },
            "metadata": metadata,
        })

    def _feature_in_bbox(self,
                          feature: Dict[str, Any],
                          min_lon: float, min_lat: float,
                          max_lon: float, max_lat: float) -> bool:
        """
        检查 GeoJSON Feature 的几何是否在边界框内
        """
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates")
        if not coords:
            return False

        def check_coords(c: Any) -> bool:
            """递归检查坐标是否在 bbox 内"""
            if not isinstance(c, list):
                return False
            if len(c) >= 2 and all(isinstance(v, (int, float)) for v in c[:2]):
                lon, lat = c[0], c[1]
                return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
            for item in c:
                if check_coords(item):
                    return True
            return False

        return check_coords(coords)

    # ----------------------------------------------------------
    #  端点处理器: 发射计划
    # ----------------------------------------------------------

    def _handle_get_launches(self,
                              query_params: Dict[str, str],
                              body: Optional[dict],
                              context: Dict[str, Any]) -> Dict[str, Any]:
        """
        GET /api/v1/launches - 获取火箭/卫星发射计划

        支持查询参数:
            country: 按国家代码过滤 (如 "CHN", "USA")
            upcoming: 仅返回即将发射的 ("true" / "false")
            limit:    返回数量限制 (默认 50)
            offset:   偏移量
        """
        data = self._load_data_file("launches.json")
        if data is None:
            return error_response("发射计划数据文件不可用", status=503, error_code="DATA_UNAVAILABLE")

        features = data.get("features", [])
        metadata = data.get("metadata", {})

        # country 过滤
        country = query_params.get("country", "")
        if country:
            countries = {c.strip().upper() for c in country.split(",") if c.strip()}
            features = [
                f for f in features
                if f.get("properties", {}).get("country_code", "").upper() in countries
            ]

        # upcoming 过滤
        upcoming = query_params.get("upcoming", "")
        if upcoming:
            want_upcoming = upcoming.lower() == "true"
            features = [
                f for f in features
                if f.get("properties", {}).get("is_upcoming", False) == want_upcoming
            ]

        # 分页
        total = len(features)
        try:
            limit = int(query_params.get("limit", "50"))
        except ValueError:
            limit = 50
        try:
            offset = int(query_params.get("offset", "0"))
        except ValueError:
            offset = 0

        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        page_features = features[offset:offset + limit]

        return success_response({
            "features": page_features,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "returned": len(page_features),
            },
            "metadata": metadata,
        })

    # ----------------------------------------------------------
    #  端点处理器: 卫星数据
    # ----------------------------------------------------------

    def _handle_get_satellites(self,
                                query_params: Dict[str, str],
                                body: Optional[dict],
                                context: Dict[str, Any]) -> Dict[str, Any]:
        """
        GET /api/v1/satellites - 获取卫星 TLE 数据

        支持查询参数:
            category: 按类别过滤 (如 "stations", "starlink", "weather", "beidou", "visual")
            name:     按名称模糊搜索
            limit:    返回数量限制 (默认 100，卫星数据量大，建议限制)
            offset:   偏移量
        """
        data = self._load_data_file("satellites.json")
        if data is None:
            return error_response("卫星数据文件不可用", status=503, error_code="DATA_UNAVAILABLE")

        satellites = data.get("satellites", [])
        metadata = data.get("metadata", {})

        # category 过滤
        category = query_params.get("category", "")
        if category:
            categories = {c.strip().lower() for c in category.split(",") if c.strip()}
            satellites = [
                s for s in satellites
                if s.get("category", "").lower() in categories
            ]

        # name 搜索
        name_query = query_params.get("name", "")
        if name_query:
            name_lower = name_query.lower()
            satellites = [
                s for s in satellites
                if name_lower in s.get("name", "").lower()
            ]

        # 分页
        total = len(satellites)
        try:
            limit = int(query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        try:
            offset = int(query_params.get("offset", "0"))
        except ValueError:
            offset = 0

        limit = max(1, min(limit, 1000))
        offset = max(0, offset)

        page_sats = satellites[offset:offset + limit]

        return success_response({
            "satellites": page_sats,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "returned": len(page_sats),
            },
            "metadata": metadata,
        })

    # ----------------------------------------------------------
    #  端点处理器: 飞行计划分析
    # ----------------------------------------------------------

    def _handle_analyze_flight_plan(self,
                                     query_params: Dict[str, str],
                                     body: Optional[dict],
                                     context: Dict[str, Any]) -> Dict[str, Any]:
        """
        POST /api/v1/flight-plan/analyze - 飞行计划 NOTAM 影响分析

        请求体 JSON 格式::

            {
                "departure_icao": "ZBAA",
                "arrival_icao": "ZSPD",
                "departure_time": "2026-08-18 08:00 UTC",
                "arrival_time": "2026-08-18 10:00 UTC",
                "cruise_altitude_ft": 35000,
                "route_waypoints": [[34.5, 113.8]]
            }

        可选参数:
            notam_features: 自定义 NOTAM 要素列表 (不传则读取 data/notams.json)
        """
        if not body:
            return error_response("请求体不能为空", status=400, error_code="EMPTY_BODY")

        # 提取飞行计划参数
        required_fields = ["departure_icao", "arrival_icao"]
        for field_name in required_fields:
            if not body.get(field_name):
                return error_response(
                    f"缺少必填字段: {field_name}",
                    status=400,
                    error_code="MISSING_FIELD"
                )

        try:
            fp = FlightPlan(
                departure_icao=body["departure_icao"],
                arrival_icao=body["arrival_icao"],
                departure_time=body.get("departure_time", ""),
                arrival_time=body.get("arrival_time", ""),
                cruise_altitude_ft=float(body.get("cruise_altitude_ft", 0)),
                route_waypoints=body.get("route_waypoints", []),
            )
        except (KeyError, ValueError, TypeError) as e:
            return error_response(
                f"飞行计划参数解析失败: {e}",
                status=400,
                error_code="INVALID_PARAMS"
            )

        # 获取 NOTAM 要素 (使用请求体中的自定义数据或读取默认文件)
        notam_features = body.get("notam_features")
        if not notam_features:
            notam_data = self._load_data_file("notams.json")
            if notam_data:
                notam_features = notam_data.get("features", [])
            else:
                notam_features = []

        # 执行分析
        result = self._flight_plan_analyzer.analyze(fp, notam_features)

        return success_response(result.to_dict())

    # ----------------------------------------------------------
    #  端点处理器: 订阅管理
    # ----------------------------------------------------------

    def _handle_get_subscriptions(self,
                                   query_params: Dict[str, str],
                                   body: Optional[dict],
                                   context: Dict[str, Any]) -> Dict[str, Any]:
        """
        GET /api/v1/subscriptions - 获取当前用户的订阅列表

        查询参数:
            type: 按类型过滤 (可选)
        """
        user_info = context.get("user_info")
        if not user_info:
            return error_response("用户未认证", status=401, error_code="UNAUTHORIZED")

        type_filter = query_params.get("type", "")

        with self._sub_lock:
            subs = [
                sub for sub in self._subscriptions.values()
                if sub.user_id == user_info.user_id
            ]

        # type 过滤
        if type_filter:
            subs = [s for s in subs if s.type == type_filter]

        return success_response({
            "subscriptions": [s.to_dict() for s in subs],
            "total": len(subs),
        })

    def _handle_create_subscription(self,
                                     query_params: Dict[str, str],
                                     body: Optional[dict],
                                     context: Dict[str, Any]) -> Dict[str, Any]:
        """
        POST /api/v1/subscriptions - 创建订阅

        请求体 JSON 格式::

            {
                "type": "notam",          // 订阅类型: notam / launch / satellite
                "filter": {               // 过滤条件 (可选)
                    "fir": "ZBPE",
                    "type": "danger"
                },
                "callback_url": "https://..."  // 回调通知 URL (可选)
            }
        """
        user_info = context.get("user_info")
        if not user_info:
            return error_response("用户未认证", status=401, error_code="UNAUTHORIZED")

        if not body:
            return error_response("请求体不能为空", status=400, error_code="EMPTY_BODY")

        sub_type = body.get("type", "")
        if not sub_type:
            return error_response("缺少订阅类型 (type 字段)", status=400, error_code="MISSING_FIELD")

        valid_types = {"notam", "launch", "satellite"}
        if sub_type not in valid_types:
            return error_response(
                f"无效的订阅类型: {sub_type}，支持: {', '.join(sorted(valid_types))}",
                status=400,
                error_code="INVALID_TYPE"
            )

        # 创建订阅
        sub_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        subscription = Subscription(
            subscription_id=sub_id,
            user_id=user_info.user_id,
            type=sub_type,
            filter=body.get("filter", {}),
            callback_url=body.get("callback_url", ""),
            created_at=now_iso,
            active=True,
        )

        with self._sub_lock:
            self._subscriptions[sub_id] = subscription

        return success_response(
            subscription.to_dict(),
            status=201,
            extra={"message": "订阅创建成功"}
        )

    # ----------------------------------------------------------
    #  端点处理器: 健康检查
    # ----------------------------------------------------------

    def _handle_health_check(self,
                              query_params: Dict[str, str],
                              body: Optional[dict],
                              context: Dict[str, Any]) -> Dict[str, Any]:
        """
        GET /api/v1/health - 健康检查 (无需认证)
        """
        # 检查数据文件是否可用
        notams_ok = self._load_data_file("notams.json") is not None
        launches_ok = self._load_data_file("launches.json") is not None
        satellites_ok = self._load_data_file("satellites.json") is not None

        with self._sub_lock:
            sub_count = len(self._subscriptions)

        return success_response({
            "status": "ok" if all([notams_ok, launches_ok, satellites_ok]) else "degraded",
            "services": {
                "notams": "available" if notams_ok else "unavailable",
                "launches": "available" if launches_ok else "unavailable",
                "satellites": "available" if satellites_ok else "unavailable",
            },
            "registered_api_keys": len(self._api_keys),
            "total_subscriptions": sub_count,
            "total_requests": self._request_count,
            "data_dir": self.data_dir,
        })

    # ----------------------------------------------------------
    #  API Key 管理
    # ----------------------------------------------------------

    def register_api_key(self, api_key_info: ApiKeyInfo) -> None:
        """
        注册一个新的 API Key

        参数:
            api_key_info: API Key 用户信息
        """
        self._api_keys[api_key_info.api_key] = api_key_info

    def revoke_api_key(self, api_key: str) -> bool:
        """
        撤销 API Key

        返回: True 如果成功撤销, False 如果 Key 不存在
        """
        if api_key in self._api_keys:
            del self._api_keys[api_key]
            self.rate_limiter.reset(api_key)
            return True
        return False

    def list_api_keys(self) -> List[Dict[str, Any]]:
        """列出所有已注册的 API Key (不返回 Key 本身的明文)"""
        return [
            {
                "user_id": info.user_id,
                "user_name": info.user_name,
                "plan": info.plan,
                "rate_capacity": info.rate_capacity,
                "rate_refill": info.rate_refill,
                "api_key_prefix": info.api_key[:8] + "..." if len(info.api_key) > 8 else "***",
            }
            for info in self._api_keys.values()
        ]


# ============================================================
#  便捷工厂函数
# ============================================================

def create_gateway(data_dir: Optional[str] = None,
                    api_key: Optional[str] = None,
                    plan: str = "free") -> APIGateway:
    """
    快速创建一个配置好默认 API Key 的 API 网关

    参数:
        data_dir: 项目 data 目录路径
        api_key:  自定义 API Key (不传则自动生成)
        plan:     订阅计划 (free / pro / enterprise)

    返回:
        配置好的 APIGateway 实例
    """
    # 根据计划设置限流参数
    plan_configs = {
        "free": {"capacity": 60.0, "refill": 1.0},       # 60 次/分钟
        "pro": {"capacity": 600.0, "refill": 10.0},      # 600 次/分钟
        "enterprise": {"capacity": 6000.0, "refill": 100.0},  # 6000 次/分钟
    }
    config = plan_configs.get(plan, plan_configs["free"])

    if api_key is None:
        api_key = f"avt_{uuid.uuid4().hex[:24]}"

    key_info = ApiKeyInfo(
        api_key=api_key,
        user_id=f"user_{uuid.uuid4().hex[:8]}",
        user_name="默认用户",
        plan=plan,
        rate_capacity=config["capacity"],
        rate_refill=config["refill"],
    )

    gateway = APIGateway(data_dir=data_dir)
    gateway.register_api_key(key_info)

    return gateway


# ============================================================
#  模块自测 / 演示
# ============================================================

if __name__ == "__main__":
    # 创建网关并注册演示 API Key
    gateway = create_gateway(plan="pro")
    demo_key = list(gateway._api_keys.keys())[0]

    print("=" * 60)
    print("  航空通 API 网关演示")
    print("=" * 60)
    print(f"\n演示 API Key: {demo_key}")
    print(f"数据目录: {gateway.data_dir}")

    # 1. 健康检查 (无需认证)
    print("\n--- 健康检查 ---")
    resp = gateway.handle_request(
        path="/api/v1/health",
        method="GET",
        headers={},
        query_params={},
        body=None,
    )
    print(json.dumps(resp, ensure_ascii=False, indent=2))

    headers = {"X-API-Key": demo_key}

    # 2. 获取 NOTAM 列表
    print("\n--- 获取 NOTAM 列表 (type=danger) ---")
    resp = gateway.handle_request(
        path="/api/v1/notams",
        method="GET",
        headers=headers,
        query_params={"type": "danger", "limit": "3"},
        body=None,
    )
    if resp["success"]:
        print(f"成功: 返回 {resp['data']['pagination']['returned']} 条 NOTAM")
        for f in resp["data"]["features"]:
            props = f.get("properties", {})
            print(f"  - {props.get('notam_code')}: {props.get('type_name')} [{props.get('fir')}]")
    else:
        print(f"失败: {resp['error']}")

    # 3. 获取发射计划
    print("\n--- 获取发射计划 (country=CHN) ---")
    resp = gateway.handle_request(
        path="/api/v1/launches",
        method="GET",
        headers=headers,
        query_params={"country": "CHN", "limit": "5"},
        body=None,
    )
    if resp["success"]:
        print(f"成功: 返回 {resp['data']['pagination']['returned']} 条发射计划")
        for f in resp["data"]["features"]:
            props = f.get("properties", {})
            print(f"  - {props.get('name')}: {props.get('net_display')}")
    else:
        print(f"失败: {resp['error']}")

    # 4. 获取卫星数据
    print("\n--- 获取卫星数据 (category=stations) ---")
    resp = gateway.handle_request(
        path="/api/v1/satellites",
        method="GET",
        headers=headers,
        query_params={"category": "stations", "limit": "5"},
        body=None,
    )
    if resp["success"]:
        print(f"成功: 返回 {resp['data']['pagination']['returned']} 颗卫星")
        for s in resp["data"]["satellites"]:
            print(f"  - {s.get('name')} (NORAD: {s.get('norad_id')})")
    else:
        print(f"失败: {resp['error']}")

    # 5. 飞行计划分析
    print("\n--- 飞行计划 NOTAM 影响分析 ---")
    resp = gateway.handle_request(
        path="/api/v1/flight-plan/analyze",
        method="POST",
        headers=headers,
        query_params={},
        body=json.dumps({
            "departure_icao": "ZBAA",
            "arrival_icao": "ZSPD",
            "departure_time": "2026-08-18 08:00 UTC",
            "arrival_time": "2026-08-18 10:00 UTC",
            "cruise_altitude_ft": 35000,
            "route_waypoints": [[34.5, 113.8]],
        }),
    )
    if resp["success"]:
        data = resp["data"]
        print(f"成功: 检测到 {data['total_affected']} 条受影响 NOTAM")
        print(f"  严重: {data['critical_count']} / 警告: {data['warning_count']} / 提示: {data['info_count']}")
        print(f"  预计绕飞: {data['route_deviation_nm']:.1f} 海里")
        print(f"  摘要: {data['summary']}")
    else:
        print(f"失败: {resp['error']}")

    # 6. 创建订阅
    print("\n--- 创建订阅 ---")
    resp = gateway.handle_request(
        path="/api/v1/subscriptions",
        method="POST",
        headers=headers,
        query_params={},
        body=json.dumps({
            "type": "notam",
            "filter": {"fir": "ZBPE", "type": "danger"},
            "callback_url": "https://example.com/callback",
        }),
    )
    if resp["success"]:
        sub = resp["data"]
        print(f"成功: 订阅 ID = {sub['subscription_id']}")
        print(f"  类型: {sub['type']}, 过滤: {sub['filter']}")
    else:
        print(f"失败: {resp['error']}")

    # 7. 获取订阅列表
    print("\n--- 获取订阅列表 ---")
    resp = gateway.handle_request(
        path="/api/v1/subscriptions",
        method="GET",
        headers=headers,
        query_params={},
        body=None,
    )
    if resp["success"]:
        print(f"成功: 共 {resp['data']['total']} 条订阅")
    else:
        print(f"失败: {resp['error']}")

    # 8. 认证失败测试
    print("\n--- 认证失败测试 ---")
    resp = gateway.handle_request(
        path="/api/v1/notams",
        method="GET",
        headers={"X-API-Key": "invalid_key"},
        query_params={},
        body=None,
    )
    print(f"结果: success={resp['success']}, error={resp['error']}, status={resp['status']}")

    print("\n" + "=" * 60)
    print("  演示结束")
    print("=" * 60)
