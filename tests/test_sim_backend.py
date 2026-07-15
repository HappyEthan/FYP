import math
from brushbot.scene import Scene
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.types import Command

def test_sim_backend_tracks_command():
    sc = Scene(gui=False); sc.load()
    b = SimBackend(sc, ZeroTactile(), substeps=8)
    target = (0.5, 0.0, 0.3, math.pi, 0.0, 0.0)
    for _ in range(60):
        b.write(Command(tcp_pose=target))
    st = b.read()
    x, y, z = st.tcp_pose[:3]
    err = ((x-0.5)**2 + (y-0.0)**2 + (z-0.3)**2) ** 0.5
    # 已知 KUKA 位置-only IK 收敛底 ~0.0205m (见 task-3-report.md), 与 Task 3
    # test_ik_reaches_target 一致放宽到 3cm; 换 Elfin URDF 后需重新校核。
    assert err < 0.03
    assert st.g_meas == 0.0
    assert st.t > 0.0
    sc.close()
