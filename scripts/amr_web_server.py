#!/usr/bin/env python3
"""
Serve AMR dashboard (static) + proxy WebSocket /rosbridge → rosbridge :9090.

Dùng cho ngrok free (chỉ 1 tunnel public):
  python3 scripts/amr_web_server.py
  ngrok http 8080   # hoặc ./scripts/start_ngrok.sh

LAN vẫn có thể dùng http.server + ws://IP:9090 như cũ.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

try:
    from aiohttp import WSMsgType, web
except ImportError:
    print('Thiếu aiohttp. Cài: pip install -r scripts/requirements-web.txt', file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / 'web' / 'amr_dashboard'
DEFAULT_PORT = 8080
ROSBRIDGE_WS = 'ws://127.0.0.1:9090'


async def rosbridge_proxy(request: web.Request) -> web.WebSocketResponse:
    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)

    import aiohttp

    session = aiohttp.ClientSession()
    try:
        async with session.ws_connect(ROSBRIDGE_WS) as ws_server:

            async def client_to_server() -> None:
                async for msg in ws_client:
                    if msg.type == WSMsgType.TEXT:
                        await ws_server.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await ws_server.send_bytes(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break

            async def server_to_client() -> None:
                async for msg in ws_server:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await ws_client.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await ws_client.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break

            await asyncio.gather(client_to_server(), server_to_client())
    except Exception as exc:
        print(f'rosbridge proxy lỗi: {exc}', file=sys.stderr)
    finally:
        await session.close()

    return ws_client


async def run_server(host: str, port: int) -> None:
    if not STATIC_DIR.is_dir():
        print(f'Không tìm thấy thư mục web: {STATIC_DIR}', file=sys.stderr)
        raise SystemExit(1)

    app = web.Application()
    app.router.add_get('/rosbridge', rosbridge_proxy)

    async def serve_index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / 'index.html')

    app.router.add_get('/', serve_index)
    # show_index=True đủ cho aiohttp cũ (không có kwarg index=)
    app.router.add_static('/', STATIC_DIR, show_index=True)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    print(f'AMR web server: http://{host}:{port}')
    print(f'  Static  : {STATIC_DIR}')
    print(f'  Rosbridge proxy: ws(s)://<host>/rosbridge → {ROSBRIDGE_WS}')
    print('Ngrok free: ./scripts/start_ngrok.sh (1 tunnel → port này)')

    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    await stop.wait()
    await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description='AMR dashboard + rosbridge WebSocket proxy')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    asyncio.run(run_server(args.host, args.port))


if __name__ == '__main__':
    main()
