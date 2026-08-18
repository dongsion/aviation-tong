#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - 付费功能后端包 (premium)

提供用户认证与权限管理、NOTAM 订阅管理、多渠道通知推送三大核心能力：

  - auth:           Tier 层级 / User 用户 / AuthManager 认证管理
  - subscription:   Subscription 订阅 / SubscriptionManager 订阅管理 + NOTAM 匹配
  - notifications:  NotificationChannel 渠道 / NotificationService 推送服务

用法示例::

    from premium import AuthManager, Tier
    from premium import SubscriptionManager
    from premium import NotificationService

    # 认证
    auth = AuthManager()
    user = auth.verify_api_key("ak_xxx")

    # 订阅管理
    sub_mgr = SubscriptionManager()
    sub = sub_mgr.create_subscription(
        name="华东危险区订阅",
        user_id="user_001",
        fir_codes=["ZSHA"],
        keywords=["DANGER", "ROCKET"],
        channels=["email", "webhook"],
        email="pilot@example.com",
        webhook_url="https://example.com/hook",
    )

    # 通知推送
    notifier = NotificationService()
    for matched_sub in sub_mgr.find_matching_subscriptions(notam_feature):
        notifier.notify_new_notam(matched_sub, notam_feature)
"""
from .auth import Tier, User, AuthManager, Permission
from .notifications import NotificationChannel, NotificationService
from .subscription import Subscription, SubscriptionManager

__all__ = [
    # 认证与权限
    "Tier",
    "User",
    "AuthManager",
    "Permission",
    # 订阅管理
    "Subscription",
    "SubscriptionManager",
    # 通知推送
    "NotificationChannel",
    "NotificationService",
]

__version__ = "1.0.0"
