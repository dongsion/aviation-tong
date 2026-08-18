#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - 用户认证与权限管理模块

提供基于 API Key 的用户认证、分层权限控制（FREE / PRO / TEAM / ENTERPRISE）。
权限矩阵：
  - FREE:       基础 NOTAM 查看
  - PRO:        订阅 + 推送 + 飞行计划 + API（1000 次/月）
  - TEAM:       团队管理 + API（10 万次/月）+ 卫星过境
  - ENTERPRISE: 全部功能 + 私有部署

用户凭据持久化于 data/api_keys.json
"""
import json
import os
import logging
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set, Dict, List

logger = logging.getLogger(__name__)

# ============================================================
# 路径配置 —— 与项目根目录保持一致
# ============================================================
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, 'data')
API_KEYS_FILE = os.path.join(DATA_DIR, 'api_keys.json')


# ============================================================
# 用户订阅层级
# ============================================================
class Tier(Enum):
    """用户订阅层级枚举"""
    FREE = "free"
    PRO = "pro"
    TEAM = "team"
    ENTERPRISE = "enterprise"


# ============================================================
# 权限常量
# ============================================================
class Permission:
    """权限标识常量"""
    BASIC_VIEW = "basic_view"                # 基础 NOTAM 查看
    NOTAM_SUBSCRIBE = "notam_subscribe"       # NOTAM 订阅管理
    PUSH_NOTIFICATION = "push_notification"  # 推送通知
    FLIGHT_PLAN = "flight_plan"              # 飞行计划提交
    API_ACCESS = "api_access"                # API 接口访问
    TEAM_MANAGEMENT = "team_management"       # 团队管理
    SATELLITE_TRANSIT = "satellite_transit"   # 卫星过境提醒
    PRIVATE_DEPLOYMENT = "private_deployment"  # 私有部署


# ============================================================
# 权限矩阵 —— 每个层级拥有的权限集合
# ============================================================
TIER_PERMISSIONS: Dict[Tier, Set[str]] = {
    Tier.FREE: {
        Permission.BASIC_VIEW,
    },
    Tier.PRO: {
        Permission.BASIC_VIEW,
        Permission.NOTAM_SUBSCRIBE,
        Permission.PUSH_NOTIFICATION,
        Permission.FLIGHT_PLAN,
        Permission.API_ACCESS,
    },
    Tier.TEAM: {
        Permission.BASIC_VIEW,
        Permission.NOTAM_SUBSCRIBE,
        Permission.PUSH_NOTIFICATION,
        Permission.FLIGHT_PLAN,
        Permission.API_ACCESS,
        Permission.TEAM_MANAGEMENT,
        Permission.SATELLITE_TRANSIT,
    },
    Tier.ENTERPRISE: {
        Permission.BASIC_VIEW,
        Permission.NOTAM_SUBSCRIBE,
        Permission.PUSH_NOTIFICATION,
        Permission.FLIGHT_PLAN,
        Permission.API_ACCESS,
        Permission.TEAM_MANAGEMENT,
        Permission.SATELLITE_TRANSIT,
        Permission.PRIVATE_DEPLOYMENT,
    },
}

# 各层级 API 调用上限（次/月），None 表示无限制
TIER_API_LIMITS: Dict[Tier, Optional[int]] = {
    Tier.FREE: 0,          # 免费用户无 API 权限
    Tier.PRO: 1000,        # PRO: 1000 次/月
    Tier.TEAM: 100000,     # TEAM: 10 万次/月
    Tier.ENTERPRISE: None,  # 企业版无限制
}


# ============================================================
# 用户数据模型
# ============================================================
@dataclass
class User:
    """用户信息"""
    user_id: str       # 用户唯一标识
    tier: Tier         # 订阅层级
    api_key: str       # API 密钥
    name: str = ""     # 用户名/显示名

    def has_permission(self, permission: str) -> bool:
        """检查用户是否拥有指定权限"""
        return permission in TIER_PERMISSIONS.get(self.tier, set())

    @property
    def api_limit(self) -> Optional[int]:
        """获取 API 月度调用上限（None = 无限制）"""
        return TIER_API_LIMITS.get(self.tier, 0)

    def to_dict(self) -> dict:
        """转为字典（用于 JSON 序列化）"""
        return {
            "user_id": self.user_id,
            "tier": self.tier.value,
            "api_key": self.api_key,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """从字典构建用户对象"""
        tier_str = data.get("tier", "free")
        try:
            tier = Tier(tier_str)
        except ValueError:
            tier = Tier.FREE
        return cls(
            user_id=data.get("user_id", ""),
            tier=tier,
            api_key=data.get("api_key", ""),
            name=data.get("name", ""),
        )


# ============================================================
# 认证管理器
# ============================================================
class AuthManager:
    """
    认证管理器 —— 验证 API Key、检查权限

    从 data/api_keys.json 加载用户凭据，提供验证与权限检查接口。
    """

    def __init__(self, api_keys_file: Optional[str] = None):
        """
        初始化认证管理器

        Args:
            api_keys_file: API 密钥 JSON 文件路径，默认为 data/api_keys.json
        """
        self.api_keys_file = api_keys_file or API_KEYS_FILE
        self._users: Dict[str, User] = {}  # api_key -> User 映射
        self._load()

    # --------------------------------------------------------
    # 数据加载与持久化
    # --------------------------------------------------------
    def _load(self) -> None:
        """从 JSON 文件加载用户凭据"""
        if not os.path.exists(self.api_keys_file):
            logger.warning(
                "API 密钥文件不存在: %s，将使用空用户表", self.api_keys_file
            )
            self._users = {}
            return

        try:
            with open(self.api_keys_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            users_list = data.get("users", []) if isinstance(data, dict) else []
            for user_data in users_list:
                user = User.from_dict(user_data)
                if user.api_key:
                    self._users[user.api_key] = user

            logger.info("已加载 %d 个用户凭据", len(self._users))
        except Exception as e:
            logger.error("加载 API 密钥文件失败: %s", e)
            self._users = {}

    def _save(self) -> None:
        """保存用户凭据到 JSON 文件"""
        os.makedirs(os.path.dirname(self.api_keys_file), exist_ok=True)
        data = {
            "users": [u.to_dict() for u in self._users.values()]
        }
        try:
            with open(self.api_keys_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存 API 密钥文件失败: %s", e)

    # --------------------------------------------------------
    # 认证与权限检查
    # --------------------------------------------------------
    def verify_api_key(self, api_key: str) -> Optional[User]:
        """
        验证 API Key，返回对应的 User 对象

        使用恒定时间比较（secrets.compare_digest）防止时序攻击。
        验证失败返回 None。

        Args:
            api_key: 待验证的 API 密钥

        Returns:
            匹配的 User 对象，或 None
        """
        if not api_key:
            return None
        for stored_key, user in self._users.items():
            if secrets.compare_digest(stored_key, api_key):
                return user
        return None

    def check_permission(self, user: User, permission: str) -> bool:
        """
        检查用户是否拥有指定权限

        Args:
            user: 已认证的 User 对象
            permission: Permission 常量字符串

        Returns:
            是否拥有该权限
        """
        if user is None:
            return False
        return user.has_permission(permission)

    # --------------------------------------------------------
    # 用户查询与管理
    # --------------------------------------------------------
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """根据 user_id 查找用户"""
        for user in self._users.values():
            if user.user_id == user_id:
                return user
        return None

    def get_all_users(self) -> List[User]:
        """获取所有用户列表"""
        return list(self._users.values())

    @staticmethod
    def generate_api_key() -> str:
        """生成随机 API Key（前缀 ak_ + 24 字节十六进制）"""
        return f"ak_{secrets.token_hex(24)}"

    def add_user(
        self,
        user_id: str,
        tier: Tier,
        name: str = "",
        api_key: Optional[str] = None,
    ) -> User:
        """
        添加新用户并持久化保存

        Args:
            user_id: 用户唯一标识
            tier: 订阅层级
            name: 用户显示名
            api_key: 自定义 API Key（留空则自动生成）

        Returns:
            创建的 User 对象
        """
        api_key = api_key or self.generate_api_key()
        user = User(user_id=user_id, tier=tier, api_key=api_key, name=name)
        self._users[api_key] = user
        self._save()
        logger.info("新增用户: %s (%s) 层级: %s", user_id, name, tier.value)
        return user

    def remove_user(self, user_id: str) -> bool:
        """根据 user_id 删除用户"""
        target_key = None
        for key, user in self._users.items():
            if user.user_id == user_id:
                target_key = key
                break
        if target_key:
            del self._users[target_key]
            self._save()
            logger.info("已删除用户: %s", user_id)
            return True
        return False

    def update_user_tier(self, user_id: str, tier: Tier) -> Optional[User]:
        """更新用户订阅层级"""
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.tier = tier
        self._save()
        logger.info("用户 %s 层级已更新为 %s", user_id, tier.value)
        return user
