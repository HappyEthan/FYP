---
project: 02-strokeplan
status: archived
---

# 无 Z StrokePlan 实施清单

> 这是 2026-09-22 已完成的无 Z V3 代码迁移记录，不是最终 StrokePlan 字段裁定。项目负责人后续倾向让 `z_ff` 进入 StrokePlan，其具体语义仍待讨论；下文“全局约束”只适用于当次实现。

> 用户已批准实施；2026-09-22 完成当前范围代码与离线联调。原步骤复选框保留作实施前清单，实际结果以以下记录为准。没有运行机械臂，没有提交 Git。

## 实施记录

- Task 1 complete：`target_strokeplan.py` 已实现 V3，旧 V2 API 保留；无 Z 校验、往返读取和非法数据测试通过。
- Task 2 complete：新增独立前馈构建与合成生成入口；四条套件改为 V3，测试无 runs 依赖、来源、排他写入和独立表。
- Task 3 complete：新增离线编译器，CLI 读取三个独立输入；先插值目标后查表；候选/未核验配置连接前拒绝。旧版 CLI 只保留显式离线预览。
- Task 4 complete：已生成 `target_v3.npz`、`target_v3_suite/`、`ry15_feedforward_v1/` 和含 Z 的独立编译预览；四条全部离线预检通过。图片已目视检查。
- 测试集中于 `test_target_strokeplan.py`、`test_target_feedforward.py`、`test_target_tools.py`，与旧版和相关实验回归合计 177 passed。全仓存在五项既有配置断言失败，详见本次交接，不宣称全仓全绿。
- 最终全仓复跑在 `test_monitor_window.py::test_disconnected_actions_explain_and_prevent_invalid_operations` 的 pyqtgraph/Qt 构造处段错误；该文件独立复跑 7 passed。其余全仓 633 passed / 15 failed / 8 skipped，其中 10 项是沙箱本地 socket 权限；对应 HTTP/IPC 文件沙箱外重跑 19 passed。未改旧 GUI 或实验配置。
- 五项配置断言：`test_record_hanzi_openloop.py::test_yong_waypoints_are_multi_stroke_and_safe`；`test_return_to_origin.py` 中 `test_confirmed_return_sends_one_direct_move_to_code_defined_origin`、`test_main_uses_hardcoded_connection_defaults_without_cli_arguments`、`test_main_allows_return_from_140_mm_high_position`；`test_run_ladder_experiment.py::test_zero_argument_defaults_compile_the_hardcoded_real_ladder`。

### 实施裁定与边界

- Ruling：在用户当前脏工作树实施，不迁移到新 worktree、不提交；实际依赖含用户未提交文件。代价是改动未以独立提交隔离，交付以具体文件和测试为准。
- Ruling：按用户批准的“不分派子代理”方式完成作者自审，不声称独立审查。自审发现三种 metadata Z/前馈键漏检，补充失败测试后修复。
- Ruling：V2 保留 API 和显式离线预览，不保留从此入口直接运动；避免绕过新独立配置审批。代价是旧命令上机前须迁移新格式。
- Ruling：将表与编译测试集中在 `test_target_feedforward.py`，CLI 联调放在 `test_target_tools.py`，不机械增加多个小测试文件。
- Ruling：现场变换首版只支持纸面 XY 平移，姿态固定；非网格末端在下一拍保持，额外时间小于 20 ms，未重定时笔画。
- 未做：专用 Skill、采集转换器、V2 自动转换器、曲线执行、动态姿态、磁记录或闭环；均作为后续明确任务。

**Goal:** 将新生成的目标笔画、实测前馈配置和执行编译分离，保留旧 V2 文件的读取能力。

**Architecture:** 新目标格式使用独立模块 `brushbot.target_strokeplan`，其中公开类仍称 `Stroke` / `StrokePlan`，写入 `format_version=3`。原 `brushbot.strokeplan` 保留为 V2 兼容模块，不在同一个类里用可选 Z 混合两种契约。新生成入口只使用 V3；执行入口显式区分 V3 与旧版。

**Tech Stack:** Python、NumPy、pytest、现有 SI 机械臂适配层；不新增依赖。

**Spec:** [StrokePlan 现行设计](../strokeplan.md)。本清单落实当前直线前馈验证，不承诺通用曲线执行、闭环或自动沾水。

## 全局约束

- StrokePlan 只含 `s/xy/t/g_target`、可选姿态和来源；不含任何 Z 或内嵌前馈表。
- 位置 m、时间 s、磁响应 µT；磁目标定义为先对基线差分向量滤波再求 XY 模长，不称为力。
- 合成生成无需 runs；实测前馈配置使用 Ry15 两个完整 run。
- 新执行流程先对目标按时间插值，再查表，不先查表再插值 Z。
- 前馈配置与现场执行设置分别加载，缺失或不匹配直接拒绝。
- 不覆盖旧 NPZ、原始 run、旧图表，不改变 ladder、return_to_origin。
- 不连接机器人；只允许离线生成、预检与假机械臂测试。真机仍要求用户自行 `--execute` 并输入 RUN。
- 不自动批准候选标定；候选可离线预检，真机执行前拒绝未批准配置。
- 不自动提交或清理当前脏工作树。

