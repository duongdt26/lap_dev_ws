cmake_minimum_required(VERSION 3.8)
project(amr_stm32_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(action_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/BeltLoadUnload.action"
  "msg/ConveyorStatus.msg"
  "msg/Stm32Health.msg"
  "srv/Stm32Hello.srv"
  "srv/ResetEstop.srv"
  "srv/RunBeltCommand.srv"
  DEPENDENCIES builtin_interfaces action_msgs std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
