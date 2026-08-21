#pragma once

// 纯 C++ 接口, 隔离 gpu_bbs3d.cuh(含 thrust/CUDA), 供普通 .cpp 使用
#include <Eigen/Dense>
#include <vector>
#include <memory>

namespace global_reloc
{

struct BBS3DOutput
{
  bool localized = false;
  Eigen::Matrix4f pose = Eigen::Matrix4f::Identity();
  int score = 0;
  float score_pct = 0.0f;
  double time_msec = 0.0;
  bool timed_out = false;
};

// 官方 KOKIAOKI/3d_bbs 的薄包装
// 注: Jetson Orin(CUDA 11.4/sm_87) 上 gpu 内核评分异常, 此处底层用 cpu::BBS3D
class Bbs3dWrapper
{
public:
  Bbs3dWrapper();
  ~Bbs3dWrapper();

  // 用地图点(重力对齐 map 系)构建分层体素图(不设置平移搜索范围)
  void setTarget(const std::vector<Eigen::Vector3f> &tar_points,
                 float min_level_res, int max_level);

  // 显式设置平移搜索包围盒(推荐用 2D 导航图边界, 而非整张 PCD AABB)
  void setTranslationSearchRange(const Eigen::Vector3f &min_xyz,
                                 const Eigen::Vector3f &max_xyz);

  // 角度搜索范围: yaw 全程, roll/pitch 用小范围吸收轻微倾斜
  void setAngularRange(float yaw_min, float yaw_max, float roll_pitch_range);

  // 地面机器人 z 基本固定: 仅更新 z 搜索范围, 保留当前 xy 搜索框
  void setZRange(float z_min, float z_max);

  void setScoreThreshold(float percentage);   // 0~1, 内点比例阈值
  void setTimeout(int msec);                  // <=0 关闭

  bool ready() const { return target_set_; }

  // 输入裁剪+降采样后的扫描(传感器系), 返回全局位姿
  BBS3DOutput localize(const std::vector<Eigen::Vector3f> &src_points);

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
  bool target_set_ = false;
  bool search_range_set_ = false;
  Eigen::Vector3f trans_min_ = Eigen::Vector3f::Zero();
  Eigen::Vector3f trans_max_ = Eigen::Vector3f::Zero();

  void applyTranslationSearchRange();
};

}  // namespace global_reloc
