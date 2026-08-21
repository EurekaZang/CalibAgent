#include "global_reloc/keyframe_db.hpp"
#include "global_reloc/pose_refiner.hpp"
#include "global_reloc/scan_context.hpp"
#include "global_reloc/bbs3d_wrapper.hpp"
#include "global_reloc/map_bounds.hpp"

#include <livox_ros_driver2/msg/custom_msg.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <pcl/io/pcd_io.h>
#include <pcl/filters/voxel_grid.h>
#include <pcl_conversions/pcl_conversions.h>

#include <rclcpp/rclcpp.hpp>
#include <sys/stat.h>
#include <mutex>
#include <deque>
#include <cmath>
#include <limits>
#include <string>
#include <vector>
#include <array>

namespace global_reloc
{

namespace
{
// 返回文件修改时间(秒); 文件不存在返回 -1。用于派生缓存(map_gicp/map_voxel)的失效判断。
long fileMtime(const std::string &path)
{
  struct stat st;
  if (stat(path.c_str(), &st) != 0) return -1;
  return static_cast<long>(st.st_mtime);
}

Eigen::Isometry3d scHintPose(const CandidateMatch &c)
{
  Eigen::Isometry3d guess = c.pose;
  Eigen::Isometry3d yaw_corr = Eigen::Isometry3d::Identity();
  yaw_corr.linear() =
    Eigen::AngleAxisd(c.yaw_offset_rad, Eigen::Vector3d::UnitZ()).toRotationMatrix();
  return guess * yaw_corr;
}

double poseYaw(const Eigen::Isometry3d &T)
{
  return std::atan2(T.linear()(1, 0), T.linear()(0, 0));
}

double normalizeAngle(double a)
{
  while (a > M_PI) a -= 2.0 * M_PI;
  while (a < -M_PI) a += 2.0 * M_PI;
  return a;
}
}  // namespace

class GlobalRelocNode : public rclcpp::Node
{
public:
  GlobalRelocNode() : Node("global_reloc")
  {
    db_dir_ = declare_parameter<std::string>("db_dir", "");
    map_pcd_ = declare_parameter<std::string>("map_pcd", "");
    top_k_ = declare_parameter<int>("top_k", 5);
    min_fitness_ = declare_parameter<double>("min_fitness", 0.35);
    yaw_search_steps_ = declare_parameter<int>("yaw_search_steps", 36);
    xy_search_step_ = declare_parameter<double>("xy_search_step", 1.0);
    xy_search_half_ = declare_parameter<int>("xy_search_half_steps", 2);
    auto_publish_ = declare_parameter<bool>("auto_publish_initialpose", true);
    reloc_period_sec_ = declare_parameter<double>("reloc_retry_period", 5.0);
    tracking_lost_fitness_ = declare_parameter<double>("tracking_lost_fitness", 0.15);
    odom_lost_timeout_ = declare_parameter<double>("odom_lost_timeout", 3.0);
    max_accum_frames_ = declare_parameter<int>("max_accum_frames", 10);
    verify_period_sec_ = declare_parameter<double>("verify_period", 1.0);
    verify_min_score_ = declare_parameter<double>("verify_min_score", 0.45);
    verify_fail_limit_ = declare_parameter<int>("verify_fail_limit", 3);

    // The last trustworthy map pose is a fast local-recovery seed only.  It
    // must not constrain the full-map fallback: after the robot is carried,
    // the physically correct pose can be arbitrarily far from this anchor.
    // Symmetric global candidates are handled by the geometric/SC yaw checks
    // below rather than by assuming that the robot never changes location.
    continuity_enable_ = declare_parameter<bool>("continuity.enabled", true);
    continuity_max_translation_ =
      declare_parameter<double>("continuity.max_translation", 2.5);
    continuity_max_yaw_deg_ =
      declare_parameter<double>("continuity.max_yaw_deg", 90.0);
    continuity_min_fitness_ =
      declare_parameter<double>("continuity.min_fitness", 0.85);
    const auto startup_pose = declare_parameter<std::vector<double>>(
      "continuity.startup_pose", std::vector<double>{});
    if (continuity_enable_ && startup_pose.size() >= 4)
    {
      continuity_anchor_ = Eigen::Isometry3d::Identity();
      continuity_anchor_.translation() =
        Eigen::Vector3d(startup_pose[0], startup_pose[1], startup_pose[2]);
      continuity_anchor_.linear() =
        Eigen::AngleAxisd(startup_pose[3], Eigen::Vector3d::UnitZ()).toRotationMatrix();
      has_continuity_anchor_ = true;
      RCLCPP_INFO(get_logger(),
        "Relocalization continuity anchor: [%.3f %.3f %.3f] yaw=%.1f deg, limits %.1fm/%.1fdeg",
        startup_pose[0], startup_pose[1], startup_pose[2],
        startup_pose[3] * 180.0 / M_PI,
        continuity_max_translation_, continuity_max_yaw_deg_);
    }

    // BBS3D(官方 KOKIAOKI/3d_bbs GPU)参数
    bb_enable_      = declare_parameter<bool>("bbs3d.enable", true);
    bbs3d_min_level_res_ = declare_parameter<double>("bbs3d.min_level_res", 0.5);
    bbs3d_max_level_     = declare_parameter<int>("bbs3d.max_level", 6);
    bbs3d_tar_leaf_      = declare_parameter<double>("bbs3d.tar_leaf_size", 0.1);
    bbs3d_src_leaf_      = declare_parameter<double>("bbs3d.src_leaf_size", 0.5);
    bbs3d_min_scan_      = declare_parameter<double>("bbs3d.min_scan_range", 1.0);
    bbs3d_max_scan_      = declare_parameter<double>("bbs3d.max_scan_range", 40.0);
    bbs3d_rp_range_      = declare_parameter<double>("bbs3d.roll_pitch_range", 0.0);
    bbs3d_score_thresh_  = declare_parameter<double>("bbs3d.score_threshold_percentage", 0.5);
    bbs3d_timeout_msec_  = declare_parameter<int>("bbs3d.timeout_msec", 0);
    bbs3d_ground_z_      = declare_parameter<double>("bbs3d.ground_z", 0.0);
    bbs3d_z_range_       = declare_parameter<double>("bbs3d.z_search_range", 1.0);
    grid_map_yaml_       = declare_parameter<std::string>("grid_map_yaml", "");
    bbs3d_search_margin_ = declare_parameter<double>("bbs3d.search_margin", 2.0);
    clip_search_to_grid_map_ = declare_parameter<bool>("clip_search_to_grid_map", true);

    // 搜索策略: "expand_from_center"(从中心一圈圈外扩) | "sc_candidates"(SC候选附近)
    search_mode_ = declare_parameter<std::string>("search.mode", "expand_from_center");
    // 外扩中心: 暂定地图原点; 后续可传初始位姿 [x, y]
    search_center_ = declare_parameter<std::vector<double>>(
      "search.center", std::vector<double>{0.0, 0.0});
    ring_step_ = declare_parameter<double>("search.ring_step", 3.0);
    ring_max_radius_ = declare_parameter<double>("search.max_radius", 0.0);  // 0=自动

    // SC 候选模式参数(search.mode=sc_candidates 时用)
    candidate_radius_ = declare_parameter<double>("near_first_search.candidate_radius", 5.0);
    expand_radii_ = declare_parameter<std::vector<double>>(
      "near_first_search.expand_radii", std::vector<double>{4.0, 10.0, 25.0});

    // 地面约束: 只在 3D 点云中有地面的区域搜索(没有地面=机器人不可能在那)
    ground_filter_enable_ = declare_parameter<bool>("ground_filter.enable", true);
    ground_z_min_rel_ = declare_parameter<double>("ground_filter.z_min", -0.6);
    ground_z_max_rel_ = declare_parameter<double>("ground_filter.z_max", 0.5);
    ground_cell_ = declare_parameter<double>("ground_filter.cell", 1.0);
    ground_min_pts_ = declare_parameter<int>("ground_filter.min_points", 2);
    ground_dilate_ = declare_parameter<int>("ground_filter.dilate_cells", 1);

    // 接受门槛: BBS3D 100% 也可能是假阳性, 必须 GICP 重合度达标
    min_accept_fitness_ = declare_parameter<double>("accept.min_gicp_fitness", 0.50);
    sc_gate_enable_ = declare_parameter<bool>("accept.sc_gate_enable", true);
    sc_gate_max_dist_ = declare_parameter<double>("accept.sc_gate_max_dist", 5.0);
    high_accept_fitness_ = declare_parameter<double>("accept.high_gicp_fitness", 0.85);
    use_sc_center_ = declare_parameter<bool>("search.use_sc_center_when_confident", true);
    sc_center_max_dist_ = declare_parameter<double>("search.sc_confident_max_dist", 0.35);
    sc_tight_radius_ = declare_parameter<double>("search.sc_tight_radius", 1.5);
    sc_confident_xy_gate_ = declare_parameter<double>("search.sc_confident_xy_gate", 1.2);
    sc_confident_yaw_gate_deg_ =
      declare_parameter<double>("search.sc_confident_yaw_gate_deg", 40.0);
    sc_gicp_first_ = declare_parameter<bool>("search.sc_gicp_first", true);
    sc_direct_pose_ = declare_parameter<bool>("search.sc_direct_pose", false);
    sc_direct_min_score_ = declare_parameter<double>("search.sc_direct_min_score", 0.45);

    ScanContextParams sc_params;
    sc_params.max_radius = declare_parameter<double>("scan_context.max_radius", 80.0);
    sc_params.num_rings = declare_parameter<int>("scan_context.num_rings", 20);
    sc_params.num_sectors = declare_parameter<int>("scan_context.num_sectors", 60);
    sc_ = ScanContext(sc_params);

    if (db_dir_.empty())
    {
      RCLCPP_ERROR(get_logger(), "db_dir parameter is required");
      throw std::runtime_error("db_dir not set");
    }

    std::string voxel_map = db_dir_ + "/map_voxel.pcd";
    pcl::PointCloud<pcl::PointXYZI>::Ptr map(new pcl::PointCloud<pcl::PointXYZI>());
    // 同样校验 map_voxel.pcd 缓存是否比 scans.pcd 旧(过期则忽略, 从完整图重建)。
    const bool voxel_stale = []( const std::string &cache, const std::string &src) {
        long c = fileMtime(cache), s = fileMtime(src);
        return (s >= 0 && c >= 0 && c < s);
      }(voxel_map, map_pcd_);
    if (voxel_stale)
    {
      RCLCPP_WARN(get_logger(),
        "Stale map_voxel cache (older than %s) -> rebuilding from current map", map_pcd_.c_str());
    }
    if ((voxel_stale || pcl::io::loadPCDFile<pcl::PointXYZI>(voxel_map, *map) != 0) && !map_pcd_.empty())
    {
      RCLCPP_WARN(get_logger(), "map_voxel.pcd missing/stale, loading full map (slow): %s", map_pcd_.c_str());
      if (pcl::io::loadPCDFile<pcl::PointXYZI>(map_pcd_, *map) != 0)
      {
        throw std::runtime_error("Failed to load map point cloud");
      }
      pcl::VoxelGrid<pcl::PointXYZI> vg;
      vg.setLeafSize(0.3f, 0.3f, 0.3f);
      vg.setInputCloud(map);
      pcl::PointCloud<pcl::PointXYZI> ds;
      vg.filter(ds);
      *map = ds;
      pcl::io::savePCDFileBinary(voxel_map, ds);
    }
    // GICP 精修用更密的地图(0.15m), 让朝向能咬到几度内; 首次从完整地图构建并缓存
    {
      std::string gicp_map_path = db_dir_ + "/map_gicp.pcd";
      // 缓存失效校验: map_gicp.pcd 比 scans.pcd 旧 => 是上一次建图的残留缓存,
      // 必须丢弃重建。否则 GICP 会把扫描对齐到旧图坐标系, 发布的初值整体歪
      // (实测 06-10 旧缓存 + 06-11 新图 => 初值偏 ~40°, 点云在 RViz 里倾斜)。
      const long gicp_mtime = fileMtime(gicp_map_path);
      const long src_mtime = fileMtime(map_pcd_);
      const bool gicp_stale = (src_mtime >= 0 && gicp_mtime >= 0 && gicp_mtime < src_mtime);
      if (gicp_stale)
      {
        RCLCPP_WARN(get_logger(),
          "Stale dense GICP cache (%s older than %s) -> rebuilding from current map",
          gicp_map_path.c_str(), map_pcd_.c_str());
      }
      pcl::PointCloud<pcl::PointXYZI>::Ptr gmap(new pcl::PointCloud<pcl::PointXYZI>());
      if (!gicp_stale &&
          pcl::io::loadPCDFile<pcl::PointXYZI>(gicp_map_path, *gmap) == 0 && gmap->size() > map->size())
      {
        RCLCPP_INFO(get_logger(), "Loaded dense GICP map: %zu points", gmap->size());
        refiner_.setMapCloud(gmap);
      }
      else if (!map_pcd_.empty())
      {
        RCLCPP_INFO(get_logger(), "Building dense GICP map (0.15m) from full map (once)...");
        pcl::PointCloud<pcl::PointXYZI>::Ptr full(new pcl::PointCloud<pcl::PointXYZI>());
        if (pcl::io::loadPCDFile<pcl::PointXYZI>(map_pcd_, *full) == 0)
        {
          pcl::VoxelGrid<pcl::PointXYZI> vg;
          vg.setLeafSize(0.15f, 0.15f, 0.15f);
          vg.setInputCloud(full);
          vg.filter(*gmap);
          pcl::io::savePCDFileBinary(gicp_map_path, *gmap);
          RCLCPP_INFO(get_logger(), "Dense GICP map: %zu points (cached)", gmap->size());
          refiner_.setMapCloud(gmap);
        }
        else
        {
          refiner_.setMapCloud(map);
        }
      }
      else
      {
        refiner_.setMapCloud(map);
      }
    }
    // GICP 由粗到精: 粗阶段(对应距离>=1m)用这张 0.3m 体素图, 细阶段用上面的 0.15m 密图
    refiner_.setCoarseMapCloud(map);
    RCLCPP_INFO(get_logger(),
      "GICP coarse map (0.3m): %zu points; dense map for fine stages set above",
      map->size());
    RCLCPP_INFO(get_logger(), "Map for BBS3D(coarse): %zu points", map->size());

    if (bb_enable_)
    {
      RCLCPP_INFO(get_logger(),
        "Building BBS3D hierarchical voxel map (min_level_res=%.2f, max_level=%d)...",
        bbs3d_min_level_res_, bbs3d_max_level_);
      // 地图降采样后转 Eigen::Vector3f
      pcl::PointCloud<pcl::PointXYZI>::Ptr tar(new pcl::PointCloud<pcl::PointXYZI>(*map));
      if (bbs3d_tar_leaf_ > 0.0)
      {
        pcl::VoxelGrid<pcl::PointXYZI> vg;
        vg.setLeafSize(bbs3d_tar_leaf_, bbs3d_tar_leaf_, bbs3d_tar_leaf_);
        vg.setInputCloud(tar);
        pcl::PointCloud<pcl::PointXYZI> ds;
        vg.filter(ds);
        *tar = ds;
      }
      std::vector<Eigen::Vector3f> tar_pts;
      tar_pts.reserve(tar->size());
      for (const auto &p : tar->points) tar_pts.emplace_back(p.x, p.y, p.z);

      bbs3d_.setTarget(tar_pts, static_cast<float>(bbs3d_min_level_res_), bbs3d_max_level_);
      bbs3d_.setAngularRange(-M_PI, M_PI, static_cast<float>(bbs3d_rp_range_));

      const float z_min = static_cast<float>(bbs3d_ground_z_ - bbs3d_z_range_);
      const float z_max = static_cast<float>(bbs3d_ground_z_ + bbs3d_z_range_);
      full_search_min_ = Eigen::Vector3f::Constant(std::numeric_limits<float>::max());
      full_search_max_ = Eigen::Vector3f::Constant(std::numeric_limits<float>::lowest());
      for (const auto &p : tar_pts)
      {
        full_search_min_ = full_search_min_.cwiseMin(p);
        full_search_max_ = full_search_max_.cwiseMax(p);
      }
      full_search_min_.z() = z_min;
      full_search_max_.z() = z_max;

      map_bounds_ = clip_search_to_grid_map_
        ? loadMapBoundsFromYaml(grid_map_yaml_) : MapBounds2D{};
      if (map_bounds_.valid)
      {
        const float margin = static_cast<float>(bbs3d_search_margin_);
        full_search_min_.x() = static_cast<float>(map_bounds_.min_x - margin);
        full_search_min_.y() = static_cast<float>(map_bounds_.min_y - margin);
        full_search_max_.x() = static_cast<float>(map_bounds_.max_x + margin);
        full_search_max_.y() = static_cast<float>(map_bounds_.max_y + margin);
        RCLCPP_INFO(get_logger(),
          "BBS3D full search clipped to 2D map [%s]: x[%.1f, %.1f] y[%.1f, %.1f]",
          grid_map_yaml_.c_str(),
          full_search_min_.x(), full_search_max_.x(),
          full_search_min_.y(), full_search_max_.y());
      }
      else if (clip_search_to_grid_map_ && !grid_map_yaml_.empty())
      {
        RCLCPP_WARN(get_logger(),
          "Failed to load grid_map_yaml '%s'; using PCD AABB for search",
          grid_map_yaml_.c_str());
      }

      buildGroundModel(tar_pts);

      setBbs3dFullSearch();
      bbs3d_.setScoreThreshold(static_cast<float>(bbs3d_score_thresh_));
      bbs3d_.setTimeout(bbs3d_timeout_msec_);
      RCLCPP_INFO(get_logger(),
        "BBS3D(CPU) ready (%zu pts, z=[%.1f,%.1f]). mode=%s center=[%.1f,%.1f] "
        "ring_step=%.1fm ground_filter=%s",
        tar_pts.size(), z_min, z_max, search_mode_.c_str(),
        search_center_.size() > 0 ? search_center_[0] : 0.0,
        search_center_.size() > 1 ? search_center_[1] : 0.0,
        ring_step_, (ground_filter_enable_ && ground_valid_) ? "on" : "off");
    }

    if (!db_.load(db_dir_, sc_, get_logger()))
    {
      RCLCPP_WARN(get_logger(), "Keyframe DB empty. Will use position+yaw grid search only.");
    }

    pub_init_ = create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>("/initialpose", 10);
    sub_lidar_ = create_subscription<livox_ros_driver2::msg::CustomMsg>(
      "/livox/lidar", rclcpp::SensorDataQoS(),
      std::bind(&GlobalRelocNode::lidarCallback, this, std::placeholders::_1));
    sub_odom_ = create_subscription<nav_msgs::msg::Odometry>(
      "/Odometry", 10, std::bind(&GlobalRelocNode::odomCallback, this, std::placeholders::_1));
    sub_registered_ = create_subscription<sensor_msgs::msg::PointCloud2>(
      "/cloud_registered", rclcpp::SensorDataQoS(),
      std::bind(&GlobalRelocNode::registeredCallback, this, std::placeholders::_1));

    timer_ = create_wall_timer(
      std::chrono::milliseconds(500),
      std::bind(&GlobalRelocNode::tryRelocalize, this));
    if (verify_period_sec_ > 0.0)
    {
      verify_timer_ = create_wall_timer(
        std::chrono::milliseconds(static_cast<int>(verify_period_sec_ * 1000)),
        std::bind(&GlobalRelocNode::verifyTracking, this));
    }

    RCLCPP_INFO(get_logger(), "Global relocalization ready. Waiting for LiDAR scans...");
  }

private:
  void lidarCallback(const livox_ros_driver2::msg::CustomMsg::SharedPtr msg)
  {
    pcl::PointCloud<pcl::PointXYZI> frame;
    frame.reserve(msg->point_num);
    for (uint32_t i = 0; i < msg->point_num; ++i)
    {
      const auto &p = msg->points[i];
      if (p.x * p.x + p.y * p.y + p.z * p.z < 0.25f) continue;
      pcl::PointXYZI pt;
      pt.x = p.x;
      pt.y = p.y;
      pt.z = p.z;
      pt.intensity = p.reflectivity;
      frame.push_back(pt);
    }
    std::lock_guard<std::mutex> lk(mtx_);
    // 滚动窗口: 只保留最近 N 帧, 避免旋转/移动时把不同朝向的帧混叠成垃圾
    recent_frames_.push_back(frame);
    while (static_cast<int>(recent_frames_.size()) > max_accum_frames_)
    {
      recent_frames_.pop_front();
    }
    size_t total = 0;
    for (const auto &f : recent_frames_) total += f.size();
    has_scan_ = total > 500;
  }

