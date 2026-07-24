#!/usr/bin/env python3
import json

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from std_msgs.msg import String


class MissionClientNode(Node):
    """Keep web mission/docking contracts while the backend is rebuilt."""

    def __init__(self):
        super().__init__('mission_client_node')
        self.response_pub = self.create_publisher(String, '/web_mission_response', 10)
        self.dock_response_pub = self.create_publisher(String, '/web_dock_response', 10)
        self.mission_status_pub = self.create_publisher(String, '/mission/status', 10)
        self.costmap_response_pub = self.create_publisher(String, '/web_costmap_response', 10)
        self.create_subscription(String, '/web_mission_request', self._mission_cb, 10)
        self.create_subscription(String, '/web_cargo_done', self._cargo_done_cb, 10)
        self.create_subscription(String, '/web_dock_request', self._dock_cb, 10)
        self.create_subscription(String, '/web_costmap_request', self._costmap_cb, 10)
        self.costmap_clients = {}
        self.costmap_restore_values = {}
        self.get_logger().info(
            'Web mission/docking contracts ready; docking backend is unavailable')

    def _publish_response(self, status: str, detail: str):
        msg = String()
        msg.data = json.dumps({'status': status, 'detail': detail}, ensure_ascii=False)
        self.response_pub.publish(msg)
        self.get_logger().info(msg.data)

    def _publish_dock_response(self, task_id: str, mode: str, status: str, detail: str, **extra):
        msg = String()
        payload = {
            'task_id': task_id,
            'mode': mode,
            'status': status,
            'detail': detail,
        }
        payload.update(extra)
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.dock_response_pub.publish(msg)
        self.get_logger().info(msg.data)

    def _publish_costmap_response(
            self, request_id: str, mode: str, status: str, detail: str, **extra):
        msg = String()
        payload = {
            'request_id': request_id,
            'mode': mode,
            'status': status,
            'detail': detail,
        }
        payload.update(extra)
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.costmap_response_pub.publish(msg)
        self.get_logger().info(msg.data)

    def _mission_cb(self, msg: String):
        try:
            data = json.loads(msg.data)
            task_id = str(data.get('task_id', ''))
            station_id = str(data['station_id'])
        except Exception as exc:
            self._publish_response('error', f'invalid mission JSON: {exc}')
            return

        detail = (
            'Docking backend is not implemented '
            f'(task_id={task_id}, station_id={station_id})'
        )
        self._publish_response('unavailable', detail)
        status = String()
        status.data = f'FAILED|{detail}'
        self.mission_status_pub.publish(status)

    def _cargo_done_cb(self, msg: String):
        mode = msg.data.strip().upper()
        self._publish_response(
            'unavailable',
            f'Docking backend is not implemented (cargo_mode={mode or "UNKNOWN"})',
        )

    def _dock_cb(self, msg: String):
        try:
            data = json.loads(msg.data)
            task_id = str(data.get('task_id', ''))
            mode = str(data.get('mode', 'DOCK_IN')).upper()
        except Exception as exc:
            self._publish_dock_response('', '', 'error', f'invalid dock JSON: {exc}')
            return

        self._publish_dock_response(
            task_id,
            mode,
            'unavailable',
            'Docking backend is not implemented',
            success=False,
        )

    def _costmap_param_clients(self, node_name: str):
        if node_name not in self.costmap_clients:
            prefix = node_name.rstrip('/')
            self.costmap_clients[node_name] = (
                self.create_client(GetParameters, f'{prefix}/get_parameters'),
                self.create_client(SetParameters, f'{prefix}/set_parameters'),
            )
        return self.costmap_clients[node_name]

    def _costmap_cb(self, msg: String):
        try:
            data = json.loads(msg.data)
            request_id = str(data.get('request_id', ''))
            mode = str(data.get('mode', 'dock')).lower()
            radius = float(data.get('radius', 0.35))
            nodes = data.get('nodes') or [
                '/local_costmap/local_costmap',
                '/global_costmap/global_costmap',
            ]
            params = data.get('parameters') or ['inflation_layer.inflation_radius']
        except Exception as exc:
            self._publish_costmap_response('', '', 'error', f'invalid costmap JSON: {exc}')
            return

        if mode in ('dock', 'set'):
            values = {name: radius for name in params}
            self._set_costmap_group(request_id, mode, nodes, values, save_restore=(mode == 'dock'))
        elif mode == 'restore':
            self._restore_costmap_group(request_id, mode, nodes)
        else:
            self._publish_costmap_response(
                request_id, mode, 'error', f'unknown costmap mode: {mode}')

    def _set_costmap_group(self, request_id: str, mode: str, nodes, values, save_restore: bool):
        pending = {'count': len(nodes), 'errors': []}
        if pending['count'] == 0:
            self._publish_costmap_response(
                request_id, mode, 'succeeded', 'no costmap nodes requested')
            return

        def finish_one(error=None):
            if error:
                pending['errors'].append(str(error))
            pending['count'] -= 1
            if pending['count'] > 0:
                return
            if pending['errors']:
                self._publish_costmap_response(
                    request_id, mode, 'error', '; '.join(pending['errors']))
            else:
                self._publish_costmap_response(
                    request_id, mode, 'succeeded', f'costmap {mode}: {values}')

        for node_name in nodes:
            self._set_costmap_node(node_name, values, save_restore, finish_one)

    def _set_costmap_node(self, node_name: str, values, save_restore: bool, done_cb):
        get_cli, set_cli = self._costmap_param_clients(node_name)
        if not set_cli.wait_for_service(timeout_sec=0.2):
            done_cb(f'{node_name}/set_parameters not ready')
            return

        def call_set():
            req = SetParameters.Request()
            for name, value in values.items():
                param = Parameter()
                param.name = name
                param.value = ParameterValue(
                    type=ParameterType.PARAMETER_DOUBLE,
                    double_value=float(value),
                )
                req.parameters.append(param)
            future = set_cli.call_async(req)
            future.add_done_callback(lambda f: self._costmap_set_done(node_name, f, done_cb))

        if not save_restore:
            call_set()
            return

        if not get_cli.wait_for_service(timeout_sec=0.2):
            done_cb(f'{node_name}/get_parameters not ready')
            return

        req = GetParameters.Request()
        req.names = list(values.keys())
        future = get_cli.call_async(req)

        def on_get(f):
            try:
                res = f.result()
                restore = {}
                for name, value in zip(req.names, res.values):
                    if value.type == ParameterType.PARAMETER_DOUBLE:
                        restore[name] = float(value.double_value)
                if restore:
                    self.costmap_restore_values[node_name] = restore
            except Exception as exc:
                done_cb(f'{node_name}/get_parameters failed: {exc}')
                return
            call_set()

        future.add_done_callback(on_get)

    def _costmap_set_done(self, node_name: str, future, done_cb):
        try:
            res = future.result()
            for result in res.results:
                if not result.successful:
                    done_cb(f'{node_name} rejected parameter: {result.reason}')
                    return
        except Exception as exc:
            done_cb(f'{node_name}/set_parameters failed: {exc}')
            return
        done_cb()

    def _restore_costmap_group(self, request_id: str, mode: str, nodes):
        values_by_node = {
            node: self.costmap_restore_values[node]
            for node in nodes
            if node in self.costmap_restore_values
        }
        pending = {'count': len(values_by_node), 'errors': []}
        if pending['count'] == 0:
            self._publish_costmap_response(
                request_id, mode, 'succeeded',
                'no saved costmap values to restore')
            return

        def finish_one(error=None):
            if error:
                pending['errors'].append(str(error))
            pending['count'] -= 1
            if pending['count'] > 0:
                return
            if pending['errors']:
                self._publish_costmap_response(
                    request_id, mode, 'error', '; '.join(pending['errors']))
            else:
                self._publish_costmap_response(request_id, mode, 'succeeded', 'costmap restored')

        for node_name, values in values_by_node.items():
            self._set_costmap_node(node_name, values, save_restore=False, done_cb=finish_one)


def main():
    rclpy.init()
    node = MissionClientNode()
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
