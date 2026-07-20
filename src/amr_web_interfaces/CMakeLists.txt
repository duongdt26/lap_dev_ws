cmake_minimum_required(VERSION 3.8)
project(amr_web_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/SaveMap.srv"
  "srv/SendNavGoal.srv"
  "srv/GetMapStatus.srv"
  "srv/SetActiveMap.srv"
  "srv/SaveSetpoints.srv"
  "srv/LoadSetpoints.srv"
  "srv/SaveKeepoutZones.srv"
  "srv/LoadKeepoutZones.srv"
  "srv/ListProcesses.srv"
  "srv/LoadProcess.srv"
  "srv/SaveProcess.srv"
  DEPENDENCIES builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