  void odomCallback(const nav_msgs::msg::Odometry::SharedPtr msg)
  {
    last_odom_time_ = now();
    if (!continuity_enable_) return;

    const auto &p = msg->pose.pose.position;
    const auto &q = msg->pose.pose.orientation;
    const double siny_cosp = 2.0 * (q.w * q.z + q.x * q.y);
    const double cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z);
    const double yaw = std::atan2(siny_cosp, cosy_cosp);
    continuity_anchor_ = Eigen::Isometry3d::Identity();
    continuity_anchor_.translation() = Eigen::Vector3d(p.x, p.y, p.z);
    continuity_anchor_.linear() =
      Eigen::AngleAxisd(yaw, Eigen::Vector3d::UnitZ()).toRotationMatrix();
    has_continuity_anchor_ = true;
  }

  bool poseMatchesContinuity(const Eigen::Isometry3d &pose, bool log_reject) const
  {
    if (!continuity_enable_ || !has_continuity_anchor_) return true;
    const double dx = pose.translation().x() - continuity_anchor_.translation().x();
    const double dy = pose.translation().y() - continuity_anchor_.translation().y();
    const double distance = std::hypot(dx, dy);
    const double yaw_delta = std::abs(
      normalizeAngle(poseYaw(pose) - poseYaw(continuity_anchor_)));
    const double max_yaw = continuity_max_yaw_deg_ * M_PI / 180.0;
    if (distance <= continuity_max_translation_ && yaw_delta <= max_yaw) return true;
    if (log_reject)
    {
      RCLCPP_WARN(get_logger(),
        "Reject reloc branch jump: candidate [%.2f %.2f yaw=%.1fdeg] vs last-good "
        "[%.2f %.2f yaw=%.1fdeg], delta=%.2fm/%.1fdeg limits=%.2fm/%.1fdeg",
        pose.translation().x(), pose.translation().y(), poseYaw(pose) * 180.0 / M_PI,
        continuity_anchor_.translation().x(), continuity_anchor_.translation().y(),
        poseYaw(continuity_anchor_) * 180.0 / M_PI,
        distance, yaw_delta * 180.0 / M_PI,
        continuity_max_translation_, continuity_max_yaw_deg_);
    }
    return false;
  }

