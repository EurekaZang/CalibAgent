#include "global_reloc/branch_bound_2d.hpp"

#include <pcl/filters/voxel_grid.h>
#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>

namespace global_reloc
{

void BranchBound2D::buildMapGrid(const pcl::PointCloud<pcl::PointXYZI> &map_cloud, const BBParams &params)
{
  params_ = params;
  ready_ = false;
  precomp_.clear();
  voxel3d_.clear();
  if (map_cloud.empty()) return;

  const double res = params_.resolution;

  // 1) 计算 z-band 内点的 XY 范围
  double min_x = std::numeric_limits<double>::max();
  double min_y = std::numeric_limits<double>::max();
  double max_x = -std::numeric_limits<double>::max();
  double max_y = -std::numeric_limits<double>::max();
  // z 基准: 取所有点 z 的较低分位作为地面参考
  double z_lo = std::numeric_limits<double>::max();
  for (const auto &p : map_cloud.points) z_lo = std::min(z_lo, (double)p.z);
  ground_z_ = z_lo;

  bool any = false;
  for (const auto &p : map_cloud.points)
  {
    const double zr = p.z - z_lo;
    if (zr < params_.z_min || zr > params_.z_max) continue;
    min_x = std::min(min_x, (double)p.x);
    min_y = std::min(min_y, (double)p.y);
    max_x = std::max(max_x, (double)p.x);
    max_y = std::max(max_y, (double)p.y);
    any = true;
  }
  if (!any) return;

  // 边界外扩, 给搜索留余量
  const double pad = 2.0;
  origin_x_ = min_x - pad;
  origin_y_ = min_y - pad;
  grid_w_ = static_cast<int>((max_x - min_x + 2 * pad) / res) + 1;
  grid_h_ = static_cast<int>((max_y - min_y + 2 * pad) / res) + 1;
  if (grid_w_ <= 0 || grid_h_ <= 0) return;

  // 2) 基础占据图(布尔, 2D) + 3D 占据体素
  std::vector<uint8_t> occ(static_cast<size_t>(grid_w_) * grid_h_, 0);
  voxel3d_.reserve(map_cloud.size());
  for (const auto &p : map_cloud.points)
  {
    const double zr = p.z - z_lo;
    if (zr < params_.z_min || zr > params_.z_max) continue;
    int gx = static_cast<int>((p.x - origin_x_) / res);
    int gy = static_cast<int>((p.y - origin_y_) / res);
    if (gx < 0 || gx >= grid_w_ || gy < 0 || gy >= grid_h_) continue;
    occ[static_cast<size_t>(gy) * grid_w_ + gx] = 1;
    // z 用"离地高度"(p.z - ground_z_), 与扫描端的离地高度对齐, 消除绝对 z 偏移
    int iz = static_cast<int>(std::floor((p.z - z_lo) / res));
    voxel3d_.insert(voxelKey(gx, gy, iz));
  }

  // 3) 距离衰减得到平滑基础分: score = max(0, 1 - dist/dilation)
  //    用两遍 chamfer 距离变换近似欧氏距离
  const float INF = 1e9f;
  std::vector<float> dist(static_cast<size_t>(grid_w_) * grid_h_, INF);
  for (int y = 0; y < grid_h_; ++y)
    for (int x = 0; x < grid_w_; ++x)
      if (occ[static_cast<size_t>(y) * grid_w_ + x]) dist[static_cast<size_t>(y) * grid_w_ + x] = 0.0f;

  auto idx = [&](int x, int y) { return static_cast<size_t>(y) * grid_w_ + x; };
  const float d1 = 1.0f, d2 = 1.41421356f;
  // 正向
  for (int y = 0; y < grid_h_; ++y)
    for (int x = 0; x < grid_w_; ++x)
    {
      float &d = dist[idx(x, y)];
      if (x > 0) d = std::min(d, dist[idx(x - 1, y)] + d1);
      if (y > 0) d = std::min(d, dist[idx(x, y - 1)] + d1);
      if (x > 0 && y > 0) d = std::min(d, dist[idx(x - 1, y - 1)] + d2);
      if (x + 1 < grid_w_ && y > 0) d = std::min(d, dist[idx(x + 1, y - 1)] + d2);
    }
  // 反向
  for (int y = grid_h_ - 1; y >= 0; --y)
    for (int x = grid_w_ - 1; x >= 0; --x)
    {
      float &d = dist[idx(x, y)];
      if (x + 1 < grid_w_) d = std::min(d, dist[idx(x + 1, y)] + d1);
      if (y + 1 < grid_h_) d = std::min(d, dist[idx(x, y + 1)] + d1);
      if (x + 1 < grid_w_ && y + 1 < grid_h_) d = std::min(d, dist[idx(x + 1, y + 1)] + d2);
      if (x > 0 && y + 1 < grid_h_) d = std::min(d, dist[idx(x - 1, y + 1)] + d2);
    }

  std::vector<float> base(static_cast<size_t>(grid_w_) * grid_h_, 0.0f);
  const float dil_cells = static_cast<float>(params_.occupied_dilation / res);
  for (size_t i = 0; i < base.size(); ++i)
  {
    float s = 1.0f - dist[i] / std::max(dil_cells, 1e-3f);
    base[i] = s > 0.0f ? s : 0.0f;
  }

  // 4) 多分辨率 max 预计算: precomp_[L][cell] = 以该 cell 为左下角、边长 2^L 的窗口最大值
  precomp_.assign(params_.max_level + 1, std::vector<float>());
  precomp_[0] = base;
  for (int L = 1; L <= params_.max_level; ++L)
  {
    const int half = 1 << (L - 1);
    const auto &prev = precomp_[L - 1];
    std::vector<float> cur(static_cast<size_t>(grid_w_) * grid_h_, 0.0f);
    for (int y = 0; y < grid_h_; ++y)
    {
      for (int x = 0; x < grid_w_; ++x)
      {
        float v = prev[idx(x, y)];
        int x2 = std::min(x + half, grid_w_ - 1);
        int y2 = std::min(y + half, grid_h_ - 1);
        v = std::max(v, prev[idx(x2, y)]);
        v = std::max(v, prev[idx(x, y2)]);
        v = std::max(v, prev[idx(x2, y2)]);
        cur[idx(x, y)] = v;
      }
    }
    precomp_[L] = std::move(cur);
  }

  ready_ = true;
}

float BranchBound2D::scoreAt(const std::vector<std::pair<int,int>> &cells,
                             int x_off, int y_off, int level) const
{
  const auto &grid = precomp_[level];
  double sum = 0.0;
  for (const auto &c : cells)
  {
    int x = c.first + x_off;
    int y = c.second + y_off;
    if (x < 0 || x >= grid_w_ || y < 0 || y >= grid_h_) continue;
    sum += grid[static_cast<size_t>(y) * grid_w_ + x];
  }
  return static_cast<float>(sum / std::max<size_t>(cells.size(), 1));
}

float BranchBound2D::scoreLeaf3D(const std::vector<Eigen::Vector3f> &rot_pts,
                                 double tx, double ty, double /*tz*/) const
{
  const double res = params_.resolution;
  int hit = 0;
  for (const auto &p : rot_pts)
  {
    double mx = p.x() + tx;
    double my = p.y() + ty;
    int ix = static_cast<int>(std::floor((mx - origin_x_) / res));
    int iy = static_cast<int>(std::floor((my - origin_y_) / res));
    // p.z() 已是"离地高度", 与地图体素的离地高度同基准
    int iz = static_cast<int>(std::floor(p.z() / res));
    // 命中体素或其 z 方向 ±1 邻域(容忍轻微高度差)
    if (voxel3d_.count(voxelKey(ix, iy, iz)) ||
        voxel3d_.count(voxelKey(ix, iy, iz + 1)) ||
        voxel3d_.count(voxelKey(ix, iy, iz - 1)))
      ++hit;
  }
  return rot_pts.empty() ? 0.0f : static_cast<float>(hit) / rot_pts.size();
}

BBResult BranchBound2D::search(
  const pcl::PointCloud<pcl::PointXYZI> &scan_in,
  double cx, double cy, double cz,
  double xy_radius,
  double yaw_step_deg,
  double min_score) const
{
  BBResult result;
  if (!ready_ || scan_in.empty()) return result;

  const double res = params_.resolution;

  // 降采样 scan 加速
  pcl::PointCloud<pcl::PointXYZI>::Ptr scan(new pcl::PointCloud<pcl::PointXYZI>(scan_in));
  {
    pcl::VoxelGrid<pcl::PointXYZI> vg;
    vg.setLeafSize(0.25f, 0.25f, 0.25f);
    vg.setInputCloud(scan);
    pcl::PointCloud<pcl::PointXYZI> ds;
    vg.filter(ds);
    *scan = ds;
  }
  // 保留传感器系 3D 点(去过近/过远), z 留给 3D 体素打分
  std::vector<Eigen::Vector3f> pts;
  pts.reserve(scan->size());
  for (const auto &p : scan->points)
  {
    double r2 = p.x * p.x + p.y * p.y;
    if (r2 < 0.49 || r2 > 60.0 * 60.0) continue;
    pts.emplace_back(p.x, p.y, p.z);
  }
  if (pts.size() < 50) return result;

  // 估计扫描端地面高度(低分位, 抗离群), 把点的 z 转成"离地高度"
  {
    std::vector<float> zs;
    zs.reserve(pts.size());
    for (const auto &p : pts) zs.push_back(p.z());
    std::sort(zs.begin(), zs.end());
    float scan_ground = zs[static_cast<size_t>(zs.size() * 0.02)];
    for (auto &p : pts) p.z() -= scan_ground;
  }

  // 搜索窗口(以 cx,cy 为中心)的 cell 起点
  const int win_cells = static_cast<int>(std::ceil(xy_radius / res));
  const int base_cx = static_cast<int>((cx - origin_x_) / res);
  const int base_cy = static_cast<int>((cy - origin_y_) / res);
  const int start_x = base_cx - win_cells;  // x_off=0 对应此处
  const int start_y = base_cy - win_cells;
  const int span = 2 * win_cells;           // x_off / y_off 取值范围 [0, span]

  const int top_level = params_.max_level;
  const int coarse_step = 1 << top_level;

  const int n_yaw = std::max(1, static_cast<int>(std::round(360.0 / yaw_step_deg)));
  double best_score = min_score;   // 真实 3D 命中率下界
  float best_seen = 0.0f;          // 仅用于日志: 见过的最高真实分
  bool found = false;

  for (int iy = 0; iy < n_yaw; ++iy)
  {
    const double yaw = -M_PI + (2.0 * M_PI * iy) / n_yaw;
    const double c = std::cos(yaw), s = std::sin(yaw);

    // 旋转后的 scan 点: 2D cell(给上界用) + 3D 点(给叶子真实分用)
    std::vector<std::pair<int,int>> cells;
    std::vector<Eigen::Vector3f> rot_pts;
    cells.reserve(pts.size());
    rot_pts.reserve(pts.size());
    for (const auto &p : pts)
    {
      double rx = c * p.x() - s * p.y();
      double ry = s * p.x() + c * p.y();
      cells.emplace_back(static_cast<int>(std::floor(rx / res)),
                         static_cast<int>(std::floor(ry / res)));
      rot_pts.emplace_back((float)rx, (float)ry, p.z());
    }

    // 分支定界(best-first): 2D 占据金字塔给可采纳上界, 叶子用 3D 体素算真实分
    struct Node { int xo, yo, level; float ub; };
    auto cmp = [](const Node &a, const Node &b) { return a.ub < b.ub; };
    std::priority_queue<Node, std::vector<Node>, decltype(cmp)> pq(cmp);

    for (int yo = 0; yo <= span; yo += coarse_step)
      for (int xo = 0; xo <= span; xo += coarse_step)
      {
        float ub = scoreAt(cells, start_x + xo, start_y + yo, top_level);
        if (ub > best_score) pq.push({xo, yo, top_level, ub});
      }

    while (!pq.empty())
    {
      Node node = pq.top();
      pq.pop();
      if (node.ub <= best_score) break;  // 上界都不优于当前最优 -> 该 yaw 剩余全剪枝

      if (node.level == 0)
      {
        // 叶子: 用 3D 体素算真实命中率(上界是 2D, 可采纳但偏乐观)
        double tx = origin_x_ + (start_x + node.xo) * res + 0.5 * res;
        double ty = origin_y_ + (start_y + node.yo) * res + 0.5 * res;
        float s3d = scoreLeaf3D(rot_pts, tx, ty, cz);
        if (s3d > best_seen) best_seen = s3d;
        if (s3d > best_score)
        {
          best_score = s3d;
          found = true;
          result.success = true;
          result.score = s3d;
          result.x = tx;
          result.y = ty;
          result.yaw = yaw;
        }
        continue;  // 继续弹出, 直到堆顶上界 <= best_score
      }

      const int child_level = node.level - 1;
      const int half = 1 << child_level;
      for (int dy = 0; dy <= half; dy += half)
        for (int dx = 0; dx <= half; dx += half)
        {
          int nxo = node.xo + dx;
          int nyo = node.yo + dy;
          if (nxo > span || nyo > span) continue;
          float ub = scoreAt(cells, start_x + nxo, start_y + nyo, child_level);
          if (ub > best_score) pq.push({nxo, nyo, child_level, ub});
        }
    }
  }

  result.best_seen = best_seen;
  result.success = found;
  return result;
}

}  // namespace global_reloc
