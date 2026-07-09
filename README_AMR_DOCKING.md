# AMR Nav2 Docking Workflow

## Build

```bash
cd /home/duo/dev_ws
colcon build --symlink-install --packages-select amr_docking_server amr_mission_supervisor amr_web_bridge amr_lan_3
source install/setup.bash
```

## Launch

Robot launch now includes `twist_mux`, web bridge, docking server, and mission supervisor:

```bash
ros2 launch amr_lan_3 launch_robot.launch.py
```

Run nodes separately when debugging:

```bash
ros2 launch amr_docking_server docking_server.launch.py
ros2 launch amr_mission_supervisor mission_supervisor.launch.py
ros2 run amr_web_bridge mission_client_node
```

## Mission Flow

1. Web publishes a mission to `/web_mission_request`.
2. `mission_client_node` calls `/mission/submit`.
3. `mission_supervisor` sends Nav2 to station `pre_dock_pose_A`.
4. Nav2 publishes through `cmd_vel_nav_raw -> velocity_smoother -> cmd_vel_nav`.
5. `twist_mux` forwards `cmd_vel_nav` until docking starts.
6. Supervisor calls `/dock` with `DOCK_IN`.
7. Docking server publishes `/cmd_vel_dock`.
8. Supervisor waits for `/mission/pick_done` or `/mission/drop_done`.
9. Supervisor calls `/dock` with `UNDOCK_OUT`.
10. Supervisor sends Nav2 to `next_goal` if provided.

## Test From Web/Rosbridge

Example JSON for `/web_mission_request`:

```json
{
  "task_id": "T001",
  "station_id": "S01",
  "cargo_mode": "PICK",
  "has_next_goal": true,
  "next_goal": {
    "frame_id": "map",
    "x": 1.0,
    "y": 0.5,
    "yaw": 0.0
  }
}
```

Publish without the web UI:

```bash
ros2 topic pub --once /web_mission_request std_msgs/msg/String \
  "{data: '{\"task_id\":\"T001\",\"station_id\":\"S01\",\"cargo_mode\":\"PICK\",\"has_next_goal\":false}'}"
```

Signal cargo done:

```bash
ros2 service call /mission/pick_done std_srvs/srv/Trigger {}
ros2 topic pub --once /web_cargo_done std_msgs/msg/String "{data: PICK}"
```

If rosbridge is running on port `9090`, a curl-style websocket client can publish the same JSON to `/web_mission_request`; plain HTTP curl is not enough for rosbridge websockets.

## Test Supervisor Service

```bash
ros2 service call /mission/submit amr_mission_supervisor/srv/SubmitMission \
"{task_id: T001, station_id: S01, cargo_mode: PICK, has_next_goal: false}"
```

## Test Docking Action Directly

Only run this when the robot is already near station A and Nav2 is not commanding the base.

```bash
ros2 action send_goal /dock amr_docking_server/action/Dock \
"{task_id: T001, station_id: S01, mode: DOCK_IN, max_speed: 0.06}" --feedback

ros2 action send_goal /dock amr_docking_server/action/Dock \
"{task_id: T001, station_id: S01, mode: UNDOCK_OUT, max_speed: 0.06}" --feedback
```

## Debug Topics

```bash
ros2 topic echo /mission/status
ros2 topic echo /web_mission_response
ros2 topic echo /cmd_vel_nav_raw
ros2 topic echo /cmd_vel_nav
ros2 topic echo /cmd_vel_dock
ros2 topic echo /cmd_vel
ros2 topic echo /diff_cont/cmd_vel_unstamped
ros2 topic echo /odometry/filtered
ros2 topic echo /scan_filtered
ros2 topic echo /emergency/bumper
```

## Important Config Files

- Station poses: `src/amr_docking_server/config/station_database.yaml`
- Mux ownership: `src/amr_lan_3/config/twist_mux.yaml`
- Mux deliverable alias: `src/amr_lan_3/config/cmd_vel_mux.yaml`
- Nav2 RPP sample: `src/amr_lan_3/config/nav2_rpp_controller.yaml`
- Active Nav2 params: `src/amr_lan_3/config/nav2_params.yaml`

## Safety Notes

- Docking aborts if robot is too far from A, TF/odom is missing, emergency is active, front obstacle is too close, yaw error exceeds 5 degrees in the corridor, lateral error grows too much, or timeout expires.
- Docking always publishes zero velocity on success, cancel, abort, and shutdown.
- `twist_mux` priorities are emergency lock, keyboard/manual, web, docking, then Nav2.
