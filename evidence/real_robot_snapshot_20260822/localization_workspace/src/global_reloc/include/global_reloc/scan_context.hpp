#pragma once

#include <Eigen/Dense>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <vector>
#include <string>

namespace global_reloc
{

struct ScanContextParams
{
  int num_rings = 20;
  int num_sectors = 60;
  double max_radius = 80.0;
  double lidar_height = 0.0;
};

class ScanContext
{
public:
  explicit ScanContext(const ScanContextParams &params = ScanContextParams());

  Eigen::MatrixXd makeDescriptor(const pcl::PointCloud<pcl::PointXYZI> &cloud) const;
  Eigen::VectorXd makeRingKey(const Eigen::MatrixXd &desc) const;
  Eigen::VectorXd makeSectorKey(const Eigen::MatrixXd &desc) const;

  double distance(const Eigen::MatrixXd &a, const Eigen::MatrixXd &b, int *best_shift = nullptr) const;

  int numSectors() const { return params_.num_sectors; }

private:
  ScanContextParams params_;
};

}  // namespace global_reloc
