#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - 通知推送服务

支持三种通知渠道：
  - EMAIL:  通过 SMTP 发送邮件
  - WEBHOOK: 发送 HTTP POST 到用户自定义 Webhook
  - WECHAT:  通过企业微信群机器人推送 Markdown 消息

配置从 config.ini 的 [PREMIUM] 段读取。
notify_new_notam 方法将匹配的 NOTAM 转为通知内容并推送到订阅配置的所有渠道。
"""
import json
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import requests
import configparser

logger = logging.getLogger(__name__)

# ============================================================
# 路径配置
# ============================================================
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO_ROOT, 'config.ini')


# ============================================================
# 通知渠道枚举
# ============================================================
class NotificationChannel(Enum):
    """通知推送渠道"""
    EMAIL = "email"
    WEBHOOK = "webhook"
    WECHAT = "wechat"


# ============================================================
# 通知推送服务
# ============================================================
class NotificationService:
    """
    通知推送服务

    从 config.ini 的 [PREMIUM] 段加载 SMTP、Webhook、企业微信配置，
    提供邮件发送、Webhook 推送、企业微信推送及 NOTAM 通知编排接口。
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化通知服务并加载配置

        Args:
            config_path: config.ini 路径，默认为项目根目录下的 config.ini
        """
        self.config_path = config_path or CONFIG_FILE
        self._load_config()

    # --------------------------------------------------------
    # 配置加载
    # --------------------------------------------------------
    def _load_config(self) -> None:
        """从 config.ini 读取 [PREMIUM] 配置段"""
        # 初始化默认值
        self.smtp_host: str = ""
        self.smtp_port: int = 465
        self.smtp_user: str = ""
        self.smtp_password: str = ""
        self.smtp_from: str = ""
        self.smtp_use_tls: bool = True
        self.webhook_timeout: int = 10
        self.wechat_webhook_url: str = ""

        # 使用 inline_comment_prefixes 支持行内注释（如 smtp_port = 465 # SSL）
        config = configparser.ConfigParser(inline_comment_prefixes=('#',))
        if os.path.exists(self.config_path):
            config.read(self.config_path, encoding='utf-8')

        if config.has_section('PREMIUM'):
            self.smtp_host = config.get(
                'PREMIUM', 'smtp_host', fallback='')
            self.smtp_port = config.getint(
                'PREMIUM', 'smtp_port', fallback=465)
            self.smtp_user = config.get(
                'PREMIUM', 'smtp_user', fallback='')
            self.smtp_password = config.get(
                'PREMIUM', 'smtp_password', fallback='')
            self.smtp_from = config.get(
                'PREMIUM', 'smtp_from', fallback='')
            self.smtp_use_tls = config.getboolean(
                'PREMIUM', 'smtp_use_tls', fallback=True)
            self.webhook_timeout = config.getint(
                'PREMIUM', 'webhook_timeout', fallback=10)
            self.wechat_webhook_url = config.get(
                'PREMIUM', 'wechat_webhook_url', fallback='')

        logger.debug(
            "通知配置已加载: SMTP=%s:%d, 企业微信=%s",
            self.smtp_host, self.smtp_port,
            "已配置" if self.wechat_webhook_url else "未配置",
        )

    # --------------------------------------------------------
    # 邮件推送
    # --------------------------------------------------------
    def send_email(self, to: str, subject: str, body: str) -> bool:
        """
        通过 SMTP 发送邮件

        端口 465 使用 SMTP_SSL（隐式 TLS），
        其他端口使用 SMTP + STARTTLS（如果 smtp_use_tls 为 True）。

        Args:
            to:      收件人邮箱地址
            subject: 邮件主题
            body:    邮件正文（纯文本）

        Returns:
            是否发送成功
        """
        if not self.smtp_host or not self.smtp_user:
            logger.warning("SMTP 未配置（host/user 为空），跳过邮件发送")
            return False

        if not to:
            logger.warning("收件人地址为空，跳过邮件发送")
            return False

        try:
            # 构建邮件
            msg = MIMEMultipart("alternative")
            msg['From'] = self.smtp_from or self.smtp_user
            msg['To'] = to
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # 根据端口选择连接方式
            if self.smtp_port == 465:
                # 隐式 TLS（SSL）
                server = smtplib.SMTP_SSL(
                    self.smtp_host, self.smtp_port, timeout=30)
            else:
                # 普通 SMTP，按需启用 STARTTLS
                server = smtplib.SMTP(
                    self.smtp_host, self.smtp_port, timeout=30)
                if self.smtp_use_tls:
                    server.starttls()

            try:
                if self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                sender = self.smtp_from or self.smtp_user
                server.sendmail(sender, [to], msg.as_string())
                logger.info("邮件已发送至 %s: %s", to, subject)
                return True
            finally:
                server.quit()

        except smtplib.SMTPException as e:
            logger.error("SMTP 邮件发送失败（协议错误）: %s", e)
            return False
        except Exception as e:
            logger.error("邮件发送异常: %s", e)
            return False

    # --------------------------------------------------------
    # Webhook 推送
    # --------------------------------------------------------
    def send_webhook(self, url: str, payload: Dict[str, Any]) -> bool:
        """
        发送 HTTP POST 请求到用户自定义 Webhook

        Args:
            url:     Webhook 目标 URL
            payload: JSON 请求体

        Returns:
            是否推送成功
        """
        if not url:
            logger.warning("Webhook URL 为空，跳过推送")
            return False

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'AviationTong-Notifier/1.0',
                },
                timeout=self.webhook_timeout,
            )
            resp.raise_for_status()
            logger.info("Webhook 推送成功: %s (HTTP %d)", url, resp.status_code)
            return True

        except requests.exceptions.Timeout:
            logger.error("Webhook 推送超时: %s", url)
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("Webhook 连接失败: %s — %s", url, e)
            return False
        except requests.exceptions.HTTPError as e:
            logger.error("Webhook HTTP 错误: %s — %s", url, e)
            return False
        except Exception as e:
            logger.error("Webhook 推送异常: %s — %s", url, e)
            return False

    # --------------------------------------------------------
    # 企业微信推送
    # --------------------------------------------------------
    def send_wechat(
        self,
        title: str,
        content: str,
        mentioned_list: Optional[List[str]] = None,
    ) -> bool:
        """
        通过企业微信群机器人发送 Markdown 消息

        Webhook URL 从 [PREMIUM] wechat_webhook_url 配置项读取。
        支持使用 @用户（通过 userid 或手机号列表）。

        Args:
            title:          消息标题（作为 Markdown 一级标题）
            content:        消息正文（Markdown 格式）
            mentioned_list: 被 @ 的用户 userid 或手机号列表（可选）

        Returns:
            是否推送成功
        """
        if not self.wechat_webhook_url:
            logger.warning("企业微信 Webhook 未配置，跳过推送")
            return False

        # 企业微信群机器人 Markdown 消息格式
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"## {title}\n\n{content}",
                "mentioned_list": mentioned_list or [],
            }
        }

        try:
            resp = requests.post(
                self.wechat_webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=self.webhook_timeout,
            )
            resp.raise_for_status()

            # 企业微信返回 JSON，检查 errcode
            result = resp.json()
            errcode = result.get("errcode", 0)
            if errcode != 0:
                logger.error(
                    "企业微信推送失败: errcode=%d, errmsg=%s",
                    errcode, result.get("errmsg", ""),
                )
                return False

            logger.info("企业微信消息推送成功: %s", title)
            return True

        except requests.exceptions.Timeout:
            logger.error("企业微信推送超时")
            return False
        except Exception as e:
            logger.error("企业微信推送异常: %s", e)
            return False

    # --------------------------------------------------------
    # NOTAM 通知编排
    # --------------------------------------------------------
    @staticmethod
    def _format_notam_content(
        subscription: Any,
        notam_feature: dict,
    ) -> Dict[str, str]:
        """
        生成 NOTAM 通知内容（标题 + 正文）

        从 NOTAM Feature 的 properties 中提取关键信息，
        格式化为适合邮件和企业微信的文本。

        Args:
            subscription:  订阅对象（鸭子类型，需有 name 属性）
            notam_feature: NOTAM GeoJSON Feature

        Returns:
            {"subject": ..., "body": ..., "title": ..., "markdown": ...}
        """
        props = notam_feature.get("properties", {})
        code = props.get("notam_code", "未知")
        notam_type = props.get("type_name", props.get("type", "未知"))
        fir = props.get("fir", "未知")
        time_str = props.get("time", "未知")
        altitude = props.get("altitude", "未标注")
        raw = props.get("raw_message", "")[:500]

        sub_name = getattr(subscription, "name", "未命名订阅")

        subject = f"[航空通] 新 NOTAM 告警: {code} ({notam_type})"

        body = (
            f"==============================\n"
            f"  航空通 NOTAM 订阅告警\n"
            f"==============================\n"
            f"\n"
            f"订阅名称:   {sub_name}\n"
            f"NOTAM 编号: {code}\n"
            f"类型:       {notam_type}\n"
            f"FIR:        {fir}\n"
            f"有效时间:   {time_str}\n"
            f"高度限制:   {altitude}\n"
            f"推送时间:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"\n"
            f"--- 原始 NOTAM 文本 ---\n"
            f"{raw}\n"
        )

        # 企业微信 Markdown 格式（带颜色高亮）
        markdown = (
            f"**NOTAM 编号: **`{code}`\n"
            f"**类型: **{notam_type}\n"
            f"**FIR: **`{fir}`\n"
            f"**有效时间: **{time_str}\n"
            f"**高度限制: **{altitude}\n"
            f"**订阅: **{sub_name}\n"
            f"\n"
            f"> {raw[:200]}"
        )

        return {
            "subject": subject,
            "body": body,
            "title": subject,
            "markdown": markdown,
        }

    def notify_new_notam(
        self,
        subscription: Any,
        notam_feature: dict,
    ) -> Dict[str, bool]:
        """
        对一条匹配订阅的新 NOTAM 生成通知内容并推送到所有渠道

        遍历订阅的 channels 列表，依次通过对应渠道发送通知。
        每个渠道独立处理异常，互不影响。

        Args:
            subscription:  订阅对象（鸭子类型，需有 name, channels,
                           email, webhook_url 属性）
            notam_feature: NOTAM GeoJSON Feature

        Returns:
            各渠道发送结果，如 {"email": True, "webhook": False}
        """
        if not notam_feature:
            logger.warning("NOTAM Feature 为空，跳过通知")
            return {}

        # 生成通知内容
        content = self._format_notam_content(subscription, notam_feature)

        results: Dict[str, bool] = {}
        channels = getattr(subscription, "channels", []) or []

        for ch_str in channels:
            # 将字符串转为 NotificationChannel 枚举
            try:
                channel = NotificationChannel(ch_str)
            except ValueError:
                logger.warning("未知通知渠道，跳过: %s", ch_str)
                continue

            # ----------------------------------------------------
            # 邮件渠道
            # ----------------------------------------------------
            if channel == NotificationChannel.EMAIL:
                email_to = getattr(subscription, "email", "") or self.smtp_from
                if email_to:
                    results["email"] = self.send_email(
                        email_to,
                        content["subject"],
                        content["body"],
                    )
                else:
                    logger.warning("邮件渠道未配置收件地址，跳过")
                    results["email"] = False

            # ----------------------------------------------------
            # Webhook 渠道
            # ----------------------------------------------------
            elif channel == NotificationChannel.WEBHOOK:
                webhook_url = getattr(subscription, "webhook_url", "")
                if webhook_url:
                    payload = {
                        "event": "new_notam",
                        "subscription": {
                            "id": getattr(subscription, "id", ""),
                            "name": getattr(subscription, "name", ""),
                        },
                        "notam": notam_feature.get("properties", {}),
                        "geometry": notam_feature.get("geometry"),
                        "subject": content["subject"],
                        "body": content["body"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    results["webhook"] = self.send_webhook(webhook_url, payload)
                else:
                    logger.warning("Webhook 渠道未配置 URL，跳过")
                    results["webhook"] = False

            # ----------------------------------------------------
            # 企业微信渠道
            # ----------------------------------------------------
            elif channel == NotificationChannel.WECHAT:
                results["wechat"] = self.send_wechat(
                    content["title"],
                    content["markdown"],
                )

        # 汇总日志
        sent = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info(
            "NOTAM 通知推送完成: 订阅=%s, 渠道成功 %d/%d",
            getattr(subscription, "name", "?"), sent, total,
        )

        return results
