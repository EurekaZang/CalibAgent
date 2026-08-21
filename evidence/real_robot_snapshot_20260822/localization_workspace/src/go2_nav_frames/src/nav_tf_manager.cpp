/**
 * Nav2 TF manager: splits FAST-LIO map->base_link into map->odom + odom->base_link
 */
#include <cmath>
#include <mutex>
#include <string>

#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <rclcpp/rclcpp.hpp>
#include <tf2/LinearMath/Matrix3x3.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <tf2_ros/transform_broadcaster.h>

namespace go2_nav_frames
{

struct Pose2D
{
  double x{0}, y{0}, z{0};
  tf2::Quaternion q{0, 0, 0, 1};
};

Pose2D odomToPose(const nav_msgs::msg::Odometry & o)
{
  Pose2D p;
  p.x = o.pose.pose.position.x;
  p.y = o.pose.pose.position.y;
  p.z = o.pose.pose.position.z;
  tf2::fromMsg(o.pose.pose.orientation, p.q);
  return p;
}

Pose2D msgToPose(const geometry_msgs::msg::Pose & pose)
{
  Pose2D p;
  p.x = pose.position.x;
  p.y = pose.position.y;
  p.z = pose.position.z;
  tf2::fromMsg(pose.orientation, p.q);
  return p;
}

Pose2D compose(const Pose2D & a, const Pose2D & b)
{
  Pose2D out;
  tf2::Matrix3x3 m_a(a.q), m_b(b.q);
  tf2::Vector3 t_b(b.x, b.y, b.z);
  tf2::Vector3 t_out = m_a * t_b + tf2::Vector3(a.x, a.y, a.z);
  tf2::Matrix3x3 m_out = m_a * m_b;
  out.x = t_out.x();
  out.y = t_out.y();
  out.z = t_out.z();
  m_out.getRotation(out.q);
  out.q.normalize();
  return out;
}

void flattenPose2D(Pose2D & p)
{
  p.z = 0.0;
  double roll, pitch, yaw;
  tf2::Matrix3x3(p.q).getRPY(roll, pitch, yaw);
  p.q.setRPY(0.0, 0.0, yaw);
}

Pose2D inverse(const Pose2D & a)
{
  Pose2D out;
  tf2::Matrix3x3 m(a.q);
  tf2::Matrix3x3 m_inv = m.transpose();
  tf2::Vector3 t(a.x, a.y, a.z);
  tf2::Vector3 t_inv = m_inv * (-t);
  out.x = t_inv.x();
  out.y = t_inv.y();
  out.z = t_inv.z();
  m_inv.getRotation(out.q);
  out.q.normalize();
  return out;
}

class NavTfManager : public rclcpp::Node
{
public:
  NavTfManager()
  : Node("nav_tf_manager"),
    map_frame_(declare_parameter<std::string>("map_frame", "map")),
    odom_frame_(declare_parameter<std::string>("odom_frame", "odom")),
    base_frame_(declare_parameter<std::string>("base_frame", "base_link")),
    fastlio_odom_topic_(declare_parameter<std::string>("fastlio_odom_topic", "/Odometry")),
    max_initialpose_jump_(declare_parameter<double>("max_initialpose_jump", 1.5))
  {
    tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);

    sub_fastlio_ = create_subscription<nav_msgs::msg::Odometry>(
      fastlio_odom_topic_, rclcpp::QoS(20),
      std::bind(&NavTfManager::fastlioOdomCallback, this, std::placeholders::_1));

    sub_init_ = create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
      "/initialpose", rclcpp::QoS(10),
      std::bind(&NavTfManager::initialPoseCallback, this, std::placeholders::_1));

    pub_odom_ = create_publisher<nav_msgs::msg::Odometry>("/odom", rclcpp::QoS(20));

    RCLCPP_INFO(get_logger(),
      "nav_tf_manager: %s -> %s -> %s (input %s)",
      map_frame_.c_str(), odom_frame_.c_str(), base_frame_.c_str(),
      fastlio_odom_topic_.c_str());
  }

