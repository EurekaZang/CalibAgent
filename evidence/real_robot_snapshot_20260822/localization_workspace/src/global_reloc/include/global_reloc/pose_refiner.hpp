#pragma once

#include <Eigen/Dense>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl/kdtree/kdtree_flann.h>

namespace global_reloc
{

struct RefineResult
{
  bool success = false;
  double fitness = 0.0;
  Eigen::Isometry3d pose = Eigen::Isometry3d::Identity();
};

class PoseRefiner
{
public:
  void setMapCloud(const pcl::PointCloud<pcl::PointXYZI>::Ptr &map_cloud);
  // 可选: 给 GICP 由粗到精用的"粗地图"(更大体素)。粗对应距离阶段用它(更快更稳),
  // 细对应距离阶段自动切回 setMapCloud 的密图(咬准朝向)。未设置则全程用密图。
  void setCoarseMapCloud(const pcl::PointCloud<pcl::PointXYZI>::Ptr &coarse_cloud)
  {
    coarse_map_cloud_ = coarse_cloud;
  }

  RefineResult refineGICP(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const Eigen::Isometry3d &initial_guess) const;

  // 小范围 GICP: 防止走廊对称结构把位姿拉飞
  RefineResult refineGICPLocal(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const Eigen::Isometry3d &initial_guess) const;

  double scorePose(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const Eigen::Isometry3d &pose) const;

  RefineResult searchYawGrid(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const Eigen::Vector3d &position,
    double z,
    int yaw_steps = 36,
    double search_radius = 3.0) const;

  RefineResult searchPositionYawGrid(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const Eigen::Vector3d &center,
    double xy_step,
    int xy_half_steps,
    int yaw_steps) const;

  // 给已经处于 map 坐标系的点云(如 /cloud_registered)打重合分(0~1)
  double scoreCloudInMap(const pcl::PointCloud<pcl::PointXYZI> &cloud_in_map) const;

  bool hasMap() const { return map_cloud_ && !map_cloud_->empty(); }

private:
  pcl::PointCloud<pcl::PointXYZI>::Ptr map_cloud_;
  pcl::PointCloud<pcl::PointXYZI>::Ptr coarse_map_cloud_;
  mutable pcl::KdTreeFLANN<pcl::PointXYZI> map_kdtree_;
  mutable bool kdtree_ready_ = false;
  double scoreAlignment(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const Eigen::Isometry3d &pose,
    pcl::PointCloud<pcl::PointXYZI> &aligned) const;
};

}  // namespace global_reloc
