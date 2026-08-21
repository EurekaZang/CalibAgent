#pragma once

#include <Eigen/Dense>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <vector>
#include <cstdint>
#include <unordered_set>

namespace global_reloc
{

struct BBParams
{
  double resolution = 0.2;      // 基础栅格/体素分辨率 (m)
  int    max_level = 4;         // 多分辨率层数 (最粗窗口 = 2^max_level 个 cell)
  double z_min = -0.5;          // map 系下参与的 z 下界(相对地面)
  double z_max = 3.0;           // map 系下参与的 z 上界(去天花板)
  double occupied_dilation = 0.4; // 2D 上界图的距离衰减尺度 (m)
};

struct BBResult
{
  bool   success = false;
  double score = 0.0;           // 最优位姿的 3D 命中率 (0~1)
  double best_seen = 0.0;       // 搜索中见过的最高 3D 命中率(调试/调参用)
  double x = 0.0;
  double y = 0.0;
  double yaw = 0.0;
};

// BBS3D: 地图建为 3D 占据体素(叶子真实打分) + 2D 占据金字塔(可采纳上界剪枝),
// 在 (x,y,yaw) 上做分支定界全局搜索, z/roll/pitch 由 FAST-LIO 重力对齐保证
class BranchBound2D
{
public:
  void buildMapGrid(const pcl::PointCloud<pcl::PointXYZI> &map_cloud, const BBParams &params);

  bool ready() const { return ready_; }

  // 在以 (cx,cy,cz) 为中心、半径 xy_radius 的窗口内, 全 yaw 搜索最优位姿
  BBResult search(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    double cx, double cy, double cz,
    double xy_radius,
    double yaw_step_deg,
    double min_score) const;

private:
  float scoreAt(const std::vector<std::pair<int,int>> &cells,
                int x_off, int y_off, int level) const;

  // 叶子: 旋转后的 3D 点 + 平移(tx,ty,tz) 在 3D 体素图里的命中率
  float scoreLeaf3D(const std::vector<Eigen::Vector3f> &rot_pts,
                    double tx, double ty, double tz) const;

  inline int64_t voxelKey(int ix, int iy, int iz) const
  {
    const int64_t OFF = 1 << 20;
    return ((int64_t)(ix + OFF) << 42) | ((int64_t)(iy + OFF) << 21) | (int64_t)(iz + OFF);
  }

  BBParams params_;
  bool ready_ = false;
  int grid_w_ = 0;
  int grid_h_ = 0;
  double origin_x_ = 0.0;   // grid(0,0) 对应的 map 坐标
  double origin_y_ = 0.0;
  double ground_z_ = 0.0;   // 地面参考 z
  // precomp_[level][y * grid_w_ + x] = 以(x,y)为左下角、边长 2^level 的窗口内最大基础分
  std::vector<std::vector<float>> precomp_;
  // 3D 占据体素(基础分辨率), 用于叶子真实打分
  std::unordered_set<int64_t> voxel3d_;
};

}  // namespace global_reloc