  void registeredCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
  {
    std::lock_guard<std::mutex> lk(reg_mtx_);
    pcl::fromROSMsg(*msg, latest_registered_);
    has_registered_ = latest_registered_.size() > 100;
  }

  pcl::PointCloud<pcl::PointXYZI> getDownsampledScan()
  {
    pcl::PointCloud<pcl::PointXYZI> scan;
    {
      std::lock_guard<std::mutex> lk(mtx_);
      for (const auto &f : recent_frames_) scan += f;
    }
    if (scan.empty()) return scan;
    pcl::VoxelGrid<pcl::PointXYZI> vg;
    vg.setLeafSize(0.3f, 0.3f, 0.3f);
    vg.setInputCloud(scan.makeShared());
    pcl::PointCloud<pcl::PointXYZI> ds;
    vg.filter(ds);
    return ds;
  }

  // 用 FAST-LIO 发布的 /cloud_registered(已在 map 系)校验当前位姿是否全局一致
  void verifyTracking()
  {
    if (verify_period_sec_ <= 0.0) return;
    if (!reloc_done_ || !refiner_.hasMap()) return;

    // A good score from latest_registered_ is meaningful only while FAST-LIO
    // is still publishing odometry.  When FAST-LIO loses tracking it stops
    // both /Odometry and /cloud_registered; without this freshness check the
    // last registered cloud is scored forever and a dead localization chain
    // is incorrectly reported as healthy.
    const double odom_age_sec =
      last_odom_time_.nanoseconds() > 0
        ? (now() - last_odom_time_).seconds()
        : std::numeric_limits<double>::infinity();
    if (odom_age_sec > odom_lost_timeout_)
    {
      RCLCPP_WARN(get_logger(),
        "Odometry stale for %.2fs (> %.2fs) -> re-triggering global relocalization",
        odom_age_sec, odom_lost_timeout_);
      reloc_done_ = false;
      verify_fail_count_ = 0;
      {
        std::lock_guard<std::mutex> lk(reg_mtx_);
        latest_registered_.clear();
        has_registered_ = false;
      }
      {
        std::lock_guard<std::mutex> lk(mtx_);
        recent_frames_.clear();
        has_scan_ = false;
      }
      return;
    }

    pcl::PointCloud<pcl::PointXYZI> reg;
    {
      std::lock_guard<std::mutex> lk(reg_mtx_);
      if (!has_registered_) return;
      reg = latest_registered_;
    }
    pcl::VoxelGrid<pcl::PointXYZI> vg;
    vg.setLeafSize(0.4f, 0.4f, 0.4f);
    vg.setInputCloud(reg.makeShared());
    pcl::PointCloud<pcl::PointXYZI> reg_ds;
    vg.filter(reg_ds);

    const double score = refiner_.scoreCloudInMap(reg_ds);
    if (score >= verify_min_score_)
    {
      verify_fail_count_ = 0;
      RCLCPP_INFO_THROTTLE(get_logger(), *get_clock(), 5000,
        "Tracking healthy: map-consistency=%.2f", score);
      return;
    }

    verify_fail_count_++;
    RCLCPP_WARN(get_logger(),
      "Tracking INCONSISTENT with map: score=%.2f (%d/%d). Likely wrong pose.",
      score, verify_fail_count_, verify_fail_limit_);

    if (verify_fail_count_ >= verify_fail_limit_)
    {
      RCLCPP_WARN(get_logger(),
        "Pose lost/kidnapped -> re-triggering global relocalization");
      reloc_done_ = false;
      verify_fail_count_ = 0;
      std::lock_guard<std::mutex> lk(mtx_);
      recent_frames_.clear();
      has_scan_ = false;
    }
  }

