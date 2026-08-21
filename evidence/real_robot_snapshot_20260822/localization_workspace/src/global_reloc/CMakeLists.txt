cmake_minimum_required(VERSION 3.8)
project(global_reloc)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(pcl_conversions REQUIRED)
find_package(livox_ros_driver2 REQUIRED)
find_package(Eigen3 REQUIRED)
find_package(PCL REQUIRED COMPONENTS common io filters registration)
find_package(OpenMP)

# 官方 3d_bbs 库(源码+预编译 .so)位置
# 注: Jetson Orin(CUDA 11.4/sm_87) 上 gpu_bbs3d 内核评分异常, 实测 cpu_bbs3d 正常, 故用 CPU 版
# 路径解析优先级: 1) 环境变量 BBS3D_DIR  2) 本工作区 third_party/3d_bbs-main  3) /home/unitree/3d_bbs-main
if(DEFINED ENV{BBS3D_DIR})
  set(BBS3D_DIR "$ENV{BBS3D_DIR}")
elseif(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/3d_bbs-main/build/libcpu_bbs3d.so")
  get_filename_component(BBS3D_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/3d_bbs-main" ABSOLUTE)
else()
  set(BBS3D_DIR "/home/unitree/3d_bbs-main")
endif()
message(STATUS "global_reloc: using BBS3D_DIR=${BBS3D_DIR}")
set(BBS3D_CPU_LIB "${BBS3D_DIR}/build/libcpu_bbs3d.so")

include_directories(include ${PCL_INCLUDE_DIRS} ${EIGEN3_INCLUDE_DIR}
  ${BBS3D_DIR}/bbs3d/include)
link_directories(${PCL_LIBRARY_DIRS})
add_definitions(${PCL_DEFINITIONS})

# 运行时能找到 libcpu_bbs3d.so
set(CMAKE_INSTALL_RPATH "${BBS3D_DIR}/build")
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)

# BBS3D 包装层(CPU 版, 普通 C++ 编译即可)
add_library(global_reloc_bbs3d SHARED src/bbs3d_wrapper.cpp)
target_link_libraries(global_reloc_bbs3d ${BBS3D_CPU_LIB} Eigen3::Eigen)
if(OpenMP_CXX_FOUND)
  target_link_libraries(global_reloc_bbs3d OpenMP::OpenMP_CXX)
endif()

add_library(global_reloc_core
  src/scan_context.cpp
  src/keyframe_db.cpp
  src/pose_refiner.cpp
  src/branch_bound_2d.cpp
  src/map_bounds.cpp
)
target_link_libraries(global_reloc_core ${PCL_LIBRARIES} Eigen3::Eigen)
ament_target_dependencies(global_reloc_core rclcpp sensor_msgs geometry_msgs nav_msgs pcl_conversions)

add_executable(global_reloc_node src/global_reloc_node.cpp)
target_link_libraries(global_reloc_node global_reloc_core global_reloc_bbs3d ${PCL_LIBRARIES})
ament_target_dependencies(global_reloc_node
  rclcpp sensor_msgs geometry_msgs nav_msgs pcl_conversions livox_ros_driver2)

add_executable(build_reloc_db src/build_reloc_db.cpp)
target_link_libraries(build_reloc_db global_reloc_core ${PCL_LIBRARIES})
ament_target_dependencies(build_reloc_db rclcpp pcl_conversions)

install(TARGETS global_reloc_core global_reloc_bbs3d global_reloc_node build_reloc_db
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

ament_package()
