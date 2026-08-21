#include "global_reloc/bbs3d_wrapper.hpp"

#include <cpu_bbs3d/bbs3d.hpp>
#include <algorithm>
#include <limits>

// 注: Jetson Orin (CUDA 11.4 / sm_87) 上官方 gpu_bbs3d 内核评分异常(返回错误低分),
// 经 CPU/GPU 对比自测确认 CPU 版本完全正常(99.9% 命中, ~140ms), 因此这里改用 cpu::BBS3D.

namespace global_reloc
{

struct Bbs3dWrapper::Impl
{
  cpu::BBS3D bbs;
};

Bbs3dWrapper::Bbs3dWrapper() : impl_(new Impl())
{
  impl_->bbs.set_num_threads(4);
}
Bbs3dWrapper::~Bbs3dWrapper() = default;

void Bbs3dWrapper::setTarget(const std::vector<Eigen::Vector3f> &tar_points,
                             float min_level_res, int max_level)
{
  std::vector<Eigen::Vector3d> tar;
  tar.reserve(tar_points.size());
  Eigen::Vector3f pcd_min = Eigen::Vector3f::Constant(std::numeric_limits<float>::max());
  Eigen::Vector3f pcd_max = Eigen::Vector3f::Constant(std::numeric_limits<float>::lowest());
  for (const auto &p : tar_points)
  {
    tar.emplace_back(p.cast<double>());
    pcd_min = pcd_min.cwiseMin(p);
    pcd_max = pcd_max.cwiseMax(p);
  }

  impl_->bbs.set_tar_points(tar, static_cast<double>(min_level_res), max_level);
  target_set_ = true;

  // 默认回退: 若未显式设置, 后续 setZRange 会用 PCD 包围盒
  trans_min_ = pcd_min;
  trans_max_ = pcd_max;
  search_range_set_ = false;
}

void Bbs3dWrapper::applyTranslationSearchRange()
{
  if (!target_set_ || !search_range_set_) return;
  impl_->bbs.set_trans_search_range(
    trans_min_.cast<double>(),
    trans_max_.cast<double>());
}

void Bbs3dWrapper::setTranslationSearchRange(const Eigen::Vector3f &min_xyz,
                                             const Eigen::Vector3f &max_xyz)
{
  if (!target_set_) return;
  trans_min_ = min_xyz;
  trans_max_ = max_xyz;
  for (int i = 0; i < 3; ++i)
  {
    if (trans_min_[i] > trans_max_[i])
      std::swap(trans_min_[i], trans_max_[i]);
  }
  search_range_set_ = true;
  applyTranslationSearchRange();
}

void Bbs3dWrapper::setZRange(float z_min, float z_max)
{
  if (!target_set_) return;
  if (z_min > z_max) std::swap(z_min, z_max);
  trans_min_.z() = z_min;
  trans_max_.z() = z_max;
  if (!search_range_set_)
  {
    search_range_set_ = true;
  }
  applyTranslationSearchRange();
}

void Bbs3dWrapper::setAngularRange(float yaw_min, float yaw_max, float rp)
{
  impl_->bbs.set_angular_search_range(
    Eigen::Vector3d(-rp, -rp, yaw_min),
    Eigen::Vector3d(rp, rp, yaw_max));
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

  std::vector<Eigen::Vector3d> src;
  src.reserve(src_points.size());
  for (const auto &p : src_points)
    src.emplace_back(p.cast<double>());

  impl_->bbs.set_src_points(src);
  impl_->bbs.localize();

  out.localized = impl_->bbs.has_localized();
  out.pose = impl_->bbs.get_global_pose().cast<float>();
  out.score = impl_->bbs.get_best_score();
  out.score_pct = static_cast<float>(impl_->bbs.get_best_score_percentage());
  out.time_msec = impl_->bbs.get_elapsed_time();
  out.timed_out = impl_->bbs.has_timed_out();
  return out;
}

}  // namespace global_reloc