  bool poseInsideMapBounds(const Eigen::Isometry3d &pose) const
  {
    const double x = pose.translation().x();
    const double y = pose.translation().y();
    return x >= map_bounds_.min_x && x <= map_bounds_.max_x &&
           y >= map_bounds_.min_y && y <= map_bounds_.max_y;
  }

  void setBbs3dFullSearch()
  {
    bbs3d_.setTranslationSearchRange(full_search_min_, full_search_max_);
  }

  void setBbs3dSearchBox(double cx, double cy, double radius_xy)
  {
    const float r = static_cast<float>(radius_xy);
    Eigen::Vector3f smin(
      std::max(full_search_min_.x(), static_cast<float>(cx) - r),
      std::max(full_search_min_.y(), static_cast<float>(cy) - r),
      full_search_min_.z());
    Eigen::Vector3f smax(
      std::min(full_search_max_.x(), static_cast<float>(cx) + r),
      std::min(full_search_max_.y(), static_cast<float>(cy) + r),
      full_search_max_.z());
    bbs3d_.setTranslationSearchRange(smin, smax);
  }

  void setBbs3dSearchBoxMinMax(double xmin, double ymin, double xmax, double ymax)
  {
    Eigen::Vector3f smin(static_cast<float>(xmin), static_cast<float>(ymin),
                         full_search_min_.z());
    Eigen::Vector3f smax(static_cast<float>(xmax), static_cast<float>(ymax),
                         full_search_max_.z());
    bbs3d_.setTranslationSearchRange(smin, smax);
  }

  // ---- 地面模型: 2D 粗栅格, 标记哪些格子有地面点 ----
  void buildGroundModel(const std::vector<Eigen::Vector3f> &pts)
  {
    ground_valid_ = false;
    if (!ground_filter_enable_ || pts.empty()) return;

    const double zlo = bbs3d_ground_z_ + ground_z_min_rel_;
    const double zhi = bbs3d_ground_z_ + ground_z_max_rel_;
    float xmin = std::numeric_limits<float>::max();
    float ymin = std::numeric_limits<float>::max();
    float xmax = std::numeric_limits<float>::lowest();
    float ymax = std::numeric_limits<float>::lowest();
    for (const auto &p : pts)
    {
      if (p.z() < zlo || p.z() > zhi) continue;
      xmin = std::min(xmin, p.x()); ymin = std::min(ymin, p.y());
      xmax = std::max(xmax, p.x()); ymax = std::max(ymax, p.y());
    }
    if (xmin > xmax || ymin > ymax)
    {
      RCLCPP_WARN(get_logger(),
        "Ground model: no points in z[%.2f,%.2f]; ground filter disabled.", zlo, zhi);
      return;
    }

    gm_res_ = std::max(0.2, ground_cell_);
    gm_origin_x_ = xmin;
    gm_origin_y_ = ymin;
    gm_w_ = static_cast<int>((xmax - xmin) / gm_res_) + 1;
    gm_h_ = static_cast<int>((ymax - ymin) / gm_res_) + 1;
    std::vector<int> cnt(static_cast<size_t>(gm_w_) * gm_h_, 0);
    for (const auto &p : pts)
    {
      if (p.z() < zlo || p.z() > zhi) continue;
      int ix = static_cast<int>((p.x() - gm_origin_x_) / gm_res_);
      int iy = static_cast<int>((p.y() - gm_origin_y_) / gm_res_);
      if (ix < 0 || ix >= gm_w_ || iy < 0 || iy >= gm_h_) continue;
      cnt[static_cast<size_t>(iy) * gm_w_ + ix]++;
    }
    std::vector<uint8_t> raw(cnt.size(), 0);
    size_t n_ground = 0;
    for (size_t i = 0; i < cnt.size(); ++i)
    {
      if (cnt[i] >= ground_min_pts_) { raw[i] = 1; ++n_ground; }
    }
    // 膨胀(补地面空洞: 盲区/反光/遮挡)
    gm_.assign(cnt.size(), 0);
    const int d = std::max(0, ground_dilate_);
    for (int y = 0; y < gm_h_; ++y)
      for (int x = 0; x < gm_w_; ++x)
      {
        if (!raw[static_cast<size_t>(y) * gm_w_ + x]) continue;
        for (int dy = -d; dy <= d; ++dy)
          for (int dx = -d; dx <= d; ++dx)
          {
            int nx = x + dx, ny = y + dy;
            if (nx < 0 || nx >= gm_w_ || ny < 0 || ny >= gm_h_) continue;
            gm_[static_cast<size_t>(ny) * gm_w_ + nx] = 1;
          }
      }
    ground_min_ = Eigen::Vector2f(xmin, ymin);
    ground_max_ = Eigen::Vector2f(xmax, ymax);
    ground_valid_ = true;
    RCLCPP_INFO(get_logger(),
      "Ground model: %dx%d @%.1fm, %zu ground cells, extent x[%.1f,%.1f] y[%.1f,%.1f]",
      gm_w_, gm_h_, gm_res_, n_ground, xmin, xmax, ymin, ymax);
  }

