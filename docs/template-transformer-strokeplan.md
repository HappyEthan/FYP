# 标准笔画 StrokePlan + Transformer 生成个性化 StrokePlan 的可行性

## 1. 结论

该思路可行，建议将其定义为：

> 先通过标准化实验建立基本笔画的可执行 StrokePlan 模板库，再从目标字帖图像中识别和分解笔画，根据目标几何、毛笔规格及墨迹特征，对模板进行检索、空间变形和控制参考修正，最终生成适用于该字帖的个性化 StrokePlan。

但模型输出不能被称为原作者唯一真实的动作，因为单幅墨迹图像到书写动作不是一一映射。更准确的说法是：

> 生成一套受标准动作先验约束、能够复现目标字形的可行动作计划。

Transformer 可以作为后续的序列条件生成器。它对系统其他模块的正式输出应当是目标汉字的完整 `StrokePlan`；内部可采用模板检索、几何变形和残差预测来构造该输出，而不必从零直接回归每一个 50 Hz 控制点。

## 1.1 模块接口必须明确

系统级数据流应定为：

```text
目标汉字图像
      ↓
Transformer / StrokePlan Generator
      ↓
该汉字的完整 StrokePlan
      ↓
运行时插值 + 磁触觉反馈控制器
      ↓
逐拍生成 z_cmd 和完整 ServoP 位姿命令
```

因此，Transformer 不输出 `z_cmd`。`z_cmd` 是依赖实时触觉测量的在线控制量，只有机械臂执行时才能计算。

## 2. 总体系统结构

```text
阶段 A：标准笔画数采
基本笔画 + 多组执行参数
        ↓
标准 StrokePlan 模板库

阶段 B：目标字帖分析
字帖图像
  ↓
笔画分割、笔顺推断、中心线和局部图像特征
  ↓
模板检索与几何对齐
  ↓
Transformer/残差模型生成控制修正
  ↓
个性化 StrokePlan
  ↓
Elfin ServoP + 磁触觉闭环执行
  ↓
实际墨迹图像评价与模型更新
```

## 3. 标准 StrokePlan 应采集什么

每个基本笔画不应只有一个固定模板，而应有一定变化范围。建议采集：

\[
\mathcal S=
\{t,s,x,y,g_d,z_{ff},\mathbf q\}
\]

其中：

- `xy`：笔画几何路径；
- `g_target`：目标触觉状态；
- `z_ff`：由触觉标定得到的前馈；
- `orientation_quat`：笔杆倾斜和旋转姿态；
- `t`：速度和节奏；
- `q`：建议用四元数保存姿态。

同时保存执行结果：

```text
StrokePlan 命令
实际 TCP 轨迹
原始磁场 Bx/By/Bz
滤波后触觉状态
实际墨迹图像
毛笔/纸张/墨液元数据
```

这会形成真正可学习的配对：

\[
(\text{StrokePlan},\text{brush metadata})
\longrightarrow
\text{actual ink image}
\]

## 4. 为什么每种笔画只有一个标准模板不够

如果每类笔画只有一个计划，例如“横”只有一个样本，那么模型只能记住模板，无法学习：

- 长短变化怎样影响时间；
- 曲率变化怎样影响姿态；
- 不同目标风格怎样影响触觉参考；
- 不同毛笔长度、笔锋大小怎样改变控制参数；
- 同一计划因软体迟滞产生怎样的结果变化。

因此应围绕标准模板进行受控参数扫描，例如：

```text
长度/尺度
曲率或折角
执行速度
目标触觉等级
倾角
倾斜方位偏置
轴向旋转
毛笔规格
```

不需要穷举所有组合，可以采用正交设计、拉丁超立方或主动学习选择实验点。

## 5. 字帖图像提供什么条件

目标图像可以产生：

- 字符整体布局；
- 每条笔画的目标区域；
- 候选中心线；
- 笔画长度和曲率；
- 局部轮廓、边缘和纹理特征；
- 在先验数据库帮助下推断的笔顺。

模型输入不应只是一张完整字符图。建议先分成逐笔画条件：

