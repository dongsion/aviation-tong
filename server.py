#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空通 - 本地开发服务器
提供静态文件服务 + /api/refresh 接口触发实时数据刷新
"""
import os
import sys
import subprocess
import threading
import json
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO_ROOT, 'data')

# 刷新状态
refresh_status = {
    'running': False,
    'last_run': None,
    'last_result': None,
    'last_error': None,
}


class AviationHandler(SimpleHTTPRequestHandler):
    """自定义请求处理器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        # API 接口
        if parsed.path == '/api/refresh':
            self.handle_refresh()
            return

        if parsed.path == '/api/status':
            self.handle_status()
            return

        # 静态文件
        super().do_GET()

    def handle_refresh(self):
        """触发数据刷新 - 运行 main.py"""
        global refresh_status

        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')

        if refresh_status['running']:
            self.send_response(409)
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
        else:
            refresh_status['last_result'] = f'失败 (exit {result.returncode})'
            refresh_status['last_error'] = result.stderr[-500:] if result.stderr else '未知错误'
            print(f"[刷新失败] {result.stderr[-200:]}")

    except subprocess.TimeoutExpired:
        refresh_status['last_result'] = '超时 (>120s)'
        refresh_status['last_error'] = '数据刷新超时'
        print("[刷新超时]")
    except Exception as e:
        refresh_status['last_result'] = f'异常: {e}'
        refresh_status['last_error'] = str(e)
        print(f"[刷新异常] {e}")
    finally:
        refresh_status['running'] = False
        refresh_status['last_run'] = time.strftime('%Y-%m-%d %H:%M:%S')


def main():
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    server = HTTPServer(('0.0.0.0', port), AviationHandler)
    print(f"{'=' * 50}")
    print(f"  航空通 开发服务器")
    print(f"  地址: http://localhost:{port}")
    print(f"  刷新API: http://localhost:{port}/api/refresh")
    print(f"  状态API: http://localhost:{port}/api/status")
    print(f"{'=' * 50}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        server.server_close()


if __name__ == '__main__':
    main()