  bool boxHasGround(double xmin, double ymin, double xmax, double ymax) const
  {
    if (!ground_valid_) return true;  // 无地面模型时不约束
    int ix0 = std::max(0, static_cast<int>((xmin - gm_origin_x_) / gm_res_));
    int iy0 = std::max(0, static_cast<int>((ymin - gm_origin_y_) / gm_res_));
    int ix1 = std::min(gm_w_ - 1, static_cast<int>((xmax - gm_origin_x_) / gm_res_));
    int iy1 = std::min(gm_h_ - 1, static_cast<int>((ymax - gm_origin_y_) / gm_res_));
    for (int y = iy0; y <= iy1; ++y)
      for (int x = ix0; x <= ix1; ++x)
        if (gm_[static_cast<size_t>(y) * gm_w_ + x]) return true;
    return false;
  }

  // 搜索区域 = 全图框 ∩ 地面外包(若有地面模型)
  void regionBounds(double &xmin, double &ymin, double &xmax, double &ymax) const
  {
    xmin = full_search_min_.x(); ymin = full_search_min_.y();
    xmax = full_search_max_.x(); ymax = full_search_max_.y();
    if (ground_valid_)
    {
      xmin = std::max(xmin, static_cast<double>(ground_min_.x()));
      ymin = std::max(ymin, static_cast<double>(ground_min_.y()));
      xmax = std::min(xmax, static_cast<double>(ground_max_.x()));
      ymax = std::min(ymax, static_cast<double>(ground_max_.y()));
    }
  }

  // 从中心一圈圈往外扩, 只搜有地面的环带
  bool relocByExpandFromCenter(
    const std::vector<Eigen::Vector3f> &src,
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const std::vector<CandidateMatch> &sc_candidates,
    RefineResult &best, std::string &win_stage)
  {
    double rx0, ry0, rx1, ry1;
    regionBounds(rx0, ry0, rx1, ry1);
    double cx = search_center_.size() > 0 ? search_center_[0] : 0.0;
    double cy = search_center_.size() > 1 ? search_center_[1] : 0.0;
    if (use_sc_center_ && !sc_candidates.empty() &&
        sc_candidates[0].sc_distance <= sc_center_max_dist_)
    {
      cx = sc_candidates[0].pose.translation().x();
      cy = sc_candidates[0].pose.translation().y();
      RCLCPP_INFO(get_logger(),
        "Search center -> SC kf=%d (%.2f,%.2f) dist=%.3f",
        sc_candidates[0].keyframe_id, cx, cy, sc_candidates[0].sc_distance);
    }

    // SC 置信时先在 hint 附近小范围+窄 yaw 搜一轮, 避免 ring#1 假阳性。
    // 但正反歧义时跳过这一轮: 窄 yaw 会被 SC(可能翻转的)hint 朝向带偏, 必须全 yaw。
    if (!yaw_ambiguous_ && use_sc_center_ && !sc_candidates.empty() &&
        sc_candidates[0].sc_distance <= sc_center_max_dist_)
    {
      const auto hint = scHintPose(sc_candidates[0]);
      const double hint_yaw = poseYaw(hint);
      const double yaw_half = sc_confident_yaw_gate_deg_ * M_PI / 180.0;
      bbs3d_.setAngularRange(
        static_cast<float>(hint_yaw - yaw_half),
        static_cast<float>(hint_yaw + yaw_half),
        static_cast<float>(bbs3d_rp_range_));
      setBbs3dSearchBox(cx, cy, sc_tight_radius_);
      win_stage = "SC-tight r=" + std::to_string(static_cast<int>(sc_tight_radius_)) + "m";
      if (runBbs3dGicp(src, scan, win_stage, sc_candidates, best))
      {
        bbs3d_.setAngularRange(
          static_cast<float>(-M_PI), static_cast<float>(M_PI),
          static_cast<float>(bbs3d_rp_range_));
        return true;
      }
      bbs3d_.setAngularRange(
        static_cast<float>(-M_PI), static_cast<float>(M_PI),
        static_cast<float>(bbs3d_rp_range_));
    }

    // 覆盖整个区域所需最大半径(中心到四角的最大值)
    double Rmax = 0.0;
    for (double px : {rx0, rx1})
      for (double py : {ry0, ry1})
        Rmax = std::max(Rmax, std::hypot(px - cx, py - cy));
    if (ring_max_radius_ > 0.0) Rmax = std::min(Rmax, ring_max_radius_);

    double prev_r = 0.0;
    int ring_idx = 0;
    for (double r = ring_step_; ; r += ring_step_)
    {
      const double rr = std::min(r, Rmax);
      // 外框(裁剪到区域)
      const double ox0 = std::max(rx0, cx - rr), oy0 = std::max(ry0, cy - rr);
      const double ox1 = std::min(rx1, cx + rr), oy1 = std::min(ry1, cy + rr);
      // 内框(上一圈, 裁剪到区域)
      const double ix0 = std::max(rx0, cx - prev_r), iy0 = std::max(ry0, cy - prev_r);
      const double ix1 = std::min(rx1, cx + prev_r), iy1 = std::min(ry1, cy + prev_r);

      // 环带 = 外框减内框, 分解为最多 4 条矩形
      std::vector<std::array<double, 4>> strips;
      if (prev_r <= 0.0)
      {
        strips.push_back({ox0, oy0, ox1, oy1});
      }
      else
      {
        if (oy0 < iy0) strips.push_back({ox0, oy0, ox1, iy0});  // 下
        if (oy1 > iy1) strips.push_back({ox0, iy1, ox1, oy1});  // 上
        if (ox0 < ix0) strips.push_back({ox0, iy0, ix0, iy1});  // 左
        if (ox1 > ix1) strips.push_back({ix1, iy0, ox1, iy1});  // 右
      }

      ++ring_idx;
      for (const auto &s : strips)
      {
        if (s[2] - s[0] < 1e-3 || s[3] - s[1] < 1e-3) continue;
        if (ground_filter_enable_ && !boxHasGround(s[0], s[1], s[2], s[3])) continue;
        setBbs3dSearchBoxMinMax(s[0], s[1], s[2], s[3]);
        win_stage = "ring#" + std::to_string(ring_idx) + " r=" +
          std::to_string(static_cast<int>(rr)) + "m";
        if (runBbs3dGicp(src, scan, win_stage, sc_candidates, best)) return true;
      }

      prev_r = rr;
      if (rr >= Rmax) break;
    }
    return false;
  }

  bool relocBySCCandidates(
    const std::vector<Eigen::Vector3f> &src,
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const std::vector<CandidateMatch> &sc_candidates,
    RefineResult &best, std::string &win_stage)
  {
    if (sc_candidates.empty()) return false;
    for (const auto &c : sc_candidates)
    {
      const double cx = c.pose.translation().x();
      const double cy = c.pose.translation().y();
      setBbs3dSearchBox(cx, cy, candidate_radius_);
      win_stage = "SC#" + std::to_string(c.keyframe_id);
      if (runBbs3dGicp(src, scan, win_stage, sc_candidates, best)) return true;
    }
    const double cx = sc_candidates[0].pose.translation().x();
    const double cy = sc_candidates[0].pose.translation().y();
    for (double r : expand_radii_)
    {
      if (r <= candidate_radius_) continue;
      setBbs3dSearchBox(cx, cy, r);
      win_stage = "SC-expand r=" + std::to_string(static_cast<int>(r)) + "m";
      if (runBbs3dGicp(src, scan, win_stage, sc_candidates, best)) return true;
    }
    return false;
  }

  std::vector<Eigen::Vector3f> prepareBbs3dSource(
    const pcl::PointCloud<pcl::PointXYZI> &scan) const
  {
    std::vector<Eigen::Vector3f> src;
    src.reserve(scan.size());
    const double rmin2 = bbs3d_min_scan_ * bbs3d_min_scan_;
    const double rmax2 = bbs3d_max_scan_ * bbs3d_max_scan_;
    pcl::PointCloud<pcl::PointXYZI>::Ptr s(new pcl::PointCloud<pcl::PointXYZI>(scan));
    if (bbs3d_src_leaf_ > 0.0)
    {
      pcl::VoxelGrid<pcl::PointXYZI> vg;
      vg.setLeafSize(bbs3d_src_leaf_, bbs3d_src_leaf_, bbs3d_src_leaf_);
      vg.setInputCloud(s);
      pcl::PointCloud<pcl::PointXYZI> ds;
      vg.filter(ds);
      *s = ds;
    }
    for (const auto &p : s->points)
    {
      const double r2 = p.x * p.x + p.y * p.y + p.z * p.z;
      if (r2 < rmin2 || r2 > rmax2) continue;
      src.emplace_back(p.x, p.y, p.z);
    }
    return src;
  }