private:
  void publishTransforms(const rclcpp::Time & stamp)
  {
    geometry_msgs::msg::TransformStamped tf_map_odom;
    tf_map_odom.header.stamp = stamp;
    tf_map_odom.header.frame_id = map_frame_;
    tf_map_odom.child_frame_id = odom_frame_;
    tf_map_odom.transform.translation.x = map_to_odom_.x;
    tf_map_odom.transform.translation.y = map_to_odom_.y;
    tf_map_odom.transform.translation.z = map_to_odom_.z;
    tf_map_odom.transform.rotation = tf2::toMsg(map_to_odom_.q);

    geometry_msgs::msg::TransformStamped tf_odom_base;
    tf_odom_base.header.stamp = stamp;
    tf_odom_base.header.frame_id = odom_frame_;
    tf_odom_base.child_frame_id = base_frame_;
    tf_odom_base.transform.translation.x = last_odom_to_base_.x;
    tf_odom_base.transform.translation.y = last_odom_to_base_.y;
    tf_odom_base.transform.translation.z = last_odom_to_base_.z;
    tf_odom_base.transform.rotation = tf2::toMsg(last_odom_to_base_.q);

    tf_broadcaster_->sendTransform({tf_map_odom, tf_odom_base});
  }

  void initialPoseCallback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
  {
    std::lock_guard<std::mutex> lk(mtx_);
    const Pose2D t_map_base_target = msgToPose(msg->pose.pose);

    if (map_to_odom_initialized_ && fastlio_odom_received_) {
      const Pose2D current_map_base = compose(map_to_odom_, last_odom_to_base_);
      const double dx = t_map_base_target.x - current_map_base.x;
      const double dy = t_map_base_target.y - current_map_base.y;
      const double jump = std::hypot(dx, dy);
      // A non-positive value explicitly disables this local gate. FAST-LIO
      // and the TF manager must accept the same /initialpose atomically;
      // rejecting it here while FAST-LIO accepts it leaves map->base_link on
      // the old (often mirrored) branch.
      if (max_initialpose_jump_ > 0.0 && jump > max_initialpose_jump_) {
        RCLCPP_ERROR(get_logger(),
          "Reject /initialpose jump %.2fm (%.2f,%.2f)->(%.2f,%.2f), keep current TF",
          jump, current_map_base.x, current_map_base.y,
          t_map_base_target.x, t_map_base_target.y);
        return;
      }
    }

    // 首次 initialpose 时 FAST-LIO 尚未发 /Odometry, odom->base 暂用单位变换。
    if (!fastlio_odom_received_) {
      last_odom_to_base_ = Pose2D{};
    }
    map_to_odom_ = compose(t_map_base_target, inverse(last_odom_to_base_));
    flattenPose2D(map_to_odom_);
    map_to_odom_initialized_ = true;

    // 立刻发布 TF, 避免 controller 在首帧 /Odometry 前报 base_link->odom 不存在。
    rclcpp::Time stamp(msg->header.stamp);
    if (stamp.seconds() == 0.0) {
      stamp = now();
    }
    publishTransforms(stamp);

    nav_msgs::msg::Odometry odom;
    odom.header.stamp = stamp;
    odom.header.frame_id = odom_frame_;
    odom.child_frame_id = base_frame_;
    odom.pose.pose.position.x = last_odom_to_base_.x;
    odom.pose.pose.position.y = last_odom_to_base_.y;
    odom.pose.pose.position.z = last_odom_to_base_.z;
    odom.pose.pose.orientation = tf2::toMsg(last_odom_to_base_.q);
    pub_odom_->publish(odom);

    RCLCPP_WARN(get_logger(),
      "Updated map->odom from /initialpose [%.2f %.2f %.2f] (TF published immediately)",
      t_map_base_target.x, t_map_base_target.y, t_map_base_target.z);
  }

  void fastlioOdomCallback(const nav_msgs::msg::Odometry::SharedPtr msg)
  {
    std::lock_guard<std::mutex> lk(mtx_);
    fastlio_odom_received_ = true;
    const Pose2D t_map_base = odomToPose(*msg);
    if (!map_to_odom_initialized_) {
      // 极端情况: FAST-LIO 先于 initialpose 发 odom, 暂设 map->odom 为单位。
      map_to_odom_ = Pose2D{};
      map_to_odom_initialized_ = true;
    }
    last_odom_to_base_ = compose(inverse(map_to_odom_), t_map_base);
    flattenPose2D(last_odom_to_base_);

    nav_msgs::msg::Odometry odom = *msg;
    odom.header.frame_id = odom_frame_;
    odom.child_frame_id = base_frame_;
    odom.pose.pose.position.x = last_odom_to_base_.x;
    odom.pose.pose.position.y = last_odom_to_base_.y;
    odom.pose.pose.position.z = last_odom_to_base_.z;
    odom.pose.pose.orientation = tf2::toMsg(last_odom_to_base_.q);
    pub_odom_->publish(odom);

    publishTransforms(msg->header.stamp);
  }

  std::string map_frame_, odom_frame_, base_frame_, fastlio_odom_topic_;
  double max_initialpose_jump_{1.5};
  bool map_to_odom_initialized_{false};
  bool fastlio_odom_received_{false};
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr sub_fastlio_;
  rclcpp::Subscription<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr sub_init_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr pub_odom_;

  std::mutex mtx_;
  Pose2D map_to_odom_;
  Pose2D last_odom_to_base_;
};

}  // namespace go2_nav_frames

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<go2_nav_frames::NavTfManager>());
  rclcpp::shutdown();
  return 0;
}
