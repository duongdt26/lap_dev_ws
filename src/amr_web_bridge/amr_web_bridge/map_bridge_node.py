#!/usr/bin/env python3
"""Bridge map (~/maps) + MAP_DATA setpoint/process cho web dashboard."""

import glob
import json
import math
import os
import re
import subprocess
from copy import deepcopy
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
    LoadKeepoutZones,
    LoadProcess,
    LoadSetpoints,
    SaveMap,
    SaveKeepoutZones,
    SaveProcess,
    SaveSetpoints,
    SetActiveMap,
)

DEFAULT_MAPS_ROOT = os.path.expanduser('~/maps')
DEFAULT_MAP_DATA_ROOT = os.path.expanduser('~/MAP_DATA')
SETPOINTS_FILE = 'setpoints.json'
KEEPOUT_FILE = 'keepout_zones.json'
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
    # transient_local: client web/rosbridge join muộn vẫn nhận map mới nhất.
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)

FILTER_QOS = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
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
        self._map_sub = self.create_subscription(
            OccupancyGrid, '/map', self._on_map, MAP_QOS)
        self._web_map_pub = self.create_publisher(
            OccupancyGrid, '/web/map', WEB_MAP_QOS)
        self._keepout_mask_pub = self.create_publisher(
            OccupancyGrid, '/keepout_filter_mask', FILTER_QOS)
        self._keepout_info_pub = self.create_publisher(
            CostmapFilterInfo, '/keepout_costmap_filter_info', FILTER_QOS)
        self._keepout_zones_pub = self.create_publisher(
            String, '/web/keepout_zones', FILTER_QOS)
        self._data_updated_pub = self.create_publisher(
            String, '/web_data_updated', 10)

        self.create_service(Trigger, '/save_map', self.save_map_callback)
        self.create_service(SaveMap, '/save_map_named', self.save_map_named_cb)
        self.create_service(Trigger, '/list_maps', self.list_maps_callback)
        self.create_service(Trigger, '/request_map_sync', self.request_map_sync_cb)
        self.create_service(GetMapStatus, '/get_map_status', self.get_map_status_cb)
        self.create_service(SetActiveMap, '/set_active_map', self.set_active_map_cb)
        self.create_service(SaveSetpoints, '/save_setpoints', self.save_setpoints_cb)
        self.create_service(LoadSetpoints, '/load_setpoints', self.load_setpoints_cb)
        self.create_service(ListProcesses, '/list_processes', self.list_processes_cb)
        self.create_service(LoadProcess, '/load_process', self.load_process_cb)
        self.create_service(SaveProcess, '/save_process', self.save_process_cb)
        self.create_service(
            LoadKeepoutZones, '/load_keepout_zones', self.load_keepout_zones_cb)
        self.create_service(
            SaveKeepoutZones, '/save_keepout_zones', self.save_keepout_zones_cb)

        self.create_timer(1.0, self._republish_timer_cb)

        self.get_logger().info(
            f'Maps: {self._maps_root} | Setpoint/process: {self._map_data_root}')
        self.get_logger().info(
            'Services: /save_map, /list_maps, /save_setpoints, /load_setpoints,'
        )
        self.get_logger().info(
            '          /list_processes, /load_process, /save_process,'
            ' /load_keepout_zones, /save_keepout_zones'
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
        keepout_dir = os.path.join(root, 'keepout')
        os.makedirs(setpoint_dir, exist_ok=True)
        os.makedirs(process_dir, exist_ok=True)
        os.makedirs(keepout_dir, exist_ok=True)

        setpoints_path = os.path.join(setpoint_dir, SETPOINTS_FILE)
        if not os.path.isfile(setpoints_path):
            payload = {
                'mapName': name,
                'updatedAt': _now_iso(),
                'setpoints': [],
            }
            with open(setpoints_path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

        keepout_path = os.path.join(keepout_dir, KEEPOUT_FILE)
        if not os.path.isfile(keepout_path):
            payload = {
                'mapName': name,
                'updatedAt': _now_iso(),
                'zones': [],
            }
            with open(keepout_path, 'w', encoding='utf-8') as fh:
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

    def _keepout_path(self, map_name: str) -> str:
        return os.path.join(self._data_dir(map_name), 'keepout', KEEPOUT_FILE)

    def _normalize_keepout_zones(self, raw) -> list:
        if isinstance(raw, dict):
            raw = raw.get('zones', [])
        if not isinstance(raw, list):
            raise ValueError('json_data phải là mảng vùng cấm')
        if len(raw) > 100:
            raise ValueError('Tối đa 100 vùng cấm cho mỗi map')

        zones = []
        for index, zone in enumerate(raw):
            if not isinstance(zone, dict):
                raise ValueError(f'Vùng cấm #{index + 1} không hợp lệ')
            raw_points = zone.get('points', [])
            if not isinstance(raw_points, list) or not 3 <= len(raw_points) <= 200:
                raise ValueError(
                    f'Vùng cấm #{index + 1} phải có từ 3 đến 200 điểm')
            points = []
            for point in raw_points:
                if not isinstance(point, dict):
                    raise ValueError(f'Điểm vùng cấm #{index + 1} không hợp lệ')
                x = float(point.get('x'))
                y = float(point.get('y'))
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError(f'Tọa độ vùng cấm #{index + 1} không hợp lệ')
                points.append({'x': x, 'y': y})
            zones.append({
                'id': str(zone.get('id') or f'keepout_{index + 1}'),
                'name': str(zone.get('name') or f'Vùng cấm {index + 1}'),
                'enabled': bool(zone.get('enabled', True)),
                'points': points,
            })
        return zones

    def _read_keepout_zones(self, map_name: str) -> list:
        if not map_name:
            return []
        path = self._keepout_path(map_name)
        if not os.path.isfile(path):
            return []
        with open(path, 'r', encoding='utf-8') as fh:
            return self._normalize_keepout_zones(json.load(fh))

    @staticmethod
    def _origin_yaw(origin) -> float:
        q = origin.orientation
        return math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )

    def _world_polygon_to_grid(self, points, info) -> list:
        yaw = self._origin_yaw(info.origin)
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        ox = info.origin.position.x
        oy = info.origin.position.y
        resolution = float(info.resolution)
        result = []
        for point in points:
            dx = point['x'] - ox
            dy = point['y'] - oy
            result.append((
                (cos_yaw * dx + sin_yaw * dy) / resolution,
                (-sin_yaw * dx + cos_yaw * dy) / resolution,
            ))
        return result

    @staticmethod
    def _fill_polygon(mask_data, width: int, height: int, polygon) -> int:
        if len(polygon) < 3:
            return 0
        min_row = max(0, int(math.floor(min(point[1] for point in polygon))))
        max_row = min(height - 1, int(math.ceil(max(point[1] for point in polygon))))
        filled = 0
        for row in range(min_row, max_row + 1):
            scan_y = row + 0.5
            intersections = []
            for index, first in enumerate(polygon):
                second = polygon[(index + 1) % len(polygon)]
                x1, y1 = first
                x2, y2 = second
                if (y1 <= scan_y < y2) or (y2 <= scan_y < y1):
                    intersections.append(
                        x1 + (scan_y - y1) * (x2 - x1) / (y2 - y1))
            intersections.sort()
            for index in range(0, len(intersections) - 1, 2):
                start = max(0, int(math.ceil(intersections[index] - 0.5)))
                end = min(
                    width - 1,
                    int(math.floor(intersections[index + 1] - 0.5)),
                )
                for col in range(start, end + 1):
                    offset = row * width + col
                    if mask_data[offset] != 100:
                        mask_data[offset] = 100
                        filled += 1
        return filled

    def _publish_keepout(self, zones=None) -> bool:
        if self._latest_map is None:
            return False
        map_name = self._active_map()
        if zones is None:
            zones = self._read_keepout_zones(map_name)

        source = self._latest_map
        mask = OccupancyGrid()
        mask.header = deepcopy(source.header)
        mask.header.stamp = self.get_clock().now().to_msg()
        mask.info = deepcopy(source.info)
        mask.info.map_load_time = mask.header.stamp
        mask.data = [0] * (mask.info.width * mask.info.height)

        filled = 0
        for zone in zones:
            if not zone.get('enabled', True):
                continue
            polygon = self._world_polygon_to_grid(zone['points'], mask.info)
            filled += self._fill_polygon(
                mask.data, mask.info.width, mask.info.height, polygon)

        info = CostmapFilterInfo()
        info.header.stamp = mask.header.stamp
        info.header.frame_id = mask.header.frame_id or 'map'
        info.type = 0
        info.filter_mask_topic = '/keepout_filter_mask'
        info.base = 0.0
        info.multiplier = 1.0

        zones_msg = String()
        zones_msg.data = json.dumps({
            'mapName': map_name,
            'zones': zones,
        }, ensure_ascii=False)

        self._keepout_mask_pub.publish(mask)
        self._keepout_info_pub.publish(info)
        self._keepout_zones_pub.publish(zones_msg)
        self.get_logger().info(
            f'Keepout mask: {len(zones)} vùng, {filled} ô lethal'
            f' ({mask.info.width}x{mask.info.height})')
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
        self._publish_keepout()

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
            self._publish_cached_map()
            self._publish_keepout()
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

    def load_keepout_zones_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            zones = self._read_keepout_zones(map_name)
            response.success = True
            response.json_data = json.dumps(zones, ensure_ascii=False)
            response.message = f'Đã tải {len(zones)} vùng cấm'
        except Exception as exc:
            response.success = False
            response.json_data = '[]'
            response.message = str(exc)
        return response

    def save_keepout_zones_cb(self, request, response):
        try:
            map_name = self._resolve_map_name(request.map_name)
            if len(request.json_data or '') > 2_000_000:
                raise ValueError('Dữ liệu vùng cấm vượt quá 2 MB')
            zones = self._normalize_keepout_zones(
                json.loads(request.json_data or '[]'))
            self._ensure_data_layout(map_name)
            payload = {
                'mapName': map_name,
                'updatedAt': _now_iso(),
                'zones': zones,
            }
            path = self._keepout_path(map_name)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

            if map_name == self._active_map():
                self._publish_keepout(zones)
            response.success = True
            response.message = f'Đã lưu {len(zones)} vùng cấm → {path}'
            self._notify_data('keepout')
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
