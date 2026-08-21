#include "global_reloc/pose_refiner.hpp"

#include <pcl/filters/voxel_grid.h>
#include <pcl/registration/gicp.h>
#include <pcl/common/transforms.h>

#include <cmath>

namespace global_reloc
{

void PoseRefiner::setMapCloud(const pcl::PointCloud<pcl::PointXYZI>::Ptr &map_cloud)
{
  map_cloud_ = map_cloud;
  if (map_cloud_ && !map_cloud_->empty())
  {
    map_kdtree_.setInputCloud(map_cloud_);
    kdtree_ready_ = true;
  }
}

double PoseRefiner::scoreCloudInMap(const pcl::PointCloud<pcl::PointXYZI> &cloud_in_map) const
{
  if (!kdtree_ready_ || cloud_in_map.empty()) return 0.0;
  int inliers = 0;
  const float thresh2 = 0.5f * 0.5f;
  std::vector<int> idx(1);
  std::vector<float> dist2(1);
  for (const auto &pt : cloud_in_map.points)
  {
    if (map_kdtree_.nearestKSearch(pt, 1, idx, dist2) > 0 && dist2[0] < thresh2)
    {
      inliers++;
    }
  }
  return static_cast<double>(inliers) / static_cast<double>(cloud_in_map.size());
}

double PoseRefiner::scoreAlignment(
  const pcl::PointCloud<pcl::PointXYZI> &scan,
  const Eigen::Isometry3d &pose,
  pcl::PointCloud<pcl::PointXYZI> &aligned) const
{
  if (!kdtree_ready_ || scan.empty()) return 0.0;

  pcl::transformPointCloud(scan, aligned, pose.matrix().cast<float>());

  int inliers = 0;
  const float thresh = 0.5f;
  const float thresh2 = thresh * thresh;
  std::vector<int> idx(1);
  std::vector<float> dist2(1);

  for (const auto &pt : aligned.points)
  {
    if (map_kdtree_.nearestKSearch(pt, 1, idx, dist2) > 0 && dist2[0] < thresh2)
    {
      inliers++;
    }
  }
  return static_cast<double>(inliers) / static_cast<double>(scan.size());
}

double PoseRefiner::scorePose(
  const pcl::PointCloud<pcl::PointXYZI> &scan,
  const Eigen::Isometry3d &pose) const
{
  pcl::PointCloud<pcl::PointXYZI> aligned;
  return scoreAlignment(scan, pose, aligned);
}

RefineResult PoseRefiner::refineGICPLocal(
  const pcl::PointCloud<pcl::PointXYZI> &scan,
  const Eigen::Isometry3d &initial_guess) const
{
  RefineResult out;
  if (!map_cloud_ || map_cloud_->empty()) return out;

  pcl::PointCloud<pcl::PointXYZI>::Ptr src(new pcl::PointCloud<pcl::PointXYZI>(scan));
  pcl::VoxelGrid<pcl::PointXYZI> vg;
  vg.setLeafSize(0.2f, 0.2f, 0.2f);
  vg.setInputCloud(src);
  vg.filter(*src);

  const double corr_stages[] = {0.5, 0.3};
  Eigen::Matrix4f T = initial_guess.matrix().cast<float>();
  bool any_converged = false;

  for (double corr : corr_stages)
  {
    pcl::GeneralizedIterativeClosestPoint<pcl::PointXYZI, pcl::PointXYZI> gicp;
    gicp.setInputSource(src);
    gicp.setInputTarget(map_cloud_);
    gicp.setMaximumIterations(25);
    gicp.setMaxCorrespondenceDistance(corr);
    gicp.setTransformationEpsilon(1e-6);
    gicp.setEuclideanFitnessEpsilon(1e-6);

    pcl::PointCloud<pcl::PointXYZI> aligned;
    gicp.align(aligned, T);
    if (!gicp.hasConverged()) continue;
    T = gicp.getFinalTransformation();
    any_converged = true;
  }

  if (!any_converged) return out;

  out.pose = Eigen::Isometry3d::Identity();
  out.pose.matrix() = T.cast<double>();
  pcl::PointCloud<pcl::PointXYZI> eval;
  out.fitness = scoreAlignment(scan, out.pose, eval);
  out.success = out.fitness > 0.25;
  return out;
}

RefineResult PoseRefiner::refineGICP(
  const pcl::PointCloud<pcl::PointXYZI> &scan,
  const Eigen::Isometry3d &initial_guess) const
{
  RefineResult out;
  if (!map_cloud_ || map_cloud_->empty()) return out;

  // 源扫描用较细体素(0.2m), 保留细节让角度精修更敏感
  pcl::PointCloud<pcl::PointXYZI>::Ptr src(new pcl::PointCloud<pcl::PointXYZI>(scan));
  pcl::VoxelGrid<pcl::PointXYZI> vg;
  vg.setLeafSize(0.2f, 0.2f, 0.2f);
  vg.setInputCloud(src);
  vg.filter(*src);

  // 由粗到精多级 GICP: 大对应距离先拉近位置, 小对应距离再咬准朝向。
  // 地图分辨率也由粗到精: 对应距离 >=1.0m 的粗阶段用粗地图(更快更稳),
  // 细阶段切回密图(咬准几度内的朝向)。粗地图未设置时全程用密图。
  const double corr_stages[] = {2.0, 0.8, 0.3};
  Eigen::Matrix4f T = initial_guess.matrix().cast<float>();
  bool any_converged = false;

  for (double corr : corr_stages)
  {
    const auto &target = (coarse_map_cloud_ && !coarse_map_cloud_->empty() && corr >= 1.0)
                           ? coarse_map_cloud_
                           : map_cloud_;
    pcl::GeneralizedIterativeClosestPoint<pcl::PointXYZI, pcl::PointXYZI> gicp;
    gicp.setInputSource(src);
    gicp.setInputTarget(target);
    gicp.setMaximumIterations(30);
    gicp.setMaxCorrespondenceDistance(corr);
    gicp.setTransformationEpsilon(1e-6);
    gicp.setEuclideanFitnessEpsilon(1e-6);

    pcl::PointCloud<pcl::PointXYZI> aligned;
    gicp.align(aligned, T);
    if (!gicp.hasConverged()) continue;
    T = gicp.getFinalTransformation();
    any_converged = true;
  }

  if (!any_converged) return out;

  out.pose = Eigen::Isometry3d::Identity();
  out.pose.matrix() = T.cast<double>();
  pcl::PointCloud<pcl::PointXYZI> eval;
  out.fitness = scoreAlignment(scan, out.pose, eval);
  out.success = out.fitness > 0.25;
  return out;
}

RefineResult PoseRefiner::searchYawGrid(
  const pcl::PointCloud<pcl::PointXYZI> &scan,
  const Eigen::Vector3d &position,
  double z,
  int yaw_steps,
  double search_radius) const
{
  RefineResult best;
  for (int i = 0; i < yaw_steps; ++i)
  {
    const double yaw = -M_PI + (2.0 * M_PI * i) / yaw_steps;
    Eigen::Isometry3d pose = Eigen::Isometry3d::Identity();
    pose.linear() = Eigen::AngleAxisd(yaw, Eigen::Vector3d::UnitZ()).toRotationMatrix();
    pose.translation() = Eigen::Vector3d(position.x(), position.y(), z);

    pcl::PointCloud<pcl::PointXYZI> aligned;
    const double score = scoreAlignment(scan, pose, aligned);
    if (score > best.fitness)
    {
      best.fitness = score;
      best.pose = pose;
      best.success = score > 0.25;
    }
  }
  (void)search_radius;
  return best;
}

RefineResult PoseRefiner::searchPositionYawGrid(
  const pcl::PointCloud<pcl::PointXYZI> &scan,
  const Eigen::Vector3d &center,
  double xy_step,
  int xy_half_steps,
  int yaw_steps) const
{
  RefineResult best;
  for (int ix = -xy_half_steps; ix <= xy_half_steps; ++ix)
  {
    for (int iy = -xy_half_steps; iy <= xy_half_steps; ++iy)
    {
      Eigen::Vector3d pos = center;
      pos.x() += ix * xy_step;
      pos.y() += iy * xy_step;
      RefineResult yaw_best = searchYawGrid(scan, pos, center.z(), yaw_steps, xy_step);
      if (yaw_best.fitness > best.fitness)
      {
        best = yaw_best;
      }
    }
  }
  return best;
}

}  // namespace global_reloc
