#pragma once

#include "global_reloc/scan_context.hpp"

#include <rclcpp/rclcpp.hpp>
#include <Eigen/Dense>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <string>
#include <vector>

namespace global_reloc
{

struct KeyframeEntry
{
  int id = 0;
  double timestamp = 0.0;
  Eigen::Vector3d position = Eigen::Vector3d::Zero();
  Eigen::Quaterniond orientation = Eigen::Quaterniond::Identity();
  Eigen::MatrixXd descriptor;
  Eigen::VectorXd ring_key;
  Eigen::VectorXd sector_key;
  std::string pcd_path;
};

struct CandidateMatch
{
  int keyframe_id = -1;
  double sc_distance = 1e9;
  int yaw_shift = 0;
  double yaw_offset_rad = 0.0;
  Eigen::Isometry3d pose = Eigen::Isometry3d::Identity();
};

class KeyframeDatabase
{
public:
  bool load(const std::string &db_dir, const ScanContext &sc, const rclcpp::Logger &logger);
  bool empty() const { return entries_.empty(); }
  size_t size() const { return entries_.size(); }

  std::vector<CandidateMatch> query(
    const Eigen::MatrixXd &query_desc,
    int top_k,
    const ScanContext &sc) const;

  bool loadKeyframeCloud(int id, pcl::PointCloud<pcl::PointXYZI> &cloud) const;

  const std::string &dbDir() const { return db_dir_; }

private:
  std::string db_dir_;
  std::vector<KeyframeEntry> entries_;
};

bool buildDatabaseFromKeyframes(
  const std::string &db_dir,
  const std::string &map_pcd_path,
  double voxel_leaf,
  const ScanContext &sc,
  const rclcpp::Logger &logger);

}  // namespace global_reloc
