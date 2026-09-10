#!/usr/bin/env python3
"""PPT-Agent-Studio 一键启动入口脚本 (Root Entry Point)

支持：
1. 默认一键启动全栈服务 (FastAPI 统一托管后端 API + WebSocket + 前端静态页面)：
   python main.py

2. 开发模式 (同时启动后端 8000 与前端 Vite 热重载 5173)：
   python main.py --dev

3. 重新构建前端产物：
   python main.py --build-frontend
"""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检查指定端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def build_frontend_if_needed(force: bool = False) -> bool:
    """检查并在需要时构建前端静态产物。"""
    index_html = FRONTEND_DIST_DIR / "index.html"
    if not force and index_html.exists():
        return True

    print("\n📦 检测到前端产物缺失或指定重新构建，正在执行 npm run build...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        res = subprocess.run(
            [npm_cmd, "run", "build"],
            cwd=str(FRONTEND_DIR),
            check=True
        )
        if res.returncode == 0:
            print("✅ 前端构建完成！")
            return True
    except FileNotFoundError:
        print("⚠️ 未找到 npm 命令。如需使用内置前端，请确保已安装 Node.js。")
    except subprocess.CalledProcessError as e:
        print(f"❌ 前端构建失败: {e}")
    return False


def start_vite_dev_server() -> subprocess.Popen | None:
    """在开发模式下启动前端 Vite 服务器。"""
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    print("🚀 正在启动前端 Vite 热更新开发服务 (http://localhost:5173)...")
    try:
        proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        return proc
    except Exception as e:
        print(f"⚠️ 无法启动前端开发服务: {e}")
        return None


def open_browser_delayed(url: str, delay: float = 1.2):
    """延迟并在后台线程打开浏览器。"""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    t = threading.Thread(target=_open, daemon=True)
    t.start()


def print_banner(host: str, port: int, dev_mode: bool):
    """输出美观的控制台启动信息。"""
    web_url = "http://localhost:5173" if dev_mode else f"http://{host}:{port}"
    api_docs_url = f"http://{host}:{port}/docs"
    mode_text = "开发热重载模式 (FastAPI:8000 + Vite:5173)" if dev_mode else "统一生产模式 (FastAPI 托管前后端与 WS)"

    print("=" * 64)
    print("  🎨 PPT-Agent-Studio 协同制作平台 一键启动成功")
    print("=" * 64)
    print(f"  👉 Web 访问入口: {web_url}")
    print(f"  📖 API 接口文档: {api_docs_url}")
    print(f"  ⚙️ 运行工作模式: {mode_text}")
    print("  💡 按 Ctrl+C 可安全终止所有服务")
    print("=" * 64 + "\n")


def main():
    parser = argparse.ArgumentParser(description="PPT-Agent-Studio 一键启动入口")
    parser.add_argument("--host", default="127.0.0.1", help="后端监听主机 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="后端端口号 (默认: 8000)")
    parser.add_argument("--dev", action="store_true", help="启动前端 Vite 开发服务器 (开发热更新)")
    parser.add_argument("--build-frontend", action="store_true", help="启动前强制重新构建前端 dist")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", default=False, help="启用后端热重载")

    args = parser.parse_args()

    # 1. 确保构建产物或开发服务就绪
    if args.build_frontend:
        build_frontend_if_needed(force=True)
    elif not args.dev and not (FRONTEND_DIST_DIR / "index.html").exists():
        build_frontend_if_needed(force=False)

    # 2. 检查端口占用情况
    if is_port_in_use(args.port, args.host):
        print(f"\n⚠️ 提示: 后端端口 {args.port} 目前已被占用。")
        print("如果是此前已在运行的 PPT-Agent 服务，可直接在浏览器中打开: http://127.0.0.1:8000")
        print("如需强制重新启动，请先关闭占用该端口的进程。\n")
        sys.exit(1)

    # 3. 如果启用了 --dev 模式，启动前端 Vite 子进程
    vite_proc = None
    if args.dev:
        vite_proc = start_vite_dev_server()
        if vite_proc:
            def cleanup_vite():
                if vite_proc and vite_proc.poll() is None:
                    print("\n🛑 正在停止前端 Vite 开发服务...")
                    try:
                        vite_proc.terminate()
                        vite_proc.wait(timeout=3)
                    except Exception:
                        vite_proc.kill()
            atexit.register(cleanup_vite)

    # 4. 自动拉起浏览器
    target_url = "http://localhost:5173" if args.dev else f"http://{args.host}:{args.port}"
    if not args.no_browser:
        open_browser_delayed(target_url, delay=1.0)

    # 5. 打印状态横幅
    print_banner(args.host, args.port, args.dev)

    # 6. 启动后端 Uvicorn
    import uvicorn
    try:
        uvicorn.run(
            "backend.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 PPT-Agent-Studio 服务已优雅退出。")


if __name__ == "__main__":
    main()
