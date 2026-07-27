#!/usr/bin/env python3
"""
plot_experiment.py

Đọc file CSV thực nghiệm AMR và tự động vẽ các đồ thị:
1. Tốc độ đặt/thực hai bánh
2. Vận tốc tuyến tính đặt/thực
3. Vận tốc góc đặt/thực + IMU angular_z
4. Pose odometry và pose map
5. Góc yaw
6. Quỹ đạo XY + global path
7. Tuổi dữ liệu các nguồn
8. Trạng thái Nav2 theo thời gian

Không yêu cầu pandas; chỉ dùng Python standard library + matplotlib.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt


# ---------------------------------------------------------------------
# Tên cột tương thích. Script sẽ tự tìm cột đầu tiên có trong CSV.
# Có thể bổ sung alias tại đây nếu file thực tế dùng tên khác.
# ---------------------------------------------------------------------
ALIASES: Dict[str, Sequence[str]] = {
    "time": ("time_sec", "elapsed_time_sec", "relative_time_sec"),
    "ros_time": ("timestamp_ros", "ros_time_sec", "stamp_sec"),

    "left_set": (
        "left_wheel_setpoint", "left_setpoint", "wheel_left_set",
        "left_target", "left_cmd"
    ),
    "left_actual": (
        "left_wheel_actual", "left_actual", "wheel_left_actual",
        "left_hall_speed", "left_encoder_speed"
    ),
    "right_set": (
        "right_wheel_setpoint", "right_setpoint", "wheel_right_set",
        "right_target", "right_cmd"
    ),
    "right_actual": (
        "right_wheel_actual", "right_actual", "wheel_right_actual",
        "right_hall_speed", "right_encoder_speed"
    ),

    "cmd_linear": ("cmd_linear_x", "linear_cmd", "cmd_v"),
    "actual_linear": (
        "actual_linear_x", "odom_linear_x", "linear_actual", "odom_v"
    ),
    "cmd_angular": ("cmd_angular_z", "angular_cmd", "cmd_omega"),
    "actual_angular": (
        "actual_angular_z", "odom_angular_z", "angular_actual", "odom_omega"
    ),

    "odom_x": ("odom_x",),
    "odom_y": ("odom_y",),
    "odom_yaw": ("odom_yaw",),

    "map_x": ("map_x", "tf_map_x"),
    "map_y": ("map_y", "tf_map_y"),
    "map_yaw": ("map_yaw", "tf_map_yaw"),

    "imu_yaw": ("imu_yaw",),
    "imu_angular_z": ("imu_angular_z", "imu_gyro_z"),

    "goal_x": ("goal_x",),
    "goal_y": ("goal_y",),
    "goal_yaw": ("goal_yaw",),

    "nav_status": ("nav_status", "navigation_status"),

    "wheel_age": ("wheel_data_age_sec", "wheel_age_sec"),
    "cmd_age": ("cmd_vel_age_sec", "cmd_age_sec"),
    "odom_age": ("odom_age_sec",),
    "imu_age": ("imu_age_sec",),
    "map_age": ("map_pose_age_sec", "map_age_sec"),
    "goal_age": ("goal_age_sec",),
    "nav_age": ("nav_status_age_sec", "nav_age_sec"),

    "note": ("note", "run_note"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vẽ đồ thị từ CSV thực nghiệm AMR."
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="File CSV chính, ví dụ experiment_data/navigation_20260727_153020.csv",
    )
    parser.add_argument(
        "--global-path",
        type=Path,
        default=None,
        help="File global path CSV. Nếu bỏ trống, script tự tìm file *_global_path.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Thư mục lưu hình. Mặc định: <tên_csv>_plots",
    )
    parser.add_argument(
        "--wheel-unit",
        default="rad/s",
        help="Đơn vị tốc độ bánh, mặc định rad/s.",
    )
    parser.add_argument(
        "--angle-unit",
        choices=("rad", "deg"),
        default="rad",
        help="Đơn vị hiển thị góc yaw. Mặc định rad.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Độ phân giải PNG, mặc định 300 dpi.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Hiện cửa sổ đồ thị sau khi lưu.",
    )
    return parser.parse_args()


def to_float(value: object) -> float:
    if value is None:
        return math.nan
    text = str(value).strip()
    if not text:
        return math.nan
    try:
        result = float(text)
        return result if math.isfinite(result) else math.nan
    except (TypeError, ValueError):
        return math.nan


def read_csv_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError(f"CSV không có header: {path}")
        rows = list(reader)
        return list(reader.fieldnames), rows


def find_column(headers: Iterable[str], logical_name: str) -> Optional[str]:
    header_set = set(headers)
    for candidate in ALIASES.get(logical_name, (logical_name,)):
        if candidate in header_set:
            return candidate
    return None


def numeric_series(
    rows: Sequence[Dict[str, str]],
    headers: Sequence[str],
    logical_name: str,
) -> Optional[List[float]]:
    column = find_column(headers, logical_name)
    if column is None:
        return None
    return [to_float(row.get(column)) for row in rows]


def text_series(
    rows: Sequence[Dict[str, str]],
    headers: Sequence[str],
    logical_name: str,
) -> Optional[List[str]]:
    column = find_column(headers, logical_name)
    if column is None:
        return None
    return [str(row.get(column, "")).strip() for row in rows]


def has_finite(values: Optional[Sequence[float]]) -> bool:
    return values is not None and any(math.isfinite(v) for v in values)


def angle_convert(values: Optional[List[float]], unit: str) -> Optional[List[float]]:
    if values is None or unit == "rad":
        return values
    return [math.degrees(v) if math.isfinite(v) else math.nan for v in values]


def finite_xy(
    x_values: Optional[Sequence[float]],
    y_values: Optional[Sequence[float]],
) -> Tuple[List[float], List[float]]:
    if x_values is None or y_values is None:
        return [], []
    xs: List[float] = []
    ys: List[float] = []
    for x, y in zip(x_values, y_values):
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
    return xs, ys


def save_figure(fig: plt.Figure, output: Path, dpi: int, show: bool) -> None:
    fig.tight_layout()
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)


def make_line_plot(
    time_values: Sequence[float],
    series: Sequence[Tuple[Sequence[float], str]],
    title: str,
    ylabel: str,
    output: Path,
    dpi: int,
    show: bool,
) -> bool:
    usable = [(values, label) for values, label in series if has_finite(values)]
    if not usable:
        return False

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for values, label in usable:
        ax.plot(time_values, values, label=label, linewidth=1.3)

    ax.set_title(title)
    ax.set_xlabel("Thời gian từ lúc bắt đầu (s)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    ax.legend()
    save_figure(fig, output, dpi, show)
    return True


def read_global_paths(
    path: Optional[Path],
) -> Dict[str, List[Tuple[int, float, float, float]]]:
    paths: Dict[str, List[Tuple[int, float, float, float]]] = defaultdict(list)
    if path is None or not path.exists():
        return paths

    headers, rows = read_csv_rows(path)
    required = {"path_id", "point_index", "x", "y"}
    if not required.issubset(set(headers)):
        print(
            f"Cảnh báo: file global path thiếu cột {sorted(required - set(headers))}",
            file=sys.stderr,
        )
        return paths

    for row in rows:
        path_id = str(row.get("path_id", "0")).strip() or "0"
        point_index = int(to_float(row.get("point_index"))) if math.isfinite(
            to_float(row.get("point_index"))
        ) else 0
        x = to_float(row.get("x"))
        y = to_float(row.get("y"))
        yaw = to_float(row.get("yaw"))
        if math.isfinite(x) and math.isfinite(y):
            paths[path_id].append((point_index, x, y, yaw))

    for path_id in paths:
        paths[path_id].sort(key=lambda item: item[0])

    return paths


def plot_trajectory(
    odom_x: Optional[List[float]],
    odom_y: Optional[List[float]],
    map_x: Optional[List[float]],
    map_y: Optional[List[float]],
    goal_x: Optional[List[float]],
    goal_y: Optional[List[float]],
    global_paths: Dict[str, List[Tuple[int, float, float, float]]],
    output: Path,
    dpi: int,
    show: bool,
) -> bool:
    odom_xs, odom_ys = finite_xy(odom_x, odom_y)
    map_xs, map_ys = finite_xy(map_x, map_y)

    if not odom_xs and not map_xs and not global_paths:
        return False

    fig, ax = plt.subplots(figsize=(8, 7))

    if odom_xs:
        ax.plot(odom_xs, odom_ys, label="Quỹ đạo odometry", linewidth=1.3)

    if map_xs:
        ax.plot(map_xs, map_ys, label="Quỹ đạo thực tế trong map", linewidth=1.5)

    for path_id, points in sorted(global_paths.items(), key=lambda item: item[0]):
        xs = [p[1] for p in points]
        ys = [p[2] for p in points]
        if xs:
            ax.plot(
                xs,
                ys,
                linestyle="--",
                linewidth=1.1,
                label=f"Global path {path_id}",
            )

    reference_x = map_xs if map_xs else odom_xs
    reference_y = map_ys if map_ys else odom_ys

    if reference_x:
        ax.scatter([reference_x[0]], [reference_y[0]], marker="o", s=60, label="Bắt đầu")
        ax.scatter([reference_x[-1]], [reference_y[-1]], marker="x", s=70, label="Kết thúc")

    if goal_x is not None and goal_y is not None:
        gx, gy = finite_xy(goal_x, goal_y)
        if gx:
            ax.scatter([gx[-1]], [gy[-1]], marker="*", s=120, label="Goal")

    ax.set_title("Quỹ đạo robot và Global Path")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.axis("equal")
    ax.grid(True, alpha=0.35)
    ax.legend()
    save_figure(fig, output, dpi, show)
    return True


def plot_nav_status(
    time_values: Sequence[float],
    statuses: Optional[List[str]],
    output: Path,
    dpi: int,
    show: bool,
) -> bool:
    if statuses is None or not any(statuses):
        return False

    unique: List[str] = []
    for status in statuses:
        if status and status not in unique:
            unique.append(status)

    mapping = {status: index for index, status in enumerate(unique)}
    y_values = [mapping.get(status, math.nan) if status else math.nan for status in statuses]

    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.step(time_values, y_values, where="post", linewidth=1.3)
    ax.set_title("Trạng thái Nav2 theo thời gian")
    ax.set_xlabel("Thời gian từ lúc bắt đầu (s)")
    ax.set_ylabel("Trạng thái")
    ax.set_yticks(list(mapping.values()))
    ax.set_yticklabels(list(mapping.keys()))
    ax.grid(True, alpha=0.35)
    save_figure(fig, output, dpi, show)
    return True


def main() -> int:
    args = parse_args()
    csv_path: Path = args.csv_file.resolve()

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else csv_path.with_name(f"{csv_path.stem}_plots")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    global_path_file: Optional[Path]
    if args.global_path is not None:
        global_path_file = args.global_path.resolve()
    else:
        candidate = csv_path.with_name(f"{csv_path.stem}_global_path.csv")
        global_path_file = candidate if candidate.exists() else None

    headers, rows = read_csv_rows(csv_path)
    if not rows:
        raise ValueError("CSV không có dòng dữ liệu.")

    time_values = numeric_series(rows, headers, "time")
    if not has_finite(time_values):
        raise ValueError(
            "Không tìm thấy cột thời gian hợp lệ. Cần có time_sec hoặc alias tương đương."
        )
    assert time_values is not None

    # Thay NaN thời gian bằng chỉ số mẫu để tránh lỗi vẽ hiếm gặp.
    clean_time: List[float] = []
    last_value = 0.0
    for index, value in enumerate(time_values):
        if math.isfinite(value):
            last_value = value
        else:
            last_value = last_value if index > 0 else 0.0
        clean_time.append(last_value)

    left_set = numeric_series(rows, headers, "left_set")
    left_actual = numeric_series(rows, headers, "left_actual")
    right_set = numeric_series(rows, headers, "right_set")
    right_actual = numeric_series(rows, headers, "right_actual")

    cmd_linear = numeric_series(rows, headers, "cmd_linear")
    actual_linear = numeric_series(rows, headers, "actual_linear")
    cmd_angular = numeric_series(rows, headers, "cmd_angular")
    actual_angular = numeric_series(rows, headers, "actual_angular")
    imu_angular_z = numeric_series(rows, headers, "imu_angular_z")

    odom_x = numeric_series(rows, headers, "odom_x")
    odom_y = numeric_series(rows, headers, "odom_y")
    odom_yaw = angle_convert(numeric_series(rows, headers, "odom_yaw"), args.angle_unit)

    map_x = numeric_series(rows, headers, "map_x")
    map_y = numeric_series(rows, headers, "map_y")
    map_yaw = angle_convert(numeric_series(rows, headers, "map_yaw"), args.angle_unit)

    imu_yaw = angle_convert(numeric_series(rows, headers, "imu_yaw"), args.angle_unit)

    goal_x = numeric_series(rows, headers, "goal_x")
    goal_y = numeric_series(rows, headers, "goal_y")
    nav_status = text_series(rows, headers, "nav_status")

    created: List[Path] = []
    skipped: List[str] = []

    def create_line(
        filename: str,
        series: Sequence[Tuple[Optional[List[float]], str]],
        title: str,
        ylabel: str,
    ) -> None:
        filtered = [(values, label) for values, label in series if values is not None]
        output = output_dir / filename
        if make_line_plot(
            clean_time,
            filtered,
            title,
            ylabel,
            output,
            args.dpi,
            args.show,
        ):
            created.append(output)
        else:
            skipped.append(filename)

    create_line(
        "01_wheel_velocity.png",
        [
            (left_set, "Setpoint bánh trái"),
            (left_actual, "Hall bánh trái"),
            (right_set, "Setpoint bánh phải"),
            (right_actual, "Hall bánh phải"),
        ],
        "Tốc độ đặt và tốc độ thực của hai bánh",
        f"Tốc độ bánh ({args.wheel_unit})",
    )

    create_line(
        "02_left_wheel_velocity.png",
        [
            (left_set, "Setpoint bánh trái"),
            (left_actual, "Hall bánh trái"),
        ],
        "Đáp ứng tốc độ bánh trái",
        f"Tốc độ bánh ({args.wheel_unit})",
    )

    create_line(
        "03_right_wheel_velocity.png",
        [
            (right_set, "Setpoint bánh phải"),
            (right_actual, "Hall bánh phải"),
        ],
        "Đáp ứng tốc độ bánh phải",
        f"Tốc độ bánh ({args.wheel_unit})",
    )

    create_line(
        "04_robot_linear_velocity.png",
        [
            (cmd_linear, "Vận tốc tuyến tính đặt"),
            (actual_linear, "Vận tốc tuyến tính thực"),
        ],
        "Vận tốc tuyến tính đặt và thực của robot",
        "Vận tốc tuyến tính (m/s)",
    )

    create_line(
        "05_robot_angular_velocity.png",
        [
            (cmd_angular, "Vận tốc góc đặt"),
            (actual_angular, "Vận tốc góc thực"),
            (imu_angular_z, "IMU angular z"),
        ],
        "Vận tốc góc đặt và thực của robot",
        "Vận tốc góc (rad/s)",
    )

    create_line(
        "06_pose_x.png",
        [
            (odom_x, "Odom X"),
            (map_x, "Map X"),
            (goal_x, "Goal X"),
        ],
        "So sánh vị trí X",
        "X (m)",
    )

    create_line(
        "07_pose_y.png",
        [
            (odom_y, "Odom Y"),
            (map_y, "Map Y"),
            (goal_y, "Goal Y"),
        ],
        "So sánh vị trí Y",
        "Y (m)",
    )

    angle_label = "Góc (rad)" if args.angle_unit == "rad" else "Góc (độ)"
    create_line(
        "08_yaw.png",
        [
            (odom_yaw, "Odom yaw"),
            (map_yaw, "Map yaw"),
            (imu_yaw, "IMU yaw"),
        ],
        "So sánh góc yaw",
        angle_label,
    )

    global_paths = read_global_paths(global_path_file)
    trajectory_output = output_dir / "09_trajectory_xy.png"
    if plot_trajectory(
        odom_x,
        odom_y,
        map_x,
        map_y,
        goal_x,
        goal_y,
        global_paths,
        trajectory_output,
        args.dpi,
        args.show,
    ):
        created.append(trajectory_output)
    else:
        skipped.append(trajectory_output.name)

    age_series = [
        (numeric_series(rows, headers, "wheel_age"), "Dữ liệu bánh"),
        (numeric_series(rows, headers, "cmd_age"), "cmd_vel"),
        (numeric_series(rows, headers, "odom_age"), "Odometry"),
        (numeric_series(rows, headers, "imu_age"), "IMU"),
        (numeric_series(rows, headers, "map_age"), "Map TF"),
        (numeric_series(rows, headers, "goal_age"), "Goal"),
        (numeric_series(rows, headers, "nav_age"), "Nav status"),
    ]
    create_line(
        "10_data_age.png",
        age_series,
        "Tuổi dữ liệu của từng nguồn",
        "Tuổi dữ liệu (s)",
    )

    nav_output = output_dir / "11_nav_status.png"
    if plot_nav_status(clean_time, nav_status, nav_output, args.dpi, args.show):
        created.append(nav_output)
    else:
        skipped.append(nav_output.name)

    note_column = find_column(headers, "note")
    note = ""
    if note_column is not None:
        for row in rows:
            candidate = str(row.get(note_column, "")).strip()
            if candidate:
                note = candidate
                break

    summary_path = output_dir / "plot_summary.txt"
    with summary_path.open("w", encoding="utf-8") as file:
        file.write(f"CSV chính: {csv_path}\n")
        file.write(f"Global path: {global_path_file or 'Không có'}\n")
        file.write(f"Số dòng: {len(rows)}\n")
        file.write(f"Thời lượng: {clean_time[-1] - clean_time[0]:.3f} s\n")
        file.write(f"Ghi chú: {note or 'Không có'}\n\n")
        file.write("Đồ thị đã tạo:\n")
        for item in created:
            file.write(f"- {item.name}\n")
        file.write("\nĐồ thị bỏ qua do thiếu dữ liệu:\n")
        for item in skipped:
            file.write(f"- {item}\n")

    print("Đã hoàn tất vẽ đồ thị.")
    print(f"CSV chính: {csv_path}")
    print(f"Global path: {global_path_file or 'Không tìm thấy'}")
    print(f"Thư mục hình: {output_dir}")
    print(f"Số hình đã tạo: {len(created)}")
    if skipped:
        print(f"Số hình bỏ qua do thiếu dữ liệu: {len(skipped)}")
    print(f"Tóm tắt: {summary_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        raise SystemExit(1)
