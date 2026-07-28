# Z 控制 Phase 0：整體 ΔB 跟蹤控制

> 設計日期：2026-07-28
> 狀態：設計
> 關聯：`docs/deltaB-control.md`（ΔB 空間控制）、`docs/gate-experiments.md`（E0–E5）、`docs/handoff-z-control.md`（交接文檔）
> 先決條件：MuJoCo 已通、`contact_sim.py` 可跑、V0 數據集存在

---

## 1. 為什麼是 Phase 0

Phase 0 的核心命題是：

> **在「不分解 ΔB、不追究壓/拖來源」的前提下，控制 Z 軸能否讓測量信號跟上目標信號？**

若能：

- 證明傳感器環路閉得上
- 證明控制器結構（前饋 + 積分）在書法場景中有效
- 給出整組基線參數（Kp、Ki、限幅、抗飽和）——後續 Phase 1/2 直接沿用

若不能（跟蹤不收斂、或收斂但誤差過大），這將是最便宜的失敗——不等硬體就找出控制架構的結構性問題。

### 與 Phase 1/2 的關係

| 階段 | 策略 | 何時需要 |
|---|---|---|
| **Phase 0（當前）** | 整體跟蹤，\|ΔB\| 標量誤差 | 同筆復現、基線建立 |
| **Phase 1** | 弧長 s + 垂距 d⊥ 分解 | 寫新字、壓拖交叉干擾明顯時 |
| **Phase 2** | 學習式前饋 + 遲滯補償 | 遲滯不可忽略、需泛化多字 |

---

## 2. 控制律

```
z_cmd(t) = z_surface + z_ff(|ΔB_d(t)|) + Kp · e(t) + Ki · ∫e(t) dt
```

### 各項詳解

**z_surface**：紙面高度常量，取自 `config.PAPER_Z = 0.20 m`。

**z_ff(g)**：前饋——「想要多少 |ΔB| → 壓到哪個 z」。來源為 E2 標定曲線 C 的逆映射：

```python
# 標定檔格式：(z_mm, |ΔB|_array) 的兩列
z_ff = np.interp(g_target, abs_dB_array, z_mm_array)
```

Phase 0 先用 `contact_sim.py` 的合成標定曲線（純 numpy 無需硬體），真機到位後只需替換標定檔。

**e(t) = |ΔB_d(t)| − |ΔB_meas(t)|**：誤差信號。選**標量**而非三軸向量的理由：

1. 方向分量被拖拽污染——標量對拖拽的敏感度最低
2. Phase 0 的目的是證明「環路能閉上」，不需方向信息
3. 標量讓 Kp/Ki 的整定更直觀（只有大小，沒有方向權重問題）

**Kp、Ki**：可調參數。初始值需通過仿真標定，規則：

- 在 S(z) 最大的工作點整定 Kp（保證全域穩定）
- Ki 設為低增益（前饋為主，反饋只補殘差）

### 工程保護

| 機制 | 實現 |
|---|---|
| **z_fb 限幅** | `np.clip(z_fb, -DZ_MARGIN, +DZ_MARGIN)`，預設 ±3 mm |
| **z_cmd 限幅** | `np.clip(z_cmd, Z_MIN, Z_MAX)`，預設紙面上下各 5 mm |
| **抗積分飽和** | back-calculation：`z_fb += Ki · e · dt + K_aw · (z_fb_limited − z_fb) · dt` |
| **接觸判別** | `\|ΔB_meas\| < 3 × NOISE_STD` → 懸空 → 凍結積分、歸零 z_fb |
| **抬筆凍結** | 目標 `\|ΔB_d\| < CONTACT_THRESHOLD` → 凍結積分（筆未觸紙時誤差無意義） |
| **拖拽監控** | 預留介面 `d_perp()`，Phase 0 不啟用 |

### ZController 介面

Phase 0 的標定數據（C 曲線）由調用方直接傳入陣列，不依賴文件。後續階段可改為從 CSV 載入。

```python
class ZController:
    def __init__(self, calib_z_mm: np.ndarray, calib_dB: np.ndarray,
                 dt: float = 0.01, kp: float = 0.5, ki: float = 0.1,
                 dz_margin: float = 3e-3, noise_std: float = 7e-6):
        """calib_z_mm: (N,) 壓深 mm；calib_dB: (N, 3) 或 (N,) 對應 |ΔB| μT。"""

    def step(self, dB_meas: np.ndarray, g_d: float) -> float:
        """單步計算 z_cmd (m)。dB_meas: (3,) μT；g_d: 目標 |ΔB| 標量 μT。
           若 g_d 超出標定範圍 → np.clip 到邊界值（飽和保護）。"""

    def reset(self):
        """重置積分器。"""

    @property
    def z_ff(self) -> float:
        """當前前饋分量，用於調試/可視化。"""

    @property
    def z_fb(self) -> float:
        """當前反饋分量，用於調試/可視化。"""
```

