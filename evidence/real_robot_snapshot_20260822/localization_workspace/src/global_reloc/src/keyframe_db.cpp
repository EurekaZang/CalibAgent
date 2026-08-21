#include "global_reloc/keyframe_db.hpp"

#include <pcl/io/pcd_io.h>
#include <pcl/filters/voxel_grid.h>

#include <fstream>
#include <sstream>
#include <sys/stat.h>
#include <algorithm>
#include <cmath>

namespace global_reloc
{

static bool fileExists(const std::string &path)
{
  struct stat st;
  return stat(path.c_str(), &st) == 0;
}

bool KeyframeDatabase::load(const std::string &db_dir, const ScanContext &sc, const rclcpp::Logger &logger)
{
  db_dir_ = db_dir;
  entries_.clear();

  std::string poses_file = db_dir + "/poses.txt";
  if (!fileExists(poses_file))
  {
    RCLCPP_ERROR(logger, "poses.txt not found in %s", db_dir.c_str());
    return false;
  }

  std::ifstream ifs(poses_file);
  std::string line;
  while (std::getline(ifs, line))
  {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream iss(line);
    KeyframeEntry e;
    double qx, qy, qz, qw;
    if (!(iss >> e.id >> e.timestamp >> e.position.x() >> e.position.y() >> e.position.z()
              >> qx >> qy >> qz >> qw))
    {
      continue;
    }
    e.orientation = Eigen::Quaterniond(qw, qx, qy, qz);
    char fname[512];
    snprintf(fname, sizeof(fname), "%s/keyframes/%06d.pcd", db_dir.c_str(), e.id);
    e.pcd_path = fname;
    if (!fileExists(e.pcd_path)) continue;

    pcl::PointCloud<pcl::PointXYZI> cloud;
    if (pcl::io::loadPCDFile<pcl::PointXYZI>(e.pcd_path, cloud) != 0) continue;
    e.descriptor = sc.makeDescriptor(cloud);
    e.ring_key = sc.makeRingKey(e.descriptor);
    e.sector_key = sc.makeSectorKey(e.descriptor);
    entries_.push_back(e);
  }

  RCLCPP_INFO(logger, "Loaded %zu keyframes from %s", entries_.size(), db_dir.c_str());
  return !entries_.empty();
}

std::vector<CandidateMatch> KeyframeDatabase::query(
  const Eigen::MatrixXd &query_desc,
  int top_k,
  const ScanContext &sc) const
{
  Eigen::VectorXd q_ring = sc.makeRingKey(query_desc);
  Eigen::VectorXd q_sector = sc.makeSectorKey(query_desc);

  struct Scored
  {
    int idx;
    double ring_dist;
  };
  std::vector<Scored> ring_scores;
  ring_scores.reserve(entries_.size());
  for (size_t i = 0; i < entries_.size(); ++i)
  {
    double d = (entries_[i].ring_key - q_ring).norm();
    ring_scores.push_back({static_cast<int>(i), d});
  }
  std::sort(ring_scores.begin(), ring_scores.end(),
    [](const Scored &a, const Scored &b) { return a.ring_dist < b.ring_dist; });

  const int preselect = std::min(static_cast<int>(entries_.size()), std::max(top_k * 4, 20));
  std::vector<CandidateMatch> results;
  for (int i = 0; i < preselect; ++i)
  {
    const auto &entry = entries_[ring_scores[i].idx];
    int shift = 0;
    double dist = sc.distance(query_desc, entry.descriptor, &shift);
    CandidateMatch c;
    c.keyframe_id = entry.id;
    c.sc_distance = dist;
    c.yaw_shift = shift;
    c.yaw_offset_rad = shift * (2.0 * M_PI / sc.numSectors());
    c.pose = Eigen::Isometry3d::Identity();
    c.pose.linear() = entry.orientation.toRotationMatrix();
    c.pose.translation() = entry.position;
    results.push_back(c);
  }

  std::sort(results.begin(), results.end(),
    [](const CandidateMatch &a, const CandidateMatch &b) {
      return a.sc_distance < b.sc_distance;
    });
  if (static_cast<int>(results.size()) > top_k) results.resize(top_k);
  return results;
}

bool KeyframeDatabase::loadKeyframeCloud(int id, pcl::PointCloud<pcl::PointXYZI> &cloud) const
{
  char fname[512];
  snprintf(fname, sizeof(fname), "%s/keyframes/%06d.pcd", db_dir_.c_str(), id);
  return pcl::io::loadPCDFile<pcl::PointXYZI>(fname, cloud) == 0;
}

bool buildDatabaseFromKeyframes(
  const std::string &db_dir,
  const std::string &map_pcd_path,
  double voxel_leaf,
  const ScanContext &sc,
  const rclcpp::Logger &logger)
{
  mkdir((db_dir).c_str(), 0755);
  mkdir((db_dir + "/keyframes").c_str(), 0755);

  if (!fileExists(db_dir + "/poses.txt"))
  {
    RCLCPP_ERROR(logger, "No poses.txt in %s. Run mapping with keyframe_save.en=true first.", db_dir.c_str());
    return false;
  }

  if (fileExists(map_pcd_path))
  {
    pcl::PointCloud<pcl::PointXYZI>::Ptr map(new pcl::PointCloud<pcl::PointXYZI>());
    if (pcl::io::loadPCDFile<pcl::PointXYZI>(map_pcd_path, *map) == 0)
    {
      pcl::VoxelGrid<pcl::PointXYZI> vg;
      vg.setLeafSize(voxel_leaf, voxel_leaf, voxel_leaf);
      vg.setInputCloud(map);
      pcl::PointCloud<pcl::PointXYZI> map_ds;
      vg.filter(map_ds);
      const std::string out = db_dir + "/map_voxel.pcd";
      pcl::io::savePCDFileBinary(out, map_ds);
      RCLCPP_INFO(logger, "Saved voxel map %s (%zu pts)", out.c_str(), map_ds.size());
    }
  }
  else
  {
    RCLCPP_WARN(logger, "Map PCD not found: %s", map_pcd_path.c_str());
  }

  KeyframeDatabase db;
  if (!db.load(db_dir, sc, logger)) return false;
  RCLCPP_INFO(logger, "Relocalization DB ready: %zu keyframes", db.size());
  return true;
}

}  // namespace global_reloc
