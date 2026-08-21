#include "global_reloc/bbs3d_wrapper.hpp"

#include <gpu_bbs3d/bbs3d.cuh>

namespace global_reloc
{

struct Bbs3dWrapper::Impl
{
  gpu::BBS3D bbs;
};

Bbs3dWrapper::Bbs3dWrapper() : impl_(new Impl()) {}
Bbs3dWrapper::~Bbs3dWrapper() = default;

void Bbs3dWrapper::setTarget(const std::vector<Eigen::Vector3f> &tar_points,
                             float min_level_res, int max_level)
{
  impl_->bbs.set_tar_points(tar_points, min_level_res, max_level);
  impl_->bbs.set_trans_search_range(tar_points);  // 平移范围 = 地图包围盒(含 z)
  target_set_ = true;
}

void Bbs3dWrapper::setAngularRange(float yaw_min, float yaw_max, float rp)
{
  impl_->bbs.set_angular_search_range(
    Eigen::Vector3f(-rp, -rp, yaw_min),
    Eigen::Vector3f(rp, rp, yaw_max));
}

void Bbs3dWrapper::setScoreThreshold(float percentage)
{
  impl_->bbs.set_score_threshold_percentage(percentage);
}

void Bbs3dWrapper::setTimeout(int msec)
{
  if (msec > 0)
  {
    impl_->bbs.enable_timeout();
    impl_->bbs.set_timeout_duration_in_msec(msec);
  }
  else
  {
    impl_->bbs.disable_timeout();
  }
}

BBS3DOutput Bbs3dWrapper::localize(const std::vector<Eigen::Vector3f> &src_points)
{
  BBS3DOutput out;
  if (!target_set_ || src_points.empty()) return out;
  impl_->bbs.set_src_points(src_points);
  impl_->bbs.localize();
  out.localized = impl_->bbs.has_localized();
  out.pose = impl_->bbs.get_global_pose();
  out.score = impl_->bbs.get_best_score();
  out.score_pct = impl_->bbs.get_best_score_percentage();
  out.time_msec = impl_->bbs.get_elapsed_time();
  out.timed_out = impl_->bbs.has_timed_out();
  return out;
}

}  // namespace global_reloc
