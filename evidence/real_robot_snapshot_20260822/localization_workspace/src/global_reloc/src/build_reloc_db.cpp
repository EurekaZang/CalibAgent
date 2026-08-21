#include "global_reloc/keyframe_db.hpp"
#include "global_reloc/scan_context.hpp"

#include <rclcpp/rclcpp.hpp>

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  auto node = rclcpp::Node::make_shared("build_reloc_db");

  std::string db_dir = node->declare_parameter<std::string>(
    "db_dir", "/home/unitree/ws_localization/src/FAST_LIO/PCD/reloc_db");
  std::string map_pcd = node->declare_parameter<std::string>(
    "map_pcd", "/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd");
  double voxel_leaf = node->declare_parameter<double>("voxel_leaf", 0.3);

  global_reloc::ScanContext sc;
  bool ok = global_reloc::buildDatabaseFromKeyframes(
    db_dir, map_pcd, voxel_leaf, sc, node->get_logger());

  rclcpp::shutdown();
  return ok ? 0 : 1;
}
