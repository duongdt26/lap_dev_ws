cmake_minimum_required(VERSION 3.8)
project(amr_docking_server)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(action_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/Dock.action"
  DEPENDENCIES action_msgs geometry_msgs
)

ament_python_install_package(amr_docking_server_py)

install(PROGRAMS
  scripts/docking_server
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
