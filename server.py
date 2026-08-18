#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - 本地开发服务器
提供静态文件服务 + 数据刷新接口 + 付费功能 API 网关
"""
import os
import sys
import subprocess
import threading
import json
import time
import traceback
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO_ROOT, 'data')

# 刷新状态
refresh_status = {
    'running': False,
    'last_run': None,
    'last_result': None,
    'last_error': None,
}

# ============================================================
# 付费功能模块 - 懒加载 (避免导入失败影响基础功能)
# ============================================================
_api_gateway = None

def get_api_gateway():
    """懒加载 API 网关，避免未安装依赖时影响基础功能"""
    global _api_gateway
    if _api_gateway is None:
        try:
            from premium.api_gateway import APIGateway
            _api_gateway = APIGateway(data_dir=DATA_DIR)
            print("[付费功能] API 网关已加载")
        except Exception as e:
            print(f"[付费功能] API 网关加载失败 (付费功能不可用): {e}")
            _api_gateway = False  # 标记为不可用
    return _api_gateway if _api_gateway is not False else None


class AviationHandler(SimpleHTTPRequestHandler):
    """自定义请求处理器 - 支持基础 API + 付费 API"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        # 基础 API
        if parsed.path == '/api/refresh':
            self.handle_refresh()
            return
        if parsed.path == '/api/status':
            self.handle_status()
            return

        # 付费 API (v1)
        if parsed.path.startswith('/api/v1/'):
            self.handle_premium_api('GET', parsed, None)
            return

        # 静态文件
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        # 付费 API (v1)
        if parsed.path.startswith('/api/v1/'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else b''
            self.handle_premium_api('POST', parsed, body)
            return

        self.send_error(405, 'Method Not Allowed')

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, Authorization')
        self.end_headers()

    def handle_premium_api(self, method, parsed, body):
        """处理付费功能 API 请求"""
        gateway = get_api_gateway()
        if gateway is None:
            self._json_response(503, {
                'success': False,
                'error': '付费功能未启用，请安装 premium 模块',
            })
            return

        # 解析查询参数
        query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

        # 解析请求体
        body_json = None
        if body:
            try:
                body_json = json.loads(body.decode('utf-8'))
            except json.JSONDecodeError:
                self._json_response(400, {
                    'success': False,
                    'error': '请求体 JSON 格式错误',
                })
                return

        # 请求头传递给网关 (API Key 从请求头中提取)
        request_headers = dict(self.headers)

        # 调用 API 网关
        try:
            result = gateway.handle_request(
                path=parsed.path,
                method=method,
                headers=request_headers,
                query_params=query_params,
                body=body_json,
            )
            status = result.get('status', 200)
            self._json_response(status, result)
        except Exception as e:
            traceback.print_exc()
            self._json_response(500, {
                'success': False,
                'error': f'服务器内部错误: {e}',
            })

    def _json_response(self, status, data):
        """发送 JSON 响应"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def handle_refresh(self):
        """触发数据刷新 - 运行 main.py"""
        global refresh_status

        if refresh_status['running']:
            self.send_response(409)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(json.dumps({
                'ok': False,
                'message': '数据刷新正在进行中，请稍候...',
            }).encode('utf-8'))
            return

        # 异步运行 main.py
        refresh_status['running'] = True
        thread = threading.Thread(target=run_refresh, daemon=True)
        thread.start()

        self.send_response(202)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(json.dumps({
            'ok': True,
            'message': '数据刷新已启动，请等待几秒后自动更新',
        }).encode('utf-8'))

    def handle_status(self):
        """返回刷新状态"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        self.wfile.write(json.dumps({
            'running': refresh_status['running'],
            'last_run': refresh_status['last_run'],
            'last_result': refresh_status['last_result'],
            'last_error': refresh_status['last_error'],
            'premium_enabled': get_api_gateway() is not None,
        }).encode('utf-8'))

    def end_headers(self):
        # 禁止缓存 JSON 文件，确保前端总是拿到最新数据
        if self.path.endswith('.json'):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        # 简化日志
        msg = format % args
        if '/api/' in msg or 'GET /data/' in msg:
            sys.stderr.write(f"[{self.log_date_time_string()}] {msg}\n")
        elif '404' in msg:
            sys.stderr.write(f"[404] {msg}\n")