  bool validateRelocResult(
    const RefineResult &result,
    const std::vector<CandidateMatch> &sc_candidates,
    bool skip_yaw_gate = false) const
  {
    if (result.fitness < min_accept_fitness_)
    {
      RCLCPP_WARN(get_logger(),
        "Reject reloc: GICP fitness %.3f < %.3f (likely false positive)",
        result.fitness, min_accept_fitness_);
      return false;
    }
    // 高拟合度只放宽 xy 距离门(几何对齐强于稀疏 SC 提示, 解决"离开原点就失败"),
    // 但绝不跳过朝向判断——翻转解同样能刷出 0.99 高拟合度, 当年把 yaw 门一起
    // bypass 正是这次"点云匹配但朝向反"的根因。
    const bool bypass_xy = result.fitness >= high_accept_fitness_;
    if (sc_gate_enable_ && !sc_candidates.empty())
    {
      const bool sc_confident =
        sc_candidates[0].sc_distance <= sc_center_max_dist_;
      const double max_dist =
        sc_confident ? sc_confident_xy_gate_ : sc_gate_max_dist_;
      const auto hint_pose = scHintPose(sc_candidates[0]);
      const auto &hint = hint_pose.translation();
      const double dx = result.pose.translation().x() - hint.x();
      const double dy = result.pose.translation().y() - hint.y();
      const double dist = std::hypot(dx, dy);
      if (dist > max_dist)
      {
        if (bypass_xy)
        {
          RCLCPP_INFO(get_logger(),
            "Accept xy %.1fm > limit %.1fm by high GICP fitness %.3f (bypass xy gate only)",
            dist, max_dist, result.fitness);
        }
        else
        {
          RCLCPP_WARN(get_logger(),
            "Reject reloc: pose (%.2f,%.2f) is %.1fm from SC hint (%.2f,%.2f) limit=%.1f",
            result.pose.translation().x(), result.pose.translation().y(),
            dist, hint.x(), hint.y(), max_dist);
          return false;
        }
      }
      // 朝向门: 调用方已自主全 yaw 搜索(skip_yaw_gate)或本轮判定正反歧义
      // (yaw_ambiguous_, SC hint yaw 不可信)时不用 SC yaw 当裁判。
      if (!skip_yaw_gate && !yaw_ambiguous_ && sc_confident &&
          sc_confident_yaw_gate_deg_ > 0.0)
      {
        const double dyaw = std::abs(
          normalizeAngle(poseYaw(result.pose) - poseYaw(hint_pose)));
        const double max_yaw = sc_confident_yaw_gate_deg_ * M_PI / 180.0;
        if (dyaw > max_yaw)
        {
          RCLCPP_WARN(get_logger(),
            "Reject reloc: yaw delta %.1f° > %.1f° (SC confident)",
            dyaw * 180.0 / M_PI, sc_confident_yaw_gate_deg_);
          return false;
        }
      }
    }
    return true;
  }

  bool tryScDirectReloc(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const std::vector<CandidateMatch> &sc_candidates,
    RefineResult &best, std::string &win_stage)
  {
    if (!sc_direct_pose_ || sc_candidates.empty() ||
        sc_candidates[0].sc_distance > sc_center_max_dist_)
      return false;

    const auto hint = scHintPose(sc_candidates[0]);
    const double score = refiner_.scorePose(scan, hint);
    RCLCPP_INFO(get_logger(),
      "SC-direct kf=%d: score=%.3f pos[%.2f %.2f] sc_dist=%.3f",
      sc_candidates[0].keyframe_id, score,
      hint.translation().x(), hint.translation().y(),
      sc_candidates[0].sc_distance);
    if (score < sc_direct_min_score_) return false;

    best = RefineResult{true, score, hint};
    win_stage = "SC-direct#" + std::to_string(sc_candidates[0].keyframe_id);
    RCLCPP_INFO(get_logger(), "SC-direct [%s] ACCEPTED", win_stage.c_str());
    return true;
  }

  bool tryScGicpReloc(
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const std::vector<CandidateMatch> &sc_candidates,
    RefineResult &best, std::string &win_stage)
  {
    // 始终对 top_k 候选做 SC+GICP(含全 yaw 搜索), 不因 sc_distance 略超阈值就
    // 漏到 BBS3D(走廊假阳性/朝向锁错)。距离门只用于 sc_direct / 搜索中心切换。
    if (!sc_gicp_first_ || sc_candidates.empty())
      return false;

    for (const auto &c : sc_candidates)
    {
      // SC 的 yaw 来自描述子列偏移, 在走廊/对称环境常估反, 单一 yaw + 局部 GICP
      // 跳不出错误朝向盆地(现象: 位置对、狗头朝向错)。这里在候选 xy 上做全 yaw
      // 网格搜索, 选重合度最高的朝向作为另一路初值, 破除 yaw aliasing。
      const Eigen::Vector3d pos = c.pose.translation();
      RefineResult yaw_best =
        refiner_.searchYawGrid(scan, pos, pos.z(), yaw_search_steps_, 0.0);

      // 两路完整 GICP 精修(对应距离大, 容忍初始误差): SC 自带 yaw vs 网格最佳 yaw
      RefineResult g_sc = refiner_.refineGICP(scan, scHintPose(c));
      RefineResult g_grid = refiner_.refineGICP(scan, yaw_best.pose);

      // 正反歧义检测: 两路都收敛到可接受拟合度, 且朝向相差≈180°, 且分数接近。
      // 这正是长走廊/对称环境的陷阱——翻转解几何重合反而更高(0.996 > 0.834)。
      // 此时绝不能用"谁分高选谁"(会选到翻转解), 必须交给 BBS3D 全 yaw 定夺。
      const bool both_ok =
        g_sc.fitness >= min_accept_fitness_ && g_grid.fitness >= min_accept_fitness_;
      const double yaw_diff_deg =
        std::abs(normalizeAngle(poseYaw(g_sc.pose) - poseYaw(g_grid.pose))) * 180.0 / M_PI;
      const bool fitness_close =
        std::abs(g_sc.fitness - g_grid.fitness) < yaw_ambiguity_margin_;
      if (both_ok && yaw_diff_deg > yaw_ambiguity_deg_ && fitness_close)
      {
        yaw_ambiguous_ = true;
        RCLCPP_WARN(get_logger(),
          "SC+GICP kf=%d YAW-AMBIGUOUS: sc_yaw=%.1f°(fit %.3f) vs grid_yaw=%.1f°(fit %.3f) "
          "diff=%.0f° -> defer to BBS3D (refuse high-fitness flipped pose)",
          c.keyframe_id, poseYaw(g_sc.pose) * 180.0 / M_PI, g_sc.fitness,
          poseYaw(g_grid.pose) * 180.0 / M_PI, g_grid.fitness, yaw_diff_deg);
        continue;
      }

      RefineResult gicp = (g_grid.fitness >= g_sc.fitness) ? g_grid : g_sc;
      if (gicp.fitness > best.fitness) best = gicp;
      RCLCPP_INFO(get_logger(),
        "SC+GICP kf=%d: fitness=%.3f (sc_yaw=%.3f grid_yaw=%.3f) pos[%.2f %.2f] sc_dist=%.3f",
        c.keyframe_id, gicp.fitness, g_sc.fitness, g_grid.fitness,
        gicp.pose.translation().x(), gicp.pose.translation().y(),
        c.sc_distance);
      // 已自主全 yaw 搜索且无正反歧义, 跳过 SC yaw 门(SC hint yaw 在对称环境可能偏)
      if (validateRelocResult(gicp, sc_candidates, /*skip_yaw_gate=*/true))
      {
        best = gicp;
        win_stage = "SC-GICP#" + std::to_string(c.keyframe_id);
        RCLCPP_INFO(get_logger(), "SC+GICP [%s] ACCEPTED", win_stage.c_str());
        return true;
      }
    }
    return false;
  }

