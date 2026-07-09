cmake_minimum_required(VERSION 3.8)
project(amr_mission_supervisor)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/SubmitMission.srv"
  DEPENDENCIES geometry_msgs
)

ament_python_install_package(amr_mission_supervisor_py)

install(PROGRAMS
  scripts/mission_supervisor
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
