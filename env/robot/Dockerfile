FROM ros:humble-ros-base-jammy
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/calibagent
COPY . .
RUN python3 -m pip install --no-cache-dir -e .
# Unitree SDK/ROS pin is added only after the P8 hardware gate is approved.

