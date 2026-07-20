#!/usr/bin/env python3
"""Bridge map (~/maps) + MAP_DATA setpoint/process cho web dashboard."""

import glob
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from nav_msgs.msg import OccupancyGrid
from nav2_msgs.msg import CostmapFilterInfo
from std_msgs.msg import String
from std_srvs.srv import Trigger

from amr_web_interfaces.srv import (
    GetMapStatus,
    ListProcesses,
    LoadProcess,
    LoadSetpoints,
    LoadKeepoutZones,
    SaveMap,
    SaveProcess,
    SaveSetpoints,
    SaveKeepoutZones,
    SetActiveMap,
)

DEFAULT_MAPS_ROOT = os.path.expanduser('~/maps')
DEFAULT_MAP_DATA_ROOT = os.path.expanduser('~/MAP_DATA')
SETPOINTS_FILE = 'setpoints.json'
KEEPOUT_ZONES_FILE = 'keepout_zones.json'
SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

MAP_QOS = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)

WEB_MAP_QOS = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.VOLATILE,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)


def sanitize_map_name(name: str) -> str:
    name = (name or '').strip()
    if not name or not SAFE_NAME_RE.match(name):
        raise ValueError(f'Tên map không hợp lệ: {name!r}')
    return name


def sanitize_process_name(name: str) -> str:
    name = (name or '').strip()
    if not name:
        raise ValueError('Tên process trống')
    safe = re.sub(r'[^\w\-]', '_', name, flags=re.UNICODE)
    if not safe:
        raise ValueError(f'Tên process không hợp lệ: {name!r}')
    return safe


