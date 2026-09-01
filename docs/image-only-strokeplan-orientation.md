# 只有网上字帖图像时，StrokePlan 的笔杆方向如何确定

## 1. 首先确定问题性质

当系统只有一张书写完成后的字帖图像，没有人的书写视频、笔杆位姿、触觉记录或动作示范时，图像能够较可靠提供：

- 汉字的二维轮廓；
- 笔画中心线的候选；
- 笔画连接关系；
- 在先验规则帮助下推断出的可能笔顺。

但图像不能唯一提供：

- 笔杆倾斜角；
- 倾斜的空间方向；
- 绕笔杆轴旋转角；
- 书写速度；
- 目标磁触觉状态；
- 毛笔在每个位置的变形历史。

原因是从动作到墨迹是多对一映射：

\[
I=F(x,y,g,\mathbf R,v,\text{brush},\text{ink},\text{paper})
\]

不同的 \(g,\mathbf R,v\) 组合可能形成相似的最终图像，因此反问题：

\[
I\longrightarrow (x,y,g,\mathbf R,v)
\]

没有唯一解。

所以项目目标应准确表述为：

> 从字帖图像提取视觉约束，并合成一套机器人可执行的 StrokePlan，使机器人的最终书写结果尽可能接近目标字帖。

不应表述为“从单张图像恢复原作者真实的笔杆姿态”。

已有图像轨迹提取研究通常从字形图像骨架化并结合笔顺知识生成 B-spline 中心线和压力信息，而不是从单幅图像直接测得真实三维笔杆姿态。近年的 CalliRewrite 也把输出描述为从图像恢复“plausible”书写行为，并用虚拟毛笔与强化学习寻找可行轨迹，这同样说明输出是合理假设而不是唯一真值。

## 2. 不使用笔宽到 Z 映射后的直接后果

本项目选择用触觉信号代替：

\[
\text{笔画宽度}\rightarrow Z
\]

这是合理的控制选择，但目标触觉信号 \(g_d(s)\) 仍然需要来源。单张图像不能直接测得 \(g_d(s)\)。因此需要在以下方法中选择：

1. 预定义触觉模板；
2. 基于路径几何的规则生成；
3. 机器人试写后的视觉优化；
4. 将来使用带过程信息的数据集训练图像到动作的模型。

也就是说，触觉能够替代笔宽到 Z 的控制映射，但不能替代 StrokePlan 目标值的生成过程。

## 3. 当前最合理的笔杆方向策略

建议把姿态从“图像中提取的真值”改成“姿态规划器生成的隐变量”。

姿态规划器输入：

\[
x(s),y(s),\kappa(s),\text{stroke connectivity}
\]

输出：

\[
\alpha(s),\phi(s),\psi(s)
\]

其中：

- \(\alpha\)：笔杆相对纸面法线的倾斜角；
- \(\phi\)：倾斜方向在纸面上的方位角；
- \(\psi\)：绕笔杆轴的旋转角。

### 3.1 用路径切线定义方向基准

路径切线方向为：

\[
\theta(s)=\operatorname{atan2}\left(\frac{dy}{ds},\frac{dx}{ds}\right)
\]

可以定义倾斜方位：

\[
\phi(s)=\theta(s)+\delta
\]

其中 \(\delta\) 是一个可实验选择的相对角：

- \(\delta=0\)：向运动方向倾斜；
- \(\delta=\pi\)：向运动反方向倾斜；
- \(\delta=\pm\pi/2\)：向轨迹法向倾斜。

这不是在恢复原作者姿态，而是在建立一个与路径方向一致、可重复验证的机器人姿态规则。

### 3.2 第一版使用固定倾角

先令：

\[
\alpha(s)=\alpha_0
\]

其中 \(\alpha_0\) 从安全的小角度开始。这样只让倾斜方向随路径方向变化，而倾斜幅度保持不变，减少实验变量。

### 3.3 高曲率区域平滑调整

在折角和高曲率区域，\(\theta(s)\) 可能快速变化。不能逐点直接把姿态对准切线，否则机器人姿态会产生突变。

应对 \(\phi(s)\) 解包并平滑：

\[
\tilde\phi(s)=\operatorname{smooth}(\operatorname{unwrap}(\theta(s)+\delta))
\]

并限制角速度和角加速度：

\[
|\dot\phi|\leq\omega_{max},\qquad
|\ddot\phi|\leq a_{\phi,max}
\]

折角处同时降低 XY 路径速度，使姿态调整和位置运动保持同步。

### 3.4 轴向旋转先保持常数

如果毛笔和触觉结构近似轴对称，仅凭最终墨迹很难确定 \(\psi(s)\)。因此第一版应令：

\[
\psi(s)=\psi_0
\]

不要人为生成复杂的轴向旋转。只有当固定 \(\psi\) 明确无法得到需要的结果，并且系统建立了可重复的旋转实验后，再把它加入优化变量。

## 4. 建议的三级姿态方案

### Level 0：固定姿态基线

\[
\alpha=0,\quad \phi=0,\quad \psi=\psi_0
\]

用途：完成圆形和第一版汉字的 XY + 触觉 Z 闭环验证。

### Level 1：切线相关的规则姿态

\[
\alpha=\alpha_0,qquad
\phi=\operatorname{smooth}(\theta+\delta),qquad
\psi=\psi_0
\]

