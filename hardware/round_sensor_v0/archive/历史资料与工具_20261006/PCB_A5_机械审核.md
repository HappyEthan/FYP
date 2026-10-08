# A5 机械审核 · U2 封装修订

> 保留的专题审查依据，并非当前工作入口。历史数量、坐标、状态和待办以 [最新交接](CAD_HANDOFF.md) 为准；旧附件如已移出，按 [清理清单](清理清单_20260918.json) 从废纸篓恢复。本轮未重做本专题审核。

2026-09-16。**U2错误节距已修正，原理图绑定和PCB原生保存/重开回读通过；仍未布线，不可投板。** 仅U2焊盘/工艺图形替换并向内微移0.10 mm，其他40元件、网络和过孔保持不变。

## 本轮交付与证据

- [双面机械空间审核图](easyeda_std/PCB_A5_机械空间审核.svg)：基于最新MLX修订版 PCB 的真实铜和坐标，加上厂家本体尺寸及明确标注的暂定操作区。底面采用顶视投影，方便空间对照，不是翻板安装视图。
- [可复算机械审核数据](easyeda_std/pcb_a5_mechanical_audit.json)：输入 SHA256、USB 配准、38 个本体/外包示意、3 组裸焊盘、封装差异和未确认项。
- 图中蓝色本体已读取厂家图纸；灰色阻容是未选定具体料号的标称尺寸，不是最大尺寸保证。C30/C31 为不装配预留。

## 1. 已修正：MLX90393 专用封装

型号为 MLX90393SLQ-ABA-011-RE，使用 UTDFN-8。厂家第39页图28给出端子节距 **0.40 mm**；此前`PCB_A5_18mm_readable_20260916.json`误用0.50 mm通用库。现已建立并保存`MLX90393_LQ_8_EP_P040_A5_R1`，库UUID为`458c2df684cd430ca5cf847a7b530b0e`；1到4脚跨度已改为1.20 mm。

此前“封装管理器41项绿色”只证明符号脚号与焊盘编号匹配，**不证明实际端子尺寸正确**。本次重新核对厂家第40页顶视脚序；库顶视1脚左上、1–4左侧向下、5–8右侧向上，等价于该厂家图顺时针旋转90°。底层实例只镜像X一次；EP为9脚GND，3脚仍NC；未沿用错误第三方3D模型。固件敏感轴定义和装机校准仍需单独验证。

外围铜焊盘0.60×0.20 mm，横向中心±1.20 mm，竖向节距0.40 mm；EP铜1.30×1.55 mm。外围铜间隙0.20 mm，外围至EP铜间隙0.25 mm。外围长度按名义引脚内沿0.90 mm、外沿1.50 mm推导，对最大半本体1.30 mm外伸0.20 mm。

EP默认锡膏关闭，单独设置6个0.40×0.40 mm方孔，面积覆盖约47.6%；外围暂按约0.10 mm钢网、1:1开口。两整排0.70×1.50 mm阻焊开窗，EP单边外扩0.05 mm。**这些是依据厂家通用SMT指南推导的工程设计值，不是厂家直接给出的本型号精确推荐焊盘。** 全板WLCSP/细间距兼容性、钢网实际输出和贴片工艺仍需审核。

新外围焊盘在原位置与C2仅剩约0.13 mm间距，因此仅将U2中心从(3.70,3.60)改为(3.60,3.60) mm，现最小间距约0.23 mm。原生DRC重新核对：116项未布线连接和1项原有Q1间距错误；未放宽规则。PCB已保存、关闭重开并下载，详见 [原生几何与网络核验](easyeda_std/mlx90393_native_verification.json)。原理图生成脚本也已锁定新库引用，避免重建回退。

依据：:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/mlx90393.pdf" purpose="source"} 第39页图28及第40页图29。

焊接设计依据：:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/melexis_smt_guidelines.pdf" purpose="source"} 第9、25–26页。

## 2. USB：接口开口基本在圆板最前端，但外壳角落伸出圆周

**用户已确认的取舍（2026-09-16）：接受USB金属外壳局部伸出圆板，由3D打印笔杆的侧开孔及装配结构解决；不单独因为此外伸扩大圆板，也不把此外伸作为继续PCB设计的阻塞项。** 优先保证USB正常使用：插头可完整插入、插拔时接口和PCB有可靠支撑；数据通信、供电及充电路径仍需完成电气审核和样板测试。接受外伸不等于已经通过功能或装配验证，也不取消焊盘、固定脚、板边距离及必要布线空间。

本版 USB4105 封装的原生定位点不是金属外壳中心，不能直接把本体矩形画在该定位点上。用原生四个 SH 焊盘与厂家图配准，并用信号焊盘行、两个定位孔交叉检查，得到：

| 项目 | 本轮结果 |
|---|---|
| 名义外壳 | 8.94 × 7.35 mm，高3.31 mm |
| 外壳中心，PCB圆心为零点 | (0, −5.35247) mm |
| 相对原生元件定位点偏移 | y约−1.30247 mm |
| 开口线 | y约−9.02747 mm，朝−y插入 |
| 圆板最前端 | y=−9 mm，接口名义外伸约0.027 mm，不代表有足够公差裕量 |
| 外壳前角到圆心 | 约10.074 mm，超过圆板半径约1.074 mm |
| 信号行/定位孔配准残差 | 约0.00012 / 0.00005 mm；这是坐标匹配，不是实物加工精度 |

