import pybullet as p
import pybullet_data
from brushbot import config

class Scene:
    def __init__(self, gui: bool = False):
        self._gui = gui
        self.cid = None
        self.robot = None
        self.num_joints = 0

    def load(self):
        self.cid = p.connect(p.GUI if self._gui else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        # PAPER_Z is an ABSTRACT writing plane used only for pen-down detection & rendering — it is NOT a physical collision surface; the ground plane sits at z=0.
        p.loadURDF("plane.urdf", [0, 0, 0])
        self.robot = p.loadURDF(config.ARM_URDF, [0, 0, 0], useFixedBase=True)
        self.num_joints = p.getNumJoints(self.robot)

    def tcp_pose(self):
        ls = p.getLinkState(self.robot, config.EEF_LINK)
        pos = ls[0]
        euler = p.getEulerFromQuaternion(ls[1])
        return (pos[0], pos[1], pos[2], euler[0], euler[1], euler[2])

    def ik(self, pos_xyz, ori_euler=None):
        # B1 用位置-only IK, 保证笔尖到达 xyz (姿态 v1 不约束, 留给 B2/实机)
        # 注: pybullet 默认 maxNumIterations=20 对本 7-DOF 臂单次求解收敛不够精确
        # (实测残差 ~0.05-0.1m, 与目标点无关), 提高迭代次数/收紧残差阈值以获得
        # 更精确的解 (调优后残差 ~0.02m, 符合 test_ik_reaches_target 的 0.03m 容差)。
        if ori_euler is None:
            q = p.calculateInverseKinematics(
                self.robot, config.EEF_LINK, pos_xyz,
                maxNumIterations=100, residualThreshold=1e-5,
            )
        else:
            quat = p.getQuaternionFromEuler(ori_euler)
            q = p.calculateInverseKinematics(
                self.robot, config.EEF_LINK, pos_xyz, quat,
                maxNumIterations=100, residualThreshold=1e-5,
            )
        return list(q)

    def set_joints(self, q):
        for i in range(min(len(q), self.num_joints)):
            p.setJointMotorControl2(self.robot, i, p.POSITION_CONTROL, q[i], force=200)

    def step(self):
        p.stepSimulation()

    def close(self):
        if self.cid is not None:
            p.disconnect()
            self.cid = None