class MapBridgeNode(Node):
    def __init__(self):
        super().__init__('map_bridge_node')

        self.declare_parameter('map_name', '')
        self.declare_parameter('active_map_name', '')
        self.declare_parameter('maps_root', DEFAULT_MAPS_ROOT)
        self.declare_parameter('map_data_root', DEFAULT_MAP_DATA_ROOT)

        self._maps_root = os.path.expanduser(
            str(self.get_parameter('maps_root').value))
        self._map_data_root = os.path.expanduser(
            str(self.get_parameter('map_data_root').value))
        os.makedirs(self._maps_root, exist_ok=True)
        os.makedirs(self._map_data_root, exist_ok=True)

        self._latest_map = None
        self._keepout_zones = []
        self._map_sub = self.create_subscription(
            OccupancyGrid, '/map', self._on_map, MAP_QOS)
        self._web_map_pub = self.create_publisher(
            OccupancyGrid, '/web/map', WEB_MAP_QOS)
        self._data_updated_pub = self.create_publisher(
            String, '/web_data_updated', 10)
        self._keepout_mask_pub = self.create_publisher(
            OccupancyGrid, '/keepout_filter_mask', MAP_QOS)
        self._keepout_info_pub = self.create_publisher(
            CostmapFilterInfo, '/keepout_costmap_filter_info', MAP_QOS)

        self.create_service(Trigger, '/save_map', self.save_map_callback)
        self.create_service(SaveMap, '/save_map_named', self.save_map_named_cb)
        self.create_service(Trigger, '/list_maps', self.list_maps_callback)
        self.create_service(Trigger, '/request_map_sync', self.request_map_sync_cb)
        self.create_service(GetMapStatus, '/get_map_status', self.get_map_status_cb)
        self.create_service(SetActiveMap, '/set_active_map', self.set_active_map_cb)
        self.create_service(SaveSetpoints, '/save_setpoints', self.save_setpoints_cb)
        self.create_service(LoadSetpoints, '/load_setpoints', self.load_setpoints_cb)
        self.create_service(
            SaveKeepoutZones, '/save_keepout_zones', self.save_keepout_zones_cb)
        self.create_service(
            LoadKeepoutZones, '/load_keepout_zones', self.load_keepout_zones_cb)
        self.create_service(ListProcesses, '/list_processes', self.list_processes_cb)
        self.create_service(LoadProcess, '/load_process', self.load_process_cb)
        self.create_service(SaveProcess, '/save_process', self.save_process_cb)

        active_map = self._active_map()
        if active_map:
            self._ensure_data_layout(active_map)
            self._keepout_zones = self._read_keepout_zones(active_map)

        self.create_timer(1.0, self._republish_timer_cb)

        self.get_logger().info(
            f'Maps: {self._maps_root} | Setpoint/process: {self._map_data_root}')
        self.get_logger().info(
            'Services: /save_map, /list_maps, /save_setpoints, /load_setpoints,'
        )
        self.get_logger().info(
            '          /list_processes, /load_process, /save_process'
        )

    def _notify_data(self, kind: str):
        msg = String()
        msg.data = kind
        self._data_updated_pub.publish(msg)

    def _active_map(self) -> str:
        return (self.get_parameter('active_map_name').value or '').strip()

    def _resolve_map_name(self, map_name: str) -> str:
        name = (map_name or '').strip() or self._active_map()
        if not name:
            raise ValueError('Chưa có map active — nạp map trước')
        return sanitize_map_name(name)

    def _data_dir(self, map_name: str) -> str:
        return os.path.join(self._map_data_root, sanitize_map_name(map_name))

    def _init_map_data_folder(self, map_name: str) -> str:
        """Tạo MAP_DATA/{map_name}/setpoint + process và file setpoints.json rỗng."""
        name = sanitize_map_name(map_name)
        root = self._data_dir(name)
        setpoint_dir = os.path.join(root, 'setpoint')
        process_dir = os.path.join(root, 'process')
        zones_dir = os.path.join(root, 'zones')
        os.makedirs(setpoint_dir, exist_ok=True)
        os.makedirs(process_dir, exist_ok=True)
        os.makedirs(zones_dir, exist_ok=True)

        setpoints_path = os.path.join(setpoint_dir, SETPOINTS_FILE)
        if not os.path.isfile(setpoints_path):
            payload = {
                'mapName': name,
                'updatedAt': _now_iso(),
                'setpoints': [],
            }
            with open(setpoints_path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

        zones_path = os.path.join(zones_dir, KEEPOUT_ZONES_FILE)
        if not os.path.isfile(zones_path):
            payload = {
                'mapName': name,
                'updatedAt': _now_iso(),
                'zones': [],
            }
            with open(zones_path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

        self.get_logger().info(f'MAP_DATA folder: {root}')
        return root

    def _ensure_data_layout(self, map_name: str):
        self._init_map_data_folder(map_name)

    def _setpoints_path(self, map_name: str) -> str:
        return os.path.join(self._data_dir(map_name), 'setpoint', SETPOINTS_FILE)

    def _process_path(self, map_name: str, process_name: str) -> str:
        safe = sanitize_process_name(process_name)
        return os.path.join(self._data_dir(map_name), 'process', f'{safe}.json')

    def _keepout_zones_path(self, map_name: str) -> str:
        return os.path.join(
            self._data_dir(map_name), 'zones', KEEPOUT_ZONES_FILE)

    def _read_keepout_zones(self, map_name: str):
        path = self._keepout_zones_path(map_name)
        if not os.path.isfile(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            zones = raw.get('zones', []) if isinstance(raw, dict) else raw
            return self._normalize_keepout_zones(zones)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().error(f'Không thể đọc vùng cấm {path}: {exc}')
            return []

    @staticmethod
    def _normalize_keepout_zones(zones):
        if not isinstance(zones, list):
            raise ValueError('json_data phải là một mảng vùng cấm')
        normalized = []
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict):
                raise ValueError(f'Vùng cấm thứ {index + 1} không hợp lệ')
            points = zone.get('points', [])
            if not isinstance(points, list) or len(points) < 3:
                raise ValueError(
                    f'Vùng cấm thứ {index + 1} phải có ít nhất 3 điểm')
            clean_points = []
            for point in points:
                x = float(point.get('x'))
                y = float(point.get('y'))
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError('Tọa độ vùng cấm phải là số hữu hạn')
                clean_points.append({'x': x, 'y': y})
            normalized.append({
                'id': str(zone.get('id') or f'zone-{index + 1}'),
                'name': str(zone.get('name') or f'Vùng cấm {index + 1}'),
                'reason': str(zone.get('reason') or ''),
                'enabled': bool(zone.get('enabled', True)),
                'points': clean_points,
            })
        return normalized

    @staticmethod
    def _point_in_polygon(x, y, points):
        inside = False
        previous = points[-1]
        for current in points:
            x1, y1 = previous['x'], previous['y']
            x2, y2 = current['x'], current['y']
            if ((y1 > y) != (y2 > y)):
                x_at_y = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < x_at_y:
                    inside = not inside
            previous = current
        return inside

    def _publish_keepout_mask(self):
        if self._latest_map is None:
            return False

        source = self._latest_map
        info = source.info
        mask = OccupancyGrid()
        mask.header.stamp = self.get_clock().now().to_msg()
        mask.header.frame_id = source.header.frame_id or 'map'
        mask.info = info
        width = int(info.width)
        height = int(info.height)
        resolution = float(info.resolution)
        origin_x = float(info.origin.position.x)
        origin_y = float(info.origin.position.y)
        data = [0] * (width * height)

        for zone in self._keepout_zones:
            if not zone.get('enabled', True):
                continue
            points = zone['points']
            min_x = max(0, int(math.floor(
                (min(p['x'] for p in points) - origin_x) / resolution)))
            max_x = min(width - 1, int(math.ceil(
                (max(p['x'] for p in points) - origin_x) / resolution)))
            min_y = max(0, int(math.floor(
                (min(p['y'] for p in points) - origin_y) / resolution)))
            max_y = min(height - 1, int(math.ceil(
                (max(p['y'] for p in points) - origin_y) / resolution)))
            for row in range(min_y, max_y + 1):
                world_y = origin_y + (row + 0.5) * resolution
                for col in range(min_x, max_x + 1):
                    world_x = origin_x + (col + 0.5) * resolution
                    if self._point_in_polygon(world_x, world_y, points):
                        data[row * width + col] = 100

        mask.data = data
        self._keepout_mask_pub.publish(mask)

        filter_info = CostmapFilterInfo()
        filter_info.header.stamp = mask.header.stamp
        filter_info.header.frame_id = mask.header.frame_id
        filter_info.type = 0
        filter_info.filter_mask_topic = '/keepout_filter_mask'
        filter_info.base = 0.0
        filter_info.multiplier = 1.0
        self._keepout_info_pub.publish(filter_info)
        return True

    def _find_process_file(self, map_name: str, process_name: str) -> str:
        proc_name = (process_name or '').strip()
        if not proc_name:
            raise ValueError('Thiếu tên process')

        proc_dir = os.path.join(self._data_dir(map_name), 'process')
        direct = self._process_path(map_name, proc_name)
        if os.path.isfile(direct):
            return direct

        if os.path.isdir(proc_dir):
            for path in sorted(glob.glob(os.path.join(proc_dir, '*.json'))):
                try:
                    with open(path, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                    if data.get('name') == proc_name:
                        return path
                except (json.JSONDecodeError, OSError):
                    continue

        raise FileNotFoundError(f'Không tìm thấy process: {proc_name}')

    def _on_map(self, msg: OccupancyGrid):
        self._latest_map = msg
        self._web_map_pub.publish(msg)
        self._publish_keepout_mask()

    def _republish_timer_cb(self):
        if self._latest_map is not None:
            self._web_map_pub.publish(self._latest_map)

    def _publish_cached_map(self) -> bool:
        if self._latest_map is None:
            return False
        self._web_map_pub.publish(self._latest_map)
        return True

    def get_map_status_cb(self, request, response):
        del request
        if self._latest_map is None:
            response.loaded = False
            response.map_name = ''
            response.width = 0
            response.height = 0
            response.resolution = 0.0
            return response

        info = self._latest_map.info
        response.loaded = True
        response.map_name = self._active_map()
        response.width = info.width
        response.height = info.height
        response.resolution = info.resolution
        return response

    def set_active_map_cb(self, request, response):
        try:
            name = sanitize_map_name(request.map_name)
            self._init_map_data_folder(name)
            self.set_parameters([
                Parameter('active_map_name', Parameter.Type.STRING, name)
            ])
            self._keepout_zones = self._read_keepout_zones(name)
            self._publish_cached_map()
            self._publish_keepout_mask()
            response.success = True
            response.message = f'Active map: {name}'
            self._notify_data('map')
        except ValueError as exc:
            response.success = False
            response.message = str(exc)
        return response

    def request_map_sync_cb(self, request, response):
        del request
        if self._publish_cached_map():
            info = self._latest_map.info
            name = self._active_map()
            label = f' ({name})' if name else ''
            response.success = True
            response.message = (
                f'Synced map{label}: {info.width}x{info.height} '
                f'@ {info.resolution:.3f} m/cell'
            )
        else:
            response.success = False
            response.message = 'Chưa có map — chạy localization hoặc nạp map trước'
        return response

    def _save_map_files(self, name: str) -> str:
        name = sanitize_map_name(name)
        data_root = self._init_map_data_folder(name)
        out_path = os.path.join(self._maps_root, name)
        cmd = [
            'ros2', 'run', 'nav2_map_server', 'map_saver_cli',
            '-f', out_path,
        ]
        self.get_logger().info(f'Lưu map: {" ".join(cmd)}')
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or 'map_saver_cli failed')

        self.set_parameters([
            Parameter('active_map_name', Parameter.Type.STRING, name),
            Parameter('map_name', Parameter.Type.STRING, name),
        ])
        self._keepout_zones = self._read_keepout_zones(name)
        self._publish_keepout_mask()
        self._notify_data('map')
        return (
            f'Đã lưu map: {out_path}.yaml + .pgm | '
            f'MAP_DATA: {data_root}'
        )

    def save_map_named_cb(self, request, response):
        try:
            name = (request.map_name or '').strip()
            if not name:
                raise ValueError('Thiếu tên map')
            response.message = self._save_map_files(name)
            response.success = True
        except subprocess.TimeoutExpired:
            response.success = False
            response.message = 'Timeout — /map có đang publish không?'
        except Exception as exc:
            response.success = False
            response.message = str(exc)
        return response

    def save_map_callback(self, request, response):
        del request
        try:
            name = (
                self.get_parameter('map_name').get_parameter_value().string_value
                or self.get_parameter('active_map_name').get_parameter_value().string_value
            )
            response.message = self._save_map_files(name)
            response.success = True
        except subprocess.TimeoutExpired:
            response.success = False
            response.message = 'Timeout — /map có đang publish không?'
        except Exception as exc:
            response.success = False
            response.message = str(exc)
        return response

    def list_maps_callback(self, request, response):
        del request
        names = []
        if os.path.isdir(self._maps_root):
            for path in sorted(glob.glob(os.path.join(self._maps_root, '*.yaml'))):
                names.append(os.path.splitext(os.path.basename(path))[0])
        response.success = True
        response.message = ','.join(names) if names else '(chưa có map trong ~/maps)'
        return response

    def save_setpoints_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            data = json.loads(request.json_data or '[]')
            if not isinstance(data, list):
                raise ValueError('json_data phải là mảng setpoint')

            self._ensure_data_layout(map_name)
            payload = {
                'mapName': map_name,
                'updatedAt': _now_iso(),
                'setpoints': data,
            }
            path = self._setpoints_path(map_name)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

            response.success = True
            response.message = f'Đã lưu {len(data)} setpoint → {path}'
            self._notify_data('setpoints')
        except Exception as exc:
            response.success = False
            response.message = str(exc)
        return response

    def load_setpoints_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            path = self._setpoints_path(map_name)
            if not os.path.isfile(path):
                response.success = True
                response.json_data = '[]'
                response.message = 'Chưa có setpoint — trả về mảng rỗng'
                return response

            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            if isinstance(raw, dict) and 'setpoints' in raw:
                points = raw['setpoints']
            elif isinstance(raw, list):
                points = raw
            else:
                points = []
            response.success = True
            response.json_data = json.dumps(points, ensure_ascii=False)
            response.message = f'Đã tải {len(points)} setpoint'
        except Exception as exc:
            response.success = False
            response.json_data = '[]'
            response.message = str(exc)
        return response

    def save_keepout_zones_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            zones = self._normalize_keepout_zones(
                json.loads(request.json_data or '[]'))
            self._ensure_data_layout(map_name)
            path = self._keepout_zones_path(map_name)
            payload = {
                'mapName': map_name,
                'updatedAt': _now_iso(),
                'zones': zones,
            }
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

            if map_name == self._active_map():
                self._keepout_zones = zones
                response.nav2_active = self._publish_keepout_mask()
            else:
                response.nav2_active = False
            response.success = True
            response.message = (
                f'Đã lưu {len(zones)} vùng cấm và phát mask cho Nav2'
                if response.nav2_active
                else f'Đã lưu {len(zones)} vùng cấm; nạp map để kích hoạt Nav2'
            )
            self._notify_data('keepout_zones')
        except Exception as exc:
            response.success = False
            response.nav2_active = False
            response.message = str(exc)
        return response

    def load_keepout_zones_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            zones = self._read_keepout_zones(map_name)
            if map_name == self._active_map():
                self._keepout_zones = zones
                response.nav2_active = self._publish_keepout_mask()
            else:
                response.nav2_active = False
            response.success = True
            response.json_data = json.dumps(zones, ensure_ascii=False)
            response.message = f'Đã tải {len(zones)} vùng cấm'
        except Exception as exc:
            response.success = False
            response.nav2_active = False
            response.json_data = '[]'
            response.message = str(exc)
        return response

    def list_processes_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            proc_dir = os.path.join(self._data_dir(map_name), 'process')
            names = []
            if os.path.isdir(proc_dir):
                for path in sorted(glob.glob(os.path.join(proc_dir, '*.json'))):
                    try:
                        with open(path, 'r', encoding='utf-8') as fh:
                            data = json.load(fh)
                        label = data.get('name') or os.path.splitext(
                            os.path.basename(path))[0]
                        names.append(label)
                    except (json.JSONDecodeError, OSError):
                        names.append(os.path.splitext(os.path.basename(path))[0])
            response.success = True
            response.names = ','.join(names)
            response.message = f'{len(names)} process'
        except Exception as exc:
            response.success = False
            response.names = ''
            response.message = str(exc)
        return response

    def load_process_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            proc_name = (request.name or '').strip()
            if not proc_name:
                raise ValueError('Thiếu tên process')

            path = self._find_process_file(map_name, proc_name)
            if not os.path.isfile(path):
                raise FileNotFoundError(f'Không tìm thấy process: {proc_name}')

            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            response.success = True
            response.json_data = json.dumps(data, ensure_ascii=False)
            response.message = f'Đã tải process {proc_name}'
        except Exception as exc:
            response.success = False
            response.json_data = '{}'
            response.message = str(exc)
        return response

    def save_process_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            proc_name = (request.name or '').strip()
            if not proc_name:
                raise ValueError('Thiếu tên process')

            data = json.loads(request.json_data or '{}')
            if not isinstance(data, dict):
                raise ValueError('json_data phải là object JSON')

            self._ensure_data_layout(map_name)
            payload = {
                'name': proc_name,
                'steps': data.get('steps', []),
                'updatedAt': data.get('updatedAt') or _now_iso(),
            }
            path = self._process_path(map_name, proc_name)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

            response.success = True
            response.message = f'Đã lưu process → {path}'
            self._notify_data('process')
        except Exception as exc:
            response.success = False
            response.message = str(exc)
        return response


def main():
    rclpy.init()
    node = MapBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
