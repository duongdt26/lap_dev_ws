import math

from amr_magnetic_line_follower.control import (
    HorizontalMarkerDetector,
    SensorData,
    active_point_span,
    choose_sweep_direction,
    compute_pose_errors,
    compute_home_reverse_wheel_command,
    compute_home_tracking_measurement,
    crc16_modbus,
    decode_active_point_mask,
    belt_command_at_marker,
    motor_rpms_to_twist,
    PDController,
    normalize_angle_rad,
    reached_sweep_limit,
)


def test_crc_from_sensor_manual_example():
    assert crc16_modbus(bytes.fromhex('01 04 03 E8 00 08')) == 0xBC71


def test_decode_all_point_layout_edges():
    reg_1014 = 0x0001
    reg_1015 = (1 << 1) | (1 << 7) | (1 << 8) | (1 << 15)
    mask = decode_active_point_mask(reg_1014, reg_1015)
    expected = (1 << 0) | (1 << 6) | (1 << 7) | (1 << 14) | (1 << 15)
    assert mask == expected
    assert active_point_span(mask) == 16


def test_horizontal_marker_raw_wide():
    detector = HorizontalMarkerDetector((83, 86))
    sensor = SensorData(
        83, True, True, active_mask=0x07FF,
        raw_active_points=11, active_span_points=11)
    detected, reason = detector.observe(sensor)
    assert detected
    assert 'raw-wide' in reason


def test_equal_motor_rpm_is_straight_twist():
    linear, angular = motor_rpms_to_twist(300, 300, 30.0, 0.09, 0.5703)
    assert linear > 0.0
    assert math.isclose(angular, 0.0, abs_tol=1e-12)


def test_original_search_rpm_is_rotation_only():
    linear, angular = motor_rpms_to_twist(130, -130, 30.0, 0.09, 0.5703)
    assert math.isclose(linear, 0.0, abs_tol=1e-12)
    assert angular < 0.0


def test_approach_load_load_runs_both_markers_then_final_stop():
    assert [belt_command_at_marker(i, 'load', 'load') for i in (1, 2, 3)] == [
        (1, 'load'), (2, 'load'), None]


def test_approach_load_unload_runs_correct_command_at_each_marker():
    assert [belt_command_at_marker(i, 'load', 'unload') for i in (1, 2, 3)] == [
        (1, 'load'), (2, 'unload'), None]


def test_approach_unload_load_runs_correct_command_at_each_marker():
    assert [belt_command_at_marker(i, 'unload', 'load') for i in (1, 2, 3)] == [
        (1, 'unload'), (2, 'load'), None]


def test_approach_unload_unload_runs_both_markers_then_final_stop():
    assert [belt_command_at_marker(i, 'unload', 'unload') for i in (1, 2, 3)] == [
        (1, 'unload'), (2, 'unload'), None]


def test_unload_only_belt1_skips_second_marker_command():
    assert [belt_command_at_marker(i, 'unload', 'none') for i in (1, 2, 3)] == [
        (1, 'unload'), None, None]


def test_unload_only_belt2_skips_first_marker_command():
    assert [belt_command_at_marker(i, 'none', 'unload') for i in (1, 2, 3)] == [
        None, (2, 'unload'), None]


def test_home_uses_rear_sensor_and_commands_reverse_motion():
    rear = SensorData(86, True, True, offset_mm=0.0)
    measurement = compute_home_tracking_measurement(rear)
    left, right, _ = compute_home_reverse_wheel_command(
        PDController(), measurement, 1.0)
    assert left < 0 and right < 0
    linear, _ = motor_rpms_to_twist(left, right, 30.0, 0.09, 0.5703)
    assert linear < 0.0


def test_home_rear_offset_steers_tail_toward_line():
    rear = SensorData(86, True, True, offset_mm=20.0)
    measurement = compute_home_tracking_measurement(rear)
    left, right, _ = compute_home_reverse_wheel_command(
        PDController(), measurement, 1.0)
    _, angular = motor_rpms_to_twist(left, right, 30.0, 0.09, 0.5703)
    assert angular < 0.0


def test_shortest_yaw_turn_315_to_0_is_left_45_degrees():
    error = normalize_angle_rad(math.radians(0.0 - 315.0))
    assert math.isclose(math.degrees(error), 45.0, abs_tol=1e-9)


def test_shortest_yaw_turn_45_to_0_is_right_45_degrees():
    error = normalize_angle_rad(math.radians(0.0 - 45.0))
    assert math.isclose(math.degrees(error), -45.0, abs_tol=1e-9)


def test_pose_lateral_error_and_sweep_side():
    errors = compute_pose_errors(
        target_x=1.0,
        target_y=2.0,
        target_yaw_rad=0.0,
        actual_x=1.0,
        actual_y=2.10,
        actual_yaw_rad=0.0,
    )
    assert math.isclose(errors.lateral_error_m, 0.10, abs_tol=1e-9)
    # Robot lech trai truc tram -> line o phai -> quet phai (-1).
    assert choose_sweep_direction(
        errors.yaw_error_rad,
        errors.lateral_error_m,
        math.radians(5.0),
        0.02,
    ) == -1


def test_lateral_error_selects_nearest_sweep_side_after_align():
    assert choose_sweep_direction(
        math.radians(30.0),
        lateral_error_m=0.10,
        yaw_deadband_rad=math.radians(5.0),
        lateral_deadband_m=0.02,
    ) == -1


def test_yaw_direction_is_fallback_when_lateral_error_is_small():
    assert choose_sweep_direction(
        math.radians(30.0),
        lateral_error_m=0.0,
        yaw_deadband_rad=math.radians(5.0),
        lateral_deadband_m=0.02,
    ) == +1


def test_sweep_stops_at_90_degree_boundaries():
    limit = math.radians(90.0)
    assert not reached_sweep_limit(math.radians(89.0), +1, limit)
    assert reached_sweep_limit(math.radians(90.0), +1, limit)
    assert not reached_sweep_limit(math.radians(-89.0), -1, limit)
    assert reached_sweep_limit(math.radians(-90.0), -1, limit)
