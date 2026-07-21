# Elfin5 机器人描述 — 来源与许可

- **来源**：Han's Robot（大族机器人）官方 ROS 包 `elfin_robot` 的 `elfin_description`
  （https://github.com/huayan-robotics/elfin_robot）。
- **许可**：BSD 3-Clause License. Copyright (c) 2017, Han's Robot Co., Ltd. All rights reserved.
- **本目录内容**：
  - `meshes/*.STL` — 直接取自 `elfin_description/meshes/elfin5/`（未修改）。
  - `elfin5.urdf` — 由官方 `elfin_description/urdf/elfin5.urdf.xacro` 展开而来：
    去掉 3 个 xacro:include（materials/gazebo/transmission，PyBullet 运动学无需）、
    求值 `${PI}`/`${...*density}` 表达式、mesh 路径 `package://...` 改为相对 `meshes/`。
    展开纯属格式转换，未改动关节/连杆的运动学参数。
- **用途**：仿真执行端（`brushbot`）加载此 URDF 驱动 Elfin5 写字；真机同款运动学。
