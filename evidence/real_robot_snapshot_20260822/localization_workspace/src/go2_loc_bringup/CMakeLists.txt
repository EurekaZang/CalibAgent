cmake_minimum_required(VERSION 3.8)
project(go2_loc_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch maps
  DESTINATION share/${PROJECT_NAME} OPTIONAL)

install(PROGRAMS scripts/loc_health_monitor.py
  DESTINATION lib/${PROJECT_NAME} RENAME loc_health_monitor)

ament_package()