def run_refresh():
    """在后台运行 main.py 刷新数据"""
    global refresh_status
    try:
        start = time.time()
        result = subprocess.run(
            [sys.executable, 'main.py'],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = round(time.time() - start, 1)

        if result.returncode == 0:
            refresh_status['last_result'] = f'成功 ({elapsed}s)'
            refresh_status['last_error'] = None
            print(f"[刷新成功] 耗时 {elapsed}s")

            # 刷新后检查订阅匹配 (付费功能)
            try:
                _check_subscriptions_after_refresh()
            except Exception as e:
                print(f"[订阅检查] 失败: {e}")
        else:
            refresh_status['last_result'] = f'失败 (exit {result.returncode})'
            refresh_status['last_error'] = result.stderr[-500:] if result.stderr else '未知错误'
            print(f"[刷新失败] {result.stderr[-200:]}")

    except subprocess.TimeoutExpired:
        refresh_status['last_result'] = '超时 (>300s)'
        refresh_status['last_error'] = '数据刷新超时'
        print("[刷新超时]")
    except Exception as e:
        refresh_status['last_result'] = f'异常: {e}'
        refresh_status['last_error'] = str(e)
        print(f"[刷新异常] {e}")
    finally:
        refresh_status['running'] = False
        refresh_status['last_run'] = time.strftime('%Y-%m-%d %H:%M:%S')


def _check_subscriptions_after_refresh():
    """数据刷新后检查 NOTAM 订阅匹配 (付费功能)"""
    try:
        from premium.subscription import SubscriptionManager
        from premium.notifications import NotificationService

        sub_manager = SubscriptionManager(subscriptions_file=os.path.join(DATA_DIR, 'subscriptions.json'))
        notif_service = NotificationService()

        # 加载最新 NOTAM 数据
        notam_file = os.path.join(DATA_DIR, 'notams.json')
        if not os.path.exists(notam_file):
            return

        with open(notam_file, 'r', encoding='utf-8') as f:
            notam_data = json.load(f)

        features = notam_data.get('features', [])
        all_subs = sub_manager.get_all_subscriptions()

        if not all_subs or not features:
            return

        # 检查每条 NOTAM 是否匹配订阅
        notified_count = 0
        for feature in features:
            matching_subs = sub_manager.find_matching_subscriptions(feature)
            for sub in matching_subs:
                # TODO: 实际场景中需要记录已通知的 NOTAM，避免重复推送
                # 这里仅做演示，实际部署时需要加去重逻辑
                success = notif_service.notify_new_notam(sub, feature)
                if success:
                    notified_count += 1

        if notified_count > 0:
            print(f"[订阅推送] 已发送 {notified_count} 条 NOTAM 通知")

    except ImportError:
        pass  # 付费模块未安装，跳过
    except Exception as e:
        print(f"[订阅检查] 异常: {e}")


def main():
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    # 默认绑定 127.0.0.1 防止局域网暴露，通过参数可改为 0.0.0.0
    host = '127.0.0.1'
    if len(sys.argv) > 2:
        host = sys.argv[2]

    server = ThreadingHTTPServer((host, port), AviationHandler)
    print(f"{'=' * 60}")
    print(f"  航空通 开发服务器 (多线程)")
    print(f"  地址: http://localhost:{port}")
    print(f"  刷新API: http://localhost:{port}/api/refresh")
    print(f"  状态API: http://localhost:{port}/api/status")
    print(f"  付费API: http://localhost:{port}/api/v1/*")
    print(f"  绑定地址: {host}")
    # 预加载付费模块
    gateway = get_api_gateway()
    if gateway:
        print(f"  付费功能: ✓ 已启用")
    else:
        print(f"  付费功能: ✗ 未启用 (安装 premium 模块后可用)")
    print(f"{'=' * 60}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        server.server_close()


if __name__ == '__main__':
    main()