\[
\mathbf h_i=
[x_i,y_i,\theta_i,\kappa_i,I_{local,i},s_i]
\]

其中：

- \(\theta_i\)：路径切线方向；
- \(\kappa_i\)：曲率；
- \(I_{local,i}\)：该路径位置附近的图像特征。

再加入全局条件：

\[
\mathbf c=
[\text{stroke type},\text{brush ID},L_{brush},D_{tip},\text{style embedding}]
\]

## 6. Transformer 的正式输出与内部参数化

### 6.1 对外正式输出：完整汉字 StrokePlan

一个汉字的输出应包含有序笔画列表：

```python
CharacterStrokePlan(
    character_id,
    strokes=[
        Stroke(t, s, xy, g_target, orientation_quat),
        Stroke(t, s, xy, g_target, orientation_quat),
        ...
    ],
    meta={...},
)
```

每条笔画至少包含：

- 笔画执行顺序和边界；
- `xy(s)`；
- `t(s)` 或等价速度参考；
- `g_target(s)`；
- `orientation(s)`，若当前版本不启用则为固定姿态。

`z_ff` 建议在生成后根据当前毛笔和传感器的 `calibration_id` 确定性计算并附加到计划：

\[
z_{ff}(s)=f_{cal}^{-1}(g_{target}(s))
\]

它可以存在最终计划文件中供快速执行，但不是网络必须直接预测的量。

### 6.2 模型内部推荐输出：模板参数或残差

模型内部不建议从零直接回归：

```text
50 Hz × 整条笔画的所有 x/y/z/Rx/Ry/Rz
```

这样输出维度大、数据需求高，而且很难保证平滑和安全。

推荐先输出相对于标准模板的低维残差或样条控制点：

\[
\Delta\mathcal S=
\{\Delta g_j,\Delta\alpha_j,\Delta\phi_j,
\Delta\psi_j,\Delta v_j\}_{j=1}^{K}
\]

其中 \(K\) 远小于最终 50 Hz 点数。通过平滑基函数展开：

\[
g_d(s)=g_{template}(s)+\sum_{j=1}^{K}\Delta g_j\beta_j(s)
\]

姿态和速度采用相同思路。最终执行器再把连续参考重采样到 50 Hz。

这叫“模板 + 残差”结构：

\[
\text{personalized plan}
=
\operatorname{Warp}(\text{template},\text{target geometry})
+
\text{learned residual}
\]

这些内部参数经模板展开、平滑、安全约束和重采样后，组装成对外的完整 `CharacterStrokePlan`。因此“残差预测”和“输出整个字的 StrokePlan”并不矛盾：前者是实现方法，后者是模块契约。

## 7. XY 与控制参考应分开处理

### XY 几何

先从目标字帖提取中心线，再把标准模板通过弧长和样条变形对齐：

\[
\mathbf p_{base}(s)
=
\operatorname{Warp}
(\mathbf p_{template}(s),\mathbf p_{target}(s))
\]

Transformer 只预测小的几何残差：

\[
\mathbf p_d(s)
=
\mathbf p_{base}(s)+\Delta\mathbf p(s)
\]

### 触觉和姿态

由标准模板提供基础曲线：

\[
g_d(s)=g_{template}(s)+\Delta g(s)
\]

\[
\mathbf R_d(s)
=
\mathbf R_{template}(s)\oplus\Delta\mathbf R(s)
\]

网络不应输出最终 `z_cmd`。正确链路是：

\[
g_d\rightarrow z_{ff}=f_{cal}^{-1}(g_d)
\]

\[
z_{cmd}=z_{surface}+s_z(z_{ff}+z_{fb})
\]

其中 `z_fb` 由真机触觉闭环在线产生。

## 8. 最大的数据问题：逆映射不唯一

只收集：

```text
标准笔画名称 → 一个标准 StrokePlan
```

无法监督：

```text
任意字帖图像 → 独有 StrokePlan
```

因为训练集中没有“这个目标图像应该对应哪个动作”的标签。

可采用两种解决办法。

### 方案 A：直接配对数据

用机器人执行大量已知 StrokePlan，并拍摄结果：

