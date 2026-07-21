import pybullet as p
import pybullet_data
from brushbot import config

class Scene:
    def __init__(self, gui: bool = False):
        self._gui = gui
        self.cid = None
        self.robot = None
        self.num_joints = 0
        self.movable = []      # 可动(非 FIXED)关节的索引, IK 结果按此顺序映射

    def load(self):
        self.cid = p.connect(p.GUI if self._gui else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        # PAPER_Z is an ABSTRACT writing plane used only for pen-down detection & rendering — it is NOT a physical collision surface; the ground plane sits at z=0.
        p.loadURDF("plane.urdf", [0, 0, 0])
        self.robot = p.loadURDF(config.ARM_URDF, [0, 0, 0], useFixedBase=True)
        self.num_joints = p.getNumJoints(self.robot)
        # calculateInverseKinematics 返回的 q 只含可动关节, 按出现顺序排列.
        # Elfin 前有 2 个 FIXED 关节 -> 关节索引 != 自由度索引, 必须显式映射.
        self.movable = [i for i in range(self.num_joints)
                        if p.getJointInfo(self.robot, i)[2] != p.JOINT_FIXED]

    def tcp_pose(self):
        ls = p.getLinkState(self.robot, config.EEF_LINK)
        pos = ls[0]
        euler = p.getEulerFromQuaternion(ls[1])
        return (pos[0], pos[1], pos[2], euler[0], euler[1], euler[2])

    def ik(self, pos_xyz, ori_euler=None):
        # B1 用位置-only IK, 保证笔尖到达 xyz (姿态 v1 不约束, 留给 B2/实机)
        # Elfin5 是 6-DOF 非冗余臂, 位置-only IK 精确 (残差 ~0). 提高迭代/收紧残差
        # 只是稳妥 (对早期用的 KUKA 7-DOF 冗余臂尤为必要, 那时有 ~0.02m 收敛地板)。
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
        # q[k] 对应第 k 个可动关节 (非 FIXED), 非关节索引 k
        for k, jidx in enumerate(self.movable):
            if k < len(q):
                p.setJointMotorControl2(self.robot, jidx, p.POSITION_CONTROL, q[k],
                                        force=config.JOINT_MAX_FORCE)

    def step(self):
        p.stepSimulation()

    def close(self):
        if self.cid is not None:
            p.disconnect()
            self.cid = None
