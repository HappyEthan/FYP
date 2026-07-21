from brushbot.scene import Scene

def test_scene_loads_and_reads_tcp():
    sc = Scene(gui=False)
    sc.load()
    assert sc.num_joints >= 6
    pose = sc.tcp_pose()
    assert len(pose) == 6
    sc.close()

def test_sequential_scenes_do_not_interfere():
    """先后创建/销毁多个 Scene 时各自客户端不能串扰。

    Scene 若用模块级 pybullet API 而不显式传 physicsClientId, 调用会打到
    错误(或已断开)的客户端, 表现为跟踪精度随"同进程内跑过几个 Scene"而变。
    """
    import math
    from brushbot.backends.sim import SimBackend, ZeroTactile
    from brushbot.types import Command

    for _ in range(2):
        sc = Scene(gui=False)
        sc.load()
        b = SimBackend(sc, ZeroTactile(), substeps=8)
        target = (0.45, 0.0, 0.20, math.pi, 0.0, 0.0)
        for _ in range(60):
            b.write(Command(tcp_pose=target))
        x, y, z = b.read().tcp_pose[:3]
        err = ((x - 0.45) ** 2 + y ** 2 + (z - 0.20) ** 2) ** 0.5
        assert err < 0.01
        sc.close()


def test_ik_reaches_target():
    sc = Scene(gui=False)
    sc.load()
    target = (0.5, 0.0, 0.3)
    q = sc.ik(target)                 # 位置-only IK
    sc.set_joints(q)
    for _ in range(240):
        sc.step()
    x, y, z = sc.tcp_pose()[:3]
    err = ((x-target[0])**2 + (y-target[1])**2 + (z-target[2])**2) ** 0.5
    # 实测 pybullet 默认 IK 单次求解在 20 次迭代下对本臂/该目标残差达 ~0.05m
    # (与目标点选择无关, 见 task-3-report.md); 提高 ik() 内迭代次数后残差
    # 稳定收敛到 ~0.0204m, 按 brief Step 4 备注放宽到 3cm 容差。
    assert err < 0.03   # 3cm 内 (brief Step 4 允许的放宽)
    sc.close()