  bool runBbs3dGicp(
    const std::vector<Eigen::Vector3f> &src,
    const pcl::PointCloud<pcl::PointXYZI> &scan,
    const std::string &stage,
    const std::vector<CandidateMatch> &sc_candidates,
    RefineResult &out_best)
  {
    BBS3DOutput o = bbs3d_.localize(src);
    if (!o.localized)
    {
      RCLCPP_DEBUG(get_logger(),
        "BBS3D [%s] miss: score=%d (%.0f%%)%s %.0fms",
        stage.c_str(), o.score, o.score_pct * 100.0,
        o.timed_out ? " timeout" : "", o.time_msec);
      return false;
    }
    Eigen::Isometry3d guess = Eigen::Isometry3d::Identity();
    guess.matrix() = o.pose.cast<double>();
    RefineResult gicp = refiner_.refineGICP(scan, guess);
    out_best = gicp.fitness > 0.0 ? gicp : RefineResult{true, o.score_pct, guess};
    RCLCPP_INFO(get_logger(),
      "BBS3D [%s] candidate: score=%d (%.0f%%) %.0fms -> GICP %.3f pos[%.2f %.2f]",
      stage.c_str(), o.score, o.score_pct * 100.0, o.time_msec, out_best.fitness,
      out_best.pose.translation().x(), out_best.pose.translation().y());
    if (!validateRelocResult(out_best, sc_candidates))
    {
      return false;
    }
    RCLCPP_INFO(get_logger(), "BBS3D [%s] ACCEPTED", stage.c_str());
    return true;
  }

  void publishInitialPose(const Eigen::Isometry3d &pose)
  {
    geometry_msgs::msg::PoseWithCovarianceStamped msg;
    msg.header.stamp = now();
    msg.header.frame_id = "map";
    msg.pose.pose.position.x = pose.translation().x();
    msg.pose.pose.position.y = pose.translation().y();
    msg.pose.pose.position.z = pose.translation().z();
    Eigen::Quaterniond q(pose.rotation());
    msg.pose.pose.orientation.x = q.x();
    msg.pose.pose.orientation.y = q.y();
    msg.pose.pose.orientation.z = q.z();
    msg.pose.pose.orientation.w = q.w();
    for (int i = 0; i < 36; ++i) msg.pose.covariance[i] = 0.0;
    msg.pose.covariance[0] = 0.25;
    msg.pose.covariance[7] = 0.25;
    msg.pose.covariance[35] = 0.1;
    pub_init_->publish(msg);
    RCLCPP_INFO(get_logger(),
      "Published /initialpose: [%.2f %.2f %.2f] yaw=%.1f° fitness=%.2f",
      pose.translation().x(), pose.translation().y(), pose.translation().z(),
      std::atan2(2.0 * (q.w() * q.z() + q.x() * q.y()),
        1.0 - 2.0 * (q.y() * q.y() + q.z() * q.z())) * 180.0 / M_PI,
      last_fitness_);

    // 对称性诊断: 比较"发布朝向"与"绕 z 翻转 180°"的几何重合率。
    // 两者接近 => 环境对称, 纯几何打分无法区分正反; 差距大 => 翻转可被排除。
    {
      auto scan = getDownsampledScan();
      if (!scan.empty() && refiner_.hasMap())
      {
        Eigen::Isometry3d flipped = pose;
        flipped.linear() =
          pose.linear() *
          Eigen::AngleAxisd(M_PI, Eigen::Vector3d::UnitZ()).toRotationMatrix();
        const double f0 = refiner_.scorePose(scan, pose);
        const double f180 = refiner_.scorePose(scan, flipped);
        RCLCPP_WARN(get_logger(),
          "[symmetry-check] fitness(published)=%.3f vs fitness(+180deg)=%.3f "
          "=> %s",
          f0, f180,
          (std::abs(f0 - f180) < 0.08)
            ? "AMBIGUOUS (geometric symmetry, scores tie)"
            : (f0 >= f180 ? "published is uniquely better"
                          : "FLIPPED is better -> wrong basin chosen"));
      }
    }
  }