\[
(\mathcal S_k,I_k)
\]

然后训练条件逆模型：

\[
G(I_{target},\mathcal S_{template})
\rightarrow
\Delta\mathcal S
\]

### 方案 B：先学习前向模型，再做优化

先学习：

\[
F(\mathcal S,\text{brush metadata})
\rightarrow
\hat I
\]

生成目标计划时求解：

\[
\mathcal S^*
=
\arg\min_{\mathcal S}
L(F(\mathcal S),I_{target})
\]

前向模型通常比直接逆模型更符合物理因果，并能显式处理多解。Transformer 可以用于表示序列模型或生成优化初值。

## 9. 毛笔规格如何进入模型

毛笔长度和笔锋大小不能只用于缩放 XY。建议作为条件元数据：

```yaml
brush_id: ...
total_length_m: ...
hair_length_m: ...
tip_diameter_m: ...
sensor_mount_id: ...
calibration_id: ...
```

模型条件可以写为：

\[
\mathcal S^*
=
G(I_{target},\mathcal S_{template},\mathbf b)
\]

其中 \(\mathbf b\) 是毛笔参数向量。

注意：更换毛笔或传感器装配后，`g_target → z_ff` 的标定也可能变化，因此 `calibration_id` 必须和生成的计划绑定。

## 10. Transformer 是否是最佳起点

Transformer 适合：

- 可变长度笔画序列；
- 长距离上下文；
- 多笔画之间的结构条件；
- 图像特征到序列控制参数的映射。

但第一阶段不一定比规则、样条和小型 MLP 更好。如果数据量有限，Transformer 容易记忆模板而不是真正学习毛笔动作。

推荐的模型演进是：

1. 模板检索 + 确定性几何变形；
2. 模板 + 少量可调参数；
3. 小模型预测低维残差；
4. 数据足够后使用 Transformer 预测残差序列；
5. 用实际墨迹反馈继续微调或优化。

## 11. 推荐的实验闭环

```text
目标字帖图像 I_target
        ↓
生成候选 StrokePlan S_k
        ↓
机器人执行（磁触觉在线闭环）
        ↓
拍摄实际墨迹 I_k
        ↓
计算视觉损失 L(I_k, I_target)
        ↓
更新低维计划参数
```

磁触觉闭环解决每次执行中的接触稳定性；视觉反馈解决生成的 StrokePlan 是否真正产生目标外观。这两个闭环作用不同，不能互相替代。

## 12. 建议的项目阶段

### P0：执行基础

- 圆形验证 ServoP 和磁触觉 Z 闭环；
- 固定姿态、恒定 `g_target`。

### P1：标准笔画模板库

- 选择少量基本笔画；
- 定义并标定标准 StrokePlan；
- 每个模板包含 XY、时间、触觉和姿态。

### P2：模板几何迁移

- 从字帖提取逐笔中心线；
- 将标准模板变形到目标长度和形状；
- 不使用神经网络，建立可解释基线。

### P3：参数扫描数据集

- 系统改变触觉、速度、倾角等参数；
- 执行并拍摄实际墨迹；
- 建立命令—触觉—图像配对数据。

### P4：学习残差生成器

- 输入目标笔画图像、模板和毛笔参数；
- 输出少量 StrokePlan 残差控制点；
- 与模板迁移基线比较。

### P5：整字生成

- 处理多笔画顺序、空间布局和笔间安全移动；
- 底层仍逐条执行统一 StrokePlan。

## 13. 最终判断

你的方向具备研究价值，也能自然连接：

```text
字帖图像理解
标准笔画动作先验
个性化 StrokePlan 生成
磁触觉闭环执行
视觉结果评价
```

真正需要修改的不是总体思路，而是把“一个标准模板直接训练 Transformer”改成：

> 标准模板库提供动作先验；机器人参数扫描提供计划—墨迹配对数据；图像模型和 Transformer 只生成相对模板的低维、安全、平滑修正；磁触觉闭环负责在线执行。

这样既避免从单图像声称恢复唯一真实动作，也能逐步提高对不同字形、笔画长度和毛笔规格的适应能力。