若用完全无侧孔的同心圆筒包住整个USB外壳，名义内径几何下限约20.15 mm，尚未加公差。**这不是推荐把板子或整根笔杆扩大到20.15 mm**：可设计局部侧开孔，让USB金属外壳伸入开口区域；还需考虑板子如何装入，可能采用分体壳、可拆侧盖或其它装配路径。

仅作算例：18 mm板径、径向装配间隙0.25 mm、壁厚1.0 mm，对应内径18.5 mm、外径20.5 mm，接口相对最前外壁内缩约1.223 mm。厂家配合示意图中的尾壳高度上限为6.5 mm，完全插入时尾壳至母座前端最小距离为1.85 mm。这个一维算例不能证明某根USB线一定能插入；仍缺尾壳宽度、圆弧侧壁、插入公差及开孔位置。

另须选定USB壳脚长度（0.60/0.95/1.20 mm）及PCB厚度，检查底面凸出、焊锡和底面器件净空。没有把孔/铜不越界当成实物装配通过。

依据：:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/usb4105.pdf" purpose="source"} 第1页，及 [GCT官方产品资料](https://gct.co/connector/usb4105)。

## 3. 本体尺寸和高度依据

以下平面尺寸按当前PCB方向排布；最大尺寸不含所有装配与焊料公差。

| 位号 | 本版图示尺寸 / 高度 | 依据与边界 |
|---|---|---|
| U1 PICO | 7×7 mm，最大7.1×7.1 mm；最大高1.06 mm | Espressif第30页 |
| U2 MLX | 当前方向2.5×2.0 mm，最大2.6×2.1 mm；最大高0.40 mm | 节距已修为0.40 mm，制造工艺未放行 |
| U3 IMU | 当前方向3.0×2.5 mm，最大3.1×2.6 mm；最大高0.86 mm | ST DS12814 Rev4第160页；不以首页0.83 mm标称值作为最大高度 |
| U4 充电 | 0.922×1.155 mm；最大高0.588 mm | WLCSP本体图 |
| U5 稳压 | 2×2 mm，最大2.1×2.1 mm；最大高0.8 mm | DRV0006A |
| U6 USB保护 | 本体0.8×1.0 mm；最大高0.5 mm | DRT图；引脚和飞边不包含在该本体矩形内 |
| Q1 / D4 | 1.0×0.6 mm，最大1.05×0.65 mm；最大高0.53 mm | LRC各自尺寸图 |
| ANT1插座 | 保守外包3.0×3.1 mm；未扣线高1.25 mm | 信号侧外伸已计入外包中心偏移，不是扣合后总高度 |
| 小阻容、D1–D3 | 标称尺寸示意 | 具体料号、公差和部分高度未冻结 |

已核图本体没有直接当作自动布局禁布规则。当前二维名义同面本体未发现明显交叠；C4至IMU本体间距约0.20 mm，公差、装配和返修空间还要复核。正反面可以在投影上重叠，但贯穿孔、USB壳脚、底部焊锡及夹具不能忽略。

尺寸图：:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/esp32-s3-pico-1.pdf" purpose="source"}；[ST官方IMU尺寸图，第160页](https://www.st.com/resource/en/datasheet/lsm6dsox.pdf)；:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/sgm40567.pdf" purpose="source"}；:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/tlv755p.pdf" purpose="source"}；:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/tpd2eusb30a.pdf" purpose="source"}；:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/lp0404n3t5g.pdf" purpose="source"}；:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/lmbr4010bst5g.pdf" purpose="source"}。

## 4. 天线、导线和测试口

- ANT1的紫圈半径2 mm只是垂直扣合操作空间提示，未确认工具外形；不能理解为厂家的禁布尺寸或已满足返修空间。
- 当前天线候选 FXP75.07.0045B 的FPC名义5.9×4.1×0.24 mm，图纸公差上限约6.2×4.4×0.34 mm；线长标称45 mm、线径0.81 mm。线端接头约5.2±0.5 × 3.0±0.2 mm，明显不止板上插座的范围。
- 还需确认实际I-PEX MHF I线端与Hirose插座配合后的高度、线端相对扣合中心的偏移、线缆弯曲半径及沿笔杆轴向转弯。不能拿任意Hirose线端的扣合高度替代所选Taoglas线端的组合实测。
- FPC贴在壳内、不是圆PCB上的另一块占板元件。电池与手握状态下的射频表现、贴附位置、磁传感器偏置都尚未验证。
- J2/SW1为手焊导线焊盘，J3为测试焊盘，不是板载实体开关/插座。紫框是铜边外扩0.5 mm的提示，尚未确定导线规格、线头高度、应力释放及探针夹具外径。

依据：:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/Hirose_U.FL_catalog.pdf" purpose="source"} 第12、33页；:codex-file-citation{path="/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0/references/FXP75.07.0045B.pdf" purpose="source"} 第5页；[Taoglas官方产品页](https://www.taoglas.com/product/atom-fxp75-2-4ghz-flex-super-micro-pcb-antenna/)。

## 下一步与复算

1. 复核其余复用封装，处理Q1间距与全板钢网/阻焊工艺，不仅看脚号“全绿”。U2几何修正已完成，不要整板重新转换而覆盖既有实例修正。
2. 以修正后的器件外形继续布局，确定USB侧孔与装壳方式、天线扣合/导线通道，再检查电源方案和布线可达性。
3. 实际线缆、电池、开关和打印参数选定后才输出壳体加工尺寸；本轮不冻结笔杆内径或最终板径。

```sh
python3 hardware/round_sensor_v0/scripts/check_pcb_a5_mechanical.py
python3 hardware/round_sensor_v0/scripts/test_pcb_a5_mechanical.py
```