  void tryRelocalize()
  {
    if (!has_scan_) return;
    // 成功后不再重定位; 失配/绑架由 verifyTracking() 监控并重置 reloc_done_
    if (reloc_done_) return;

    yaw_ambiguous_ = false;  // 每轮重新判定正反歧义

    const auto scan = getDownsampledScan();
    if (scan.size() < 300) return;

    Eigen::MatrixXd query_desc = sc_.makeDescriptor(scan);
    RefineResult best;
    best.fitness = 0.0;

    std::vector<CandidateMatch> sc_candidates;
    if (!db_.empty())
    {
      sc_candidates = db_.query(query_desc, top_k_, sc_);
      if (!sc_candidates.empty())
      {
        RCLCPP_INFO_THROTTLE(get_logger(), *get_clock(), 3000,
          "SC top-1 hint: kf=%d pos[%.2f %.2f] dist=%.3f",
          sc_candidates[0].keyframe_id,
          sc_candidates[0].pose.translation().x(),
          sc_candidates[0].pose.translation().y(),
          sc_candidates[0].sc_distance);
      }
    }

    bool accepted_by_bbs3d = false;
    std::string win_stage;
    bool found = false;

    // Fast path for recovery after a short odometry outage.  Starting GICP
    // from the last trustworthy map pose preserves the physical branch and is
    // both faster and more reliable than launching a fresh full-map search.
    if (continuity_enable_ && has_continuity_anchor_)
    {
      RefineResult local = refiner_.refineGICP(scan, continuity_anchor_);
      RCLCPP_INFO(get_logger(),
        "Continuity GICP: fitness=%.3f anchor[%.2f %.2f yaw=%.1fdeg] -> pos[%.2f %.2f yaw=%.1fdeg]",
        local.fitness,
        continuity_anchor_.translation().x(), continuity_anchor_.translation().y(),
        poseYaw(continuity_anchor_) * 180.0 / M_PI,
        local.pose.translation().x(), local.pose.translation().y(),
        poseYaw(local.pose) * 180.0 / M_PI);
      if (local.fitness >= continuity_min_fitness_ &&
          poseMatchesContinuity(local.pose, true) &&
          validateRelocResult(local, std::vector<CandidateMatch>{}, true))
      {
        best = local;
        found = true;
        accepted_by_bbs3d = true;
        win_stage = "continuity-GICP";
        RCLCPP_INFO(get_logger(), "Reloc won at stage [%s]", win_stage.c_str());
      }
      else if (local.fitness < continuity_min_fitness_)
      {
        RCLCPP_WARN(get_logger(),
          "Continuity GICP fitness %.3f < %.3f; running true full-map relocalization",
          local.fitness, continuity_min_fitness_);
      }
    }

    if (!found) found = tryScDirectReloc(scan, sc_candidates, best, win_stage);
    if (!found) found = tryScGicpReloc(scan, sc_candidates, best, win_stage);
    if (found)
    {
      accepted_by_bbs3d = true;
      RCLCPP_INFO(get_logger(), "Reloc won at stage [%s]", win_stage.c_str());
    }

    // ---- BBS3D: 由近到远 (从中心一圈圈外扩, 仅搜有地面区域) ----
    if (!found && bb_enable_ && bbs3d_.ready())
    {
      const auto src = prepareBbs3dSource(scan);
      if (src.size() < 100)
      {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
          "BBS3D: too few cropped scan points (%zu). Check scan_range.", src.size());
        return;
      }

      if (search_mode_ == "sc_candidates")
      {
        found = relocBySCCandidates(src, scan, sc_candidates, best, win_stage);
      }
      else
      {
        found = relocByExpandFromCenter(src, scan, sc_candidates, best, win_stage);
      }

      // 兜底: 全图搜索(仅当上面没找到)
      if (!found)
      {
        setBbs3dFullSearch();
        win_stage = "full-map";
        found = runBbs3dGicp(src, scan, win_stage, sc_candidates, best);
      }

      setBbs3dFullSearch();  // 恢复默认搜索框

      if (!found)
      {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
          "BBS3D failed all stages. Retrying...");
        return;
      }
      accepted_by_bbs3d = true;
      RCLCPP_INFO(get_logger(), "Reloc won at stage [%s]", win_stage.c_str());
    }
    else if (!found)
    {
      // BBS3D 不可用时才用原 SC+GICP 级联(仅兜底)
      Eigen::Vector3d center(
        search_center_.size() > 0 ? search_center_[0] : 0.0,
        search_center_.size() > 1 ? search_center_[1] : 0.0, 0.0);
      if (!db_.empty())
      {
        auto candidates = db_.query(query_desc, top_k_, sc_);
        if (!candidates.empty()) center = candidates[0].pose.translation();
        for (const auto &c : candidates)
        {
          Eigen::Isometry3d guess = c.pose;
          Eigen::Isometry3d yaw_corr = Eigen::Isometry3d::Identity();
          yaw_corr.linear() = Eigen::AngleAxisd(c.yaw_offset_rad, Eigen::Vector3d::UnitZ()).toRotationMatrix();
          guess = guess * yaw_corr;
          RefineResult gicp = refiner_.refineGICP(scan, guess);
          if (gicp.fitness > best.fitness) best = gicp;
        }
      }
      if (best.fitness < min_fitness_)
      {
        RefineResult grid = refiner_.searchPositionYawGrid(
          scan, center, xy_search_step_, xy_search_half_, yaw_search_steps_);
        RefineResult gicp2 = refiner_.refineGICP(scan, grid.pose);
        if (gicp2.fitness > best.fitness) best = gicp2;
        if (grid.fitness > best.fitness && gicp2.fitness < min_fitness_) best = grid;
      }
    }

    last_fitness_ = best.fitness;
    if (!accepted_by_bbs3d && best.fitness < min_fitness_)
    {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
        "Global relocalization failed (fitness=%.3f < %.3f). Retrying...",
        best.fitness, min_fitness_);
      return;
    }

    if (map_bounds_.valid && !poseInsideMapBounds(best.pose))
    {
      RCLCPP_WARN(get_logger(),
        "Reject relocalization pose (%.2f, %.2f) outside 2D map x[%.1f,%.1f] y[%.1f,%.1f]. Retrying...",
        best.pose.translation().x(), best.pose.translation().y(),
        map_bounds_.min_x, map_bounds_.max_x, map_bounds_.min_y, map_bounds_.max_y);
      return;
    }

    if (auto_publish_)
    {
      publishInitialPose(best.pose);
    }
    reloc_done_ = true;
    last_reloc_time_ = now();
    last_odom_time_ = now();  // 给 FAST-LIO 收敛/起步发布 odom 的缓冲, 避免误判跟丢
    RCLCPP_INFO(get_logger(),
      "Global relocalization SUCCESS (fitness=%.3f). Now tracking; will only re-trigger if lost.",
      best.fitness);
  }

  std::string db_dir_;
  std::string map_pcd_;
  int top_k_;
  double min_fitness_;
  int yaw_search_steps_;
  double xy_search_step_;
  int xy_search_half_;
  bool auto_publish_;
  double reloc_period_sec_;
  double tracking_lost_fitness_;
  double odom_lost_timeout_ = 3.0;
  int max_accum_frames_ = 10;
  double verify_period_sec_ = 1.0;
  double verify_min_score_ = 0.45;
  int verify_fail_limit_ = 3;
  int verify_fail_count_ = 0;
  double last_fitness_ = 0.0;
  bool continuity_enable_ = true;
  double continuity_max_translation_ = 2.5;
  double continuity_max_yaw_deg_ = 90.0;
  double continuity_min_fitness_ = 0.85;
  bool has_continuity_anchor_ = false;
  Eigen::Isometry3d continuity_anchor_ = Eigen::Isometry3d::Identity();

  bool bb_enable_ = true;
  double bbs3d_min_level_res_ = 0.5;
  int bbs3d_max_level_ = 6;
  double bbs3d_tar_leaf_ = 0.1;
  double bbs3d_src_leaf_ = 0.5;
  double bbs3d_min_scan_ = 1.0;
  double bbs3d_max_scan_ = 40.0;
  double bbs3d_rp_range_ = 0.0;
  double bbs3d_score_thresh_ = 0.5;
  int bbs3d_timeout_msec_ = 0;
  double bbs3d_ground_z_ = 0.0;
  double bbs3d_z_range_ = 1.0;
  std::string grid_map_yaml_;
  double bbs3d_search_margin_ = 2.0;
  bool clip_search_to_grid_map_ = true;
  std::string search_mode_ = "expand_from_center";
  std::vector<double> search_center_{0.0, 0.0};
  double ring_step_ = 3.0;
  double ring_max_radius_ = 0.0;
  double min_accept_fitness_ = 0.50;
  double high_accept_fitness_ = 0.85;
  bool sc_gate_enable_ = true;
  double sc_gate_max_dist_ = 5.0;
  bool use_sc_center_ = true;
  double sc_center_max_dist_ = 0.35;
  double sc_tight_radius_ = 1.5;
  double sc_confident_xy_gate_ = 1.2;
  double sc_confident_yaw_gate_deg_ = 40.0;
  bool sc_gicp_first_ = true;
  // 本轮重定位检测到"正反 yaw 歧义"(SC yaw 与全 yaw 网格最优朝向≈180°且分数接近)。
  // 置位后: 不让 SC+GICP 直接发布, 交给 BBS3D 全 yaw 全局搜索定夺; 并在校验时
  // 忽略不可靠的 SC yaw 门。每轮 tryRelocalize 开头复位。
  bool yaw_ambiguous_ = false;
  double yaw_ambiguity_deg_ = 120.0;     // 两路 yaw 差 > 此值视为正反歧义
  double yaw_ambiguity_margin_ = 0.20;   // 两路 fitness 差 < 此值视为"分不清谁对"
  bool sc_direct_pose_ = false;
  double sc_direct_min_score_ = 0.45;
  double candidate_radius_ = 5.0;
  std::vector<double> expand_radii_{4.0, 10.0, 25.0};
  Eigen::Vector3f full_search_min_ = Eigen::Vector3f::Zero();
  Eigen::Vector3f full_search_max_ = Eigen::Vector3f::Zero();
  MapBounds2D map_bounds_;

  // 地面模型
  bool ground_filter_enable_ = true;
  double ground_z_min_rel_ = -0.6;
  double ground_z_max_rel_ = 0.5;
  double ground_cell_ = 1.0;
  int ground_min_pts_ = 2;
  int ground_dilate_ = 1;
  bool ground_valid_ = false;
  double gm_origin_x_ = 0.0, gm_origin_y_ = 0.0, gm_res_ = 1.0;
  int gm_w_ = 0, gm_h_ = 0;
  std::vector<uint8_t> gm_;
  Eigen::Vector2f ground_min_ = Eigen::Vector2f::Zero();
  Eigen::Vector2f ground_max_ = Eigen::Vector2f::Zero();

  ScanContext sc_;
  KeyframeDatabase db_;
  PoseRefiner refiner_;
  Bbs3dWrapper bbs3d_;

  std::deque<pcl::PointCloud<pcl::PointXYZI>> recent_frames_;
  std::mutex mtx_;
  pcl::PointCloud<pcl::PointXYZI> latest_registered_;
  std::mutex reg_mtx_;
  bool has_registered_ = false;
  bool has_scan_ = false;
  int scan_count_ = 0;
  bool reloc_done_ = false;
  rclcpp::Time last_reloc_time_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_odom_time_{0, 0, RCL_ROS_TIME};

  rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr pub_init_;
  rclcpp::Subscription<livox_ros_driver2::msg::CustomMsg>::SharedPtr sub_lidar_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr sub_odom_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr sub_registered_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::TimerBase::SharedPtr verify_timer_;
};

}  // namespace global_reloc

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<global_reloc::GlobalRelocNode>());
  rclcpp::shutdown();
  return 0;
}
