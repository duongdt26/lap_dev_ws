#!/usr/bin/env python3
"""Đọc ngrok local API và ghi web/amr_dashboard/config.json (1 tunnel free)."""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else 'web/amr_dashboard/config.json'

    try:
        with urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=5) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f'Không đọc được ngrok API (127.0.0.1:4040): {exc}', file=sys.stderr)
        return 1

    web_url = None

    for tunnel in data.get('tunnels', []):
        name = tunnel.get('name', '')
        public_url = tunnel.get('public_url', '')
        addr = str(tunnel.get('config', {}).get('addr', ''))

        if name in ('amr', 'amr-web') or addr.endswith(':8080') or addr == '8080':
            web_url = public_url
            break

    if not web_url and data.get('tunnels'):
        web_url = data['tunnels'][0].get('public_url')

    parsed = urlparse(web_url or '')
    ros_host = parsed.netloc or (web_url or '').replace('https://', '').replace('http://', '')

    payload = {
        'webUrl': web_url or '',
        'rosbridgeHost': ros_host,
        'rosbridgePath': '/rosbridge',
        'singleTunnel': True,
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
        f.write('\n')

    print(json.dumps(payload, indent=2))
    if not web_url:
        print('Cảnh báo: chưa có tunnel ngrok trên port 8080', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