---

## 3. 測試策略

### 3.1 單測（`tests/test_z_control.py`）

| 測試 | 內容 |
|---|---|
| `test_step_tracks_constant` | 固定目標，步進後誤差收斂到 ±5% |
| `test_reset_clears_integrator` | reset 後反饋項歸零 |
| `test_z_fb_clamping` | 超限後反饋被限幅，退飽和啟動 |
| `test_lift_freezes_integrator` | 目標 |ΔB| < 閾值時積分凍結 |
| `test_air_freezes_integrator` | 測量 |ΔB| < 3σ 時積分凍結 |
| `test_z_ff_interpolation` | 前饋插值在標定範圍內連續 |

### 3.2 端到端驗證（`scripts/demo_z_control.py`）

用 `contact_sim.py` 跑完整的閉環仿真：

```
1. 生成合成標定曲線 C: contact_sim 逐檔壓入 → (z, |ΔB|)
2. 建立 z_ff = interp(|ΔB|, z)
3. 加載 V0 line_lr 的 |ΔB(t)| 為目標曲線
4. 閉環控制 + contact_sim 物理響應 → 記錄 z_cmd(t)、|ΔB_meas|(t)
5. 輸出三面板圖：
   - 上：目標 |ΔB_d| vs 測量 |ΔB_meas|
   - 中：z_cmd 分解（z_ff + z_fb）
   - 下：誤差 e(t)
```

### 3.3 驗收判據

| 指標 | 期望 | 硬限制 |
|---|---|---|
| 穩定跟蹤誤差（RMS） | < 5% 目標量程 | < 10% |
| 收斂時間（從懸空到接觸的初始誤差） | < 0.5 s | < 1.0 s |
| z_cmd 無高頻振盪 (>5 Hz) | ✅ | 模態必須衰減 |
| 積分限幅後無 windup 引發過衝 | ✅ | Reset/Catch 測試 |

---

## 4. 合成標定曲線 C

### 4.1 來源

修改 `contact_sim.py` 的 `run()` 輸出格式，使其輸出可用於 `z_ff` 的標定表：

```python
# contact_sim_ calibrate() 返回
#   z_mm: 壓深 array (mm)
#   abs_dB: 對應的 |ΔB| array (µT)
#   dB: 三軸 ΔB array (N, 3)
```

### 4.2 合成曲線的誠實邊界

| 可以信任的 | 不可以信任的 |
|---|---|
| 單調性、大體趨勢 | 絕對 S 值 |
| 壓深 vs 彎曲的結構關係 | 真實 µT 比例 |
| 方向可分性的定性結構 | 遲滯回環 |

合成曲線的目的是讓控制器的**邏輯正確性**得到驗證，不是替代真機 E2。

---

## 5. 文件變動

| 文件 | 動作 | 內容 |
|---|---|---|
| `src/brushbot/z_control.py` | **新建** | ZController 類（純 numpy，無 GUI 依賴） |
| `tests/test_z_control.py` | **新建** | 6 項單測，全無 GUI |
| `scripts/demo_z_control.py` | **新建** | 閉環仿真 Demo，出圖 |
| `src/brushbot/tactile/contact_sim.py` | ⚠️ **小改** | 加 `calibrate()` 函數輸出標定表 |
| `pyproject.toml` | *不變* | 零新依賴 |

---

## 6. 風險與緩解

| 風險 | 影響 | 緩解 |
|---|---|---|
| **合成 C 曲線與真機 S 差太多** | z_ff 偏大/偏小，反饋負擔重 | 反饋有 Ki 補償，且真機 E2 後直接替換標定檔 |
| **contact_sim 無法產生合理的時變目標** | 缺 demo 數據 | 用 V0 數據集的 |ΔB(t)| 序列 |
| **ZController 的 dt 與仿真 dt 不一致** | 積分步長錯 → 增益偏 | dt 由調用方傳入，一致即可 |
| **MuJoCo 回放時 XY 軌跡偏差導致拖拽干擾超預期** | 跟蹤誤差大 | 先在 contact_sim（無 XY 偏差）中驗證，再逐步加干擾 |

---

## 7. 輸出承諾

Phase 0 完成時將交付：

1. `ZController` 類 + 完整單測（全部通過）
2. `demo_z_control.py` 腳本：跑通後生成 `z_control_demo.png`

   預期看到的圖：目標 |ΔB_d| 曲線與測量 |ΔB_meas| 基本重合，誤差在 ±5% 內。

3. 合成標定曲線 C 的 CSV 檔案（供後續 Phase 使用）
4. 一組初始 Kp/Ki 參數
