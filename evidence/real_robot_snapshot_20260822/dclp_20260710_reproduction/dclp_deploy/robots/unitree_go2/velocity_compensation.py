# ============================================================
# 耦合速度补偿函数 (自动生成)
# 模型: fullquad (分段: vyaw_desired符号分离)
# 生成时间: 2026-07-06T02:10:41.227348
# ============================================================

def compensate_velocity(vx_desired: float, vyaw_desired: float):
    """
    前馈补偿: 将期望真实速度映射为所需指令速度
    左转(负vyaw)和右转(正vyaw)使用独立模型以校正机械不对称
    Args:
        vx_desired: 期望前向速度 (m/s)
        vyaw_desired: 期望偏航角速度 (rad/s)
    Returns: (vx_cmd, vyaw_cmd)
    """
    if vyaw_desired >= 0:
        vx_cmd = (+0.087976 +
            +0.576250*vx_desired +
            -0.102232*vyaw_desired +
            +0.282972*vx_desired*vyaw_desired +
            +0.553009*vx_desired**2 +
            +0.050530*vyaw_desired**2)
        vyaw_cmd = (-0.022478 +
            +0.047737*vx_desired +
            +1.295364*vyaw_desired +
            -0.032387*vx_desired*vyaw_desired +
            -0.063670*vx_desired**2 +
            -0.115762*vyaw_desired**2)
    else:
        vx_cmd = (+0.063134 +
            +0.699219*vx_desired +
            +0.141632*vyaw_desired +
            -0.300981*vx_desired*vyaw_desired +
            +0.415782*vx_desired**2 +
            +0.049196*vyaw_desired**2)
        vyaw_cmd = (-0.022382 +
            +0.024664*vx_desired +
            +1.222709*vyaw_desired +
            +0.108558*vx_desired*vyaw_desired +
            +0.066902*vx_desired**2 +
            +0.102695*vyaw_desired**2)
    return vx_cmd, vyaw_cmd


def predict_real_velocity(vx_cmd: float, vyaw_cmd: float):
    """正向预测: 指令速度 → 真实速度 (统一模型)"""
    vx_real = (+0.087976 +
            +0.576250*vx_cmd +
            -0.102232*vyaw_cmd +
            +0.282972*vx_cmd*vyaw_cmd +
            +0.553009*vx_cmd**2 +
            +0.050530*vyaw_cmd**2)
    vyaw_real = (-0.022478 +
            +0.047737*vx_cmd +
            +1.295364*vyaw_cmd +
            -0.032387*vx_cmd*vyaw_cmd +
            -0.063670*vx_cmd**2 +
            -0.115762*vyaw_cmd**2)
    return vx_real, vyaw_real
