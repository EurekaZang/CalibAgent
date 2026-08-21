#include "global_reloc/scan_context.hpp"

#include <algorithm>
#include <cmath>

namespace global_reloc
{

ScanContext::ScanContext(const ScanContextParams &params) : params_(params) {}

Eigen::MatrixXd ScanContext::makeDescriptor(const pcl::PointCloud<pcl::PointXYZI> &cloud) const
{
  Eigen::MatrixXd desc = Eigen::MatrixXd::Constant(
    params_.num_rings, params_.num_sectors, -1000.0);

  const double ring_step = params_.max_radius / params_.num_rings;
  const double sector_step = 2.0 * M_PI / params_.num_sectors;

  for (const auto &pt : cloud.points)
  {
    const double x = pt.x;
    const double y = pt.y;
    const double z = pt.z - params_.lidar_height;
    const double r = std::sqrt(x * x + y * y);
    if (r >= params_.max_radius || r < 0.5) continue;

    int ring = static_cast<int>(r / ring_step);
    double ang = std::atan2(y, x);
    if (ang < 0) ang += 2.0 * M_PI;
    int sector = static_cast<int>(ang / sector_step);
    ring = std::min(ring, params_.num_rings - 1);
    sector = std::min(sector, params_.num_sectors - 1);
    desc(ring, sector) = std::max(desc(ring, sector), z);
  }

  for (int r = 0; r < params_.num_rings; ++r)
  {
    for (int s = 0; s < params_.num_sectors; ++s)
    {
      if (desc(r, s) < -999.0) desc(r, s) = 0.0;
    }
  }
  return desc;
}

Eigen::VectorXd ScanContext::makeRingKey(const Eigen::MatrixXd &desc) const
{
  return desc.rowwise().mean();
}

Eigen::VectorXd ScanContext::makeSectorKey(const Eigen::MatrixXd &desc) const
{
  return desc.colwise().mean();
}

double ScanContext::distance(const Eigen::MatrixXd &a, const Eigen::MatrixXd &b, int *best_shift) const
{
  double min_dist = 1e9;
  int best = 0;
  for (int shift = 0; shift < params_.num_sectors; ++shift)
  {
    double sum = 0.0;
    int cnt = 0;
    for (int r = 0; r < params_.num_rings; ++r)
    {
      for (int s = 0; s < params_.num_sectors; ++s)
      {
        int ss = (s + shift) % params_.num_sectors;
        const double va = a(r, s);
        const double vb = b(r, ss);
        if (va < 1e-6 && vb < 1e-6) continue;
        const double denom = std::max(std::abs(va), std::abs(vb));
        if (denom < 1e-6) continue;
        sum += std::abs(va - vb) / denom;
        cnt++;
      }
    }
    if (cnt == 0) continue;
    const double dist = sum / cnt;
    if (dist < min_dist)
    {
      min_dist = dist;
      best = shift;
    }
  }
  if (best_shift) *best_shift = best;
  return min_dist;
}

}  // namespace global_reloc
