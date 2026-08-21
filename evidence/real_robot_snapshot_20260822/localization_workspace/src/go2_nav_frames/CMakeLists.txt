cmake_minimum_required(VERSION 3.8)
project(go2_nav_frames)

set(CMAKE_CXX_STANDARD 14)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

add_executable(nav_tf_manager src/nav_tf_manager.cpp)
ament_target_dependencies(nav_tf_manager
  rclcpp nav_msgs geometry_msgs tf2 tf2_ros tf2_geometry_msgs)

install(TARGETS nav_tf_manager DESTINATION lib/${PROJECT_NAME})

ament_package()