## 审查重点

1. 把 Z 藏入 metadata 或旧版 loader：V3 写入/读取均拒绝 Z 和内嵌表，旧版不静默转换。
2. 非线性表与时序：用手算中点测试查表顺序；不重定时用户的逐点 t。
3. 适用条件：错姿态、错滤波、越界目标和不支持的方向/速度在连接前拒绝。
4. 时序端点与停顿：t 严格递增，重复 XY 允许；编译后的端点、保持及速度检查一致。
5. 遗留依赖：demo、实验记录和旧轨迹仍依赖 V2，不能因迁移破坏原接口。

## 任务 1：增加无 Z 的版本化目标格式

**Files:** 新建 `src/brushbot/target_strokeplan.py`、`tests/test_target_strokeplan.py`；原 V2 文件仅补充 legacy 说明，不更改数据行为。

**Interfaces:**

```python
@dataclass
class Stroke:
    s: np.ndarray
    xy: np.ndarray
    t: np.ndarray
    g_target: np.ndarray
    orientation: np.ndarray | None = None

@dataclass
class StrokePlan:
    strokes: list[Stroke]
    meta: dict

    def validate(self) -> None: ...
    def save(self, path) -> None: ...
    @classmethod
    def load(cls, path) -> "StrokePlan": ...
```

- [ ] 先写 round-trip、缺失 t、NaN、负目标、数组不齐、重复时间、零长度、错误 s、版本不匹配、metadata 含 Z/表的失败测试。保存采用排他创建，禁止覆盖。合法停顿必须能往返读取。

```python
def test_round_trip_has_no_z(tmp_path):
    from brushbot.target_strokeplan import Stroke, StrokePlan
    p = StrokePlan([Stroke(np.array([0., 1.]),
        np.array([[0., 0.], [.02, 0.]]),
        np.array([0., 2.]), np.array([30., 40.]))],
        dict(source="synthetic", coordinate_frame="paper",
             feature="filtered_dBxy_norm_uT",
             filter_definition={"kind": "ema", "alpha": .3}))
    path = tmp_path / "target.npz"
    p.save(path)
    with np.load(path, allow_pickle=False) as d:
        assert "s0_z" not in d.files
    q = StrokePlan.load(path)
    assert q.strokes[0].t.tolist() == [0., 2.]
    assert q.strokes[0].g_target.tolist() == [30., 40.]
```

- [ ] 运行 `PYTHONPATH=src python -m pytest tests/test_target_strokeplan.py -q`，确认新能力缺失导致失败。
- [ ] 实现 V3 校验及 NPZ I/O：键为 `format_version/n_strokes/meta_json/sN_s/sN_xy/sN_t/sN_g`，可选姿态独立键。来源、坐标系及磁特征必须明确；归一化 s 从 XY 验证，允许停顿但拒绝整笔长度为零。禁止 Z/前馈数据进入 metadata。
- [ ] 重跑新测试与 `tests/test_strokeplan.py`，确保 V2 行为未变。

## 任务 2：独立前馈配置与无数据依赖的目标生成

**Files:** 新建 `src/brushbot/feedforward.py`、`scripts/build_feedforward_table.py`、`scripts/generate_strokeplan.py`；修改 `scripts/generate_measured_strokeplan.py` 和 `scripts/generate_strokeplan_suite.py`；增加 `tests/test_feedforward.py` 与 `tests/test_generate_target_plan.py`。

**Interfaces:**

```python
# brushbot.feedforward
def validate_table(table: dict) -> None: ...
def lookup_depth_m(table: dict, g_target: np.ndarray) -> np.ndarray: ...

# scripts.build_feedforward_table
def build(run_dirs) -> tuple[dict, dict]:
    """Return independent candidate table and suggested execution settings."""

# scripts.generate_strokeplan
def generate(*, targets_uT, length_mm=200., speed_mm_s=10.,
             filter_definition=None) -> StrokePlan: ...
```

- [ ] 测试手算表插值、非单调/非有限表、目标越界、重复批次等权汇总；测试生成器在无 runs 目录下成功，来源为 synthetic，不出现 Z/表。测试输出已存在时拒绝而非覆盖。

```python
def test_lookup_rejects_extrapolation(valid_table):
    valid_table.update(amplitude_uT=[20., 40., 80.],
                       depth_mm=[5., 10., 12.])
    assert lookup_depth_m(valid_table, np.array([30.]))[0] == pytest.approx(.0075)
    with pytest.raises(ValueError):
        lookup_depth_m(valid_table, np.array([81.]))
```