用途：验证倾斜方向随书写方向变化是否改善折角和笔锋稳定性。

### Level 2：试写—评价—优化

把姿态和触觉计划参数化为少量控制点：

\[
\boldsymbol\eta=
[\alpha_1,\ldots,\alpha_K,
\delta_1,\ldots,\delta_K,
g_1,\ldots,g_K]
\]

机器人试写后拍照，计算目标图像和实际图像差异：

\[
L(\boldsymbol\eta)
=
\lambda_1L_{shape}
+\lambda_2L_{skeleton}
+\lambda_3L_{edge}
+\lambda_4L_{smooth}
\]

然后使用无梯度优化、贝叶斯优化或强化学习更新参数：

\[
\boldsymbol\eta_{k+1}
=
\operatorname{Optimizer}\left(
\boldsymbol\eta_k,L_k
\right)
\]

这条路线不需要人的姿态数采，但需要机器人反复试写和拍照。最终得到的是“能让机器人写得像目标字帖的姿态”，不是原作者真实姿态。

## 5. 触觉目标也应采用同样思路

既然没有示范触觉数据，第一版可以对每条连续笔画设置：

\[
g_d(s)=g_0
\]

随后在折角实验中使用少量参数化变化，例如：

\[
g_d(s)=g_0+\sum_{j=1}^{K}c_j\beta_j(s)
\]

其中 \(\beta_j(s)\) 是平滑基函数。通过试写结果优化 \(c_j\)，而不是让神经网络一次输出每个采样点的任意值。

参数维度越低，真实机器人上的搜索越安全、样本效率越高，也更容易解释触觉反馈的作用。

## 6. StrokePlan 应保存“值”和“来源”

建议数据字段为：

```python
Stroke(
    t,
    s,
    xy,
    g_target,
    z_ff,
    orientation_quat,
)
```

同时在 metadata 中记录：

```yaml
xy_source: image_skeleton
stroke_order_source: database_or_inference
g_target_source: constant_template_or_optimized
orientation_source: fixed_or_tangent_rule_or_optimized
orientation_confidence: low
```

这样不会把算法合成出来的姿态误标成从字帖中直接测得的真实姿态。

## 7. 从方向参数得到完整姿态

假设纸面法线为：

\[
\mathbf n=[0,0,1]^T
\]

由倾角 \(\alpha\) 和方位角 \(\phi\) 构造笔杆方向：

\[
\mathbf b=
\begin{bmatrix}
\sin\alpha\cos\phi\\
\sin\alpha\sin\phi\\
-\cos\alpha
\end{bmatrix}
\]

再结合轴向旋转 \(\psi\) 构造旋转矩阵或四元数。沿路径生成的四元数必须保持符号连续，并用 SLERP 重采样到 Elfin 的 50 Hz ServoP 时间轴。

## 8. 为什么不建议直接训练“图像到姿态网络”

在没有姿态标签、没有可验证的笔杆模型、也没有机器人试写闭环数据时，网络没有明确监督目标。它可能输出平滑角度，但无法证明这些角度对应正确书写动作。

图像到动作研究通常至少引入以下一种额外约束：

- 书法规则；
- 虚拟毛笔模型；
- 机器人试写反馈；
- 姿态或动作标签；
- 强化学习环境。

因此当前更合理的是先做低维、可解释的姿态规划器，再根据真实试写结果决定是否升级为学习方法。

## 9. 与现有研究的关系

早期轨迹提取方法主要通过字形骨架、笔顺知识和 B-spline 生成中心线及压力计划，而不是从最终图像唯一恢复笔杆姿态。[Yao 等，2004](https://doi.org/10.1016/j.engappai.2004.08.008)

Guo 2026 将二维骨架、Z 压入和五次时间规划组合为三维位置轨迹，但倾角和旋转仍主要停留在规则框架层面，并非完整可复现的六维姿态算法。[Guo 等，2026](https://link.springer.com/article/10.1007/s44196-026-01222-1)

CalliRewrite 从单幅字帖图像恢复的是“合理的”书写顺序和动作，并依赖虚拟毛笔及强化学习细化轨迹，而不是声称观测到原作者唯一真实动作。[CalliRewrite](https://arxiv.org/abs/2405.15776)

已有图像到动作系统也会把倾斜/旋转角作为待生成或学习的动作变量，而不是把它们当作能够从单张图像直接测量的量。[Image-to-Action/HGN 系统](https://scholar.lib.ntnu.edu.tw/en/publications/a-chinese-calligraphy-writing-robotic-system-based-on-image-to-ac/)

## 10. 本项目的定稿建议

在没有人类动作数采的条件下，采用以下定义最稳妥：

> XY 和笔画结构由网上字帖图像提取；目标触觉和笔杆姿态由可解释的计划器生成；机器人试写图像用于逐步优化计划器参数。StrokePlan 保存的是一套可执行的合成动作，而不是原作者真实动作的测量记录。

当前优先顺序：

1. 固定姿态 + 常数触觉目标，建立基线；
2. 切线相关倾斜方向 + 固定倾角；
3. 折角处姿态平滑和降速；
4. 机器人试写后的低维参数优化；
5. 最后才考虑轴向旋转和图像到动作网络。