- [ ] 先运行新测试确认失败，再将现有完整 measure 路径提取逻辑抽到独立构建入口，保留稳定窗口、样本 age、来源、单调性检查。加入 installation、mount、姿态、滤波、方向、速度、TCP/UCS、有效范围及 `approved=False`。
- [ ] 合成生成器只计算 XY、t、g_target；采用明确的加减速时间律产生时间戳，峰值巡航速度不超过请求值。输出 V3 NPZ 及目标预览，数据不来自标定表。
- [ ] 套件保留渐变、单峰、双峰、平滑多档的目标形状，改为无 Z 生成，不调用编译器或读取 run。所有图改为 XY/目标/时间信息，不画不存在的 Z。
- [ ] 旧 `generate_measured_strokeplan.py` 的旧 API 保留并标记 legacy；CLI 要求显式 legacy 选择才输出旧混合格式，提示新入口。不删除旧脚本或产物。
- [ ] 新配置保存到新的输出路径；现场设置仅标记为历史 run 派生建议，不能视为当前现场已验证。
- [ ] 重跑上述测试和 `tests/test_measured_strokeplan.py`。

## 任务 3：执行器接入独立输入并保留离线安全边界

**Files:** 修改 `scripts/run_feedforward_strokeplan.py`；新建 `src/brushbot/strokeplan_compile.py` 与 `tests/test_target_compilation.py`；保留原假机械臂测试。

**Interfaces:**

```python
def compile_target_plan(plan, table: dict, settings: dict,
                        *, dt_s=.02) -> tuple[np.ndarray, list[str]]:
    """Return SI XYZ/RPY poses and phase labels; never connect hardware."""
```

- [ ] 测试相同目标配不同表得到不同 Z 且不修改计划；对非线性表手算中点，验证先插值目标再查表：目标从 20→80，中点为 50，表 [20,40,80]→[5,10,12] mm 得 10.5 mm，不是端点压深均值 8.5 mm。
- [ ] 测试错姿态/滤波/装配、越界、未指定坐标系、不支持方向、超速、深度与工作空间超限均拒绝；测试 1 s/20 ms 时刻和终点保持；测试合法停顿保留时间，不自动重定时。
- [ ] 先运行失败测试，再实现纯离线编译器：按 t 采样 XY/g，查表生成压深，按物理 Z 向上计算，添加高位进入、下笔、抬笔和高位返回。固定姿态先由 settings 提供；不同或动态姿态明确拒绝，不静默忽略。
- [ ] 初版仍限制标定覆盖的 +X 直线。对加减速过渡和停顿明确报告不属于匀速标定有效段，不能把 10 mm/s 的表宣称成任意速度标定；真机批准流程需覆盖这些过渡条件。
- [ ] CLI 增加 `--feedforward`、`--settings`，V3 缺少任一项即离线报错；V2 要求 `--legacy-v2`，保留原编译行为但不得作为默认路径。默认仅预览；候选表不能通过 `--execute`。
- [ ] 预览旁保存计划/表/设置的标识、哈希、预检结果及限制说明；避免覆盖。硬件分支继续复用原 TCP/UCS、wait/FSM 检查和原 SI 下发函数，不改变异常停止行为。
- [ ] 重跑 `tests/test_target_compilation.py`、`tests/test_measured_strokeplan.py`、`tests/test_execute_strokeplan.py` 和适配层测试，全程假机械臂。

## 任务 4：离线联调、迁移说明与交接

**Files:** 更新主设计文档第 17 节的实际实现状态；更新 `memory/projects/other/CURRENT.md`、`LATEST.md` 及兼容镜像。不把 Skill 创建混入本次代码改造。

- [ ] 生成新的无 Z 示例与四条目标套件；从两次 Ry15 完整 run 构建独立候选前馈和建议 settings，保留旧 artifacts。
- [ ] 用新 CLI 离线加载三份输入生成预览，记录真实输出点数、范围及适用限制。不得执行 `--execute`。
- [ ] 运行新测试、旧 StrokePlan/demo/实验轨迹/记录回归；完整测试报告列明原有失败和环境限制，不能将未跑测试称为通过。
- [ ] 运行 `python scripts/check_docs_layout.py` 和改动检查。
- [ ] 交付新文件路径、脚本内可调参数、离线命令、旧版入口及明确的未实现功能。用户不用操作生成公式；助手可代做离线生成，但不代跑机械臂。

## 确认项

已按用户批准完成本轮代码迁移；新模块与旧 V2 并存，避免破坏现有 ladder、记录和 demo 的调用。下一步可创建生成 Skill，或在独立任务中接入用户采集数据。
