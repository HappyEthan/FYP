"""把 ΔB 数据集打包成一个自包含的交互式回放 HTML(离线可开, 无外部依赖).

    python scripts/make_replay.py delta_b_v0_20260724 deltab_replay.html

页面内容:
  - 三轴 ΔBx/ΔBy/ΔBz 随时间(带播放游标 + 动作窗阴影)
  - 形变量 |ΔB| / 面内 |ΔBxy| 随时间
  - 形变方向: 面内方位角 φ=atan2(dBy,dBx) 与 极角 θ=∠(ΔB, +z) 随时间
  - ★ 坐标系里的点: ΔB 向量末端在 3D 中的位置(可拖拽旋转) + XY 平面罗盘, 都带拖尾
  - 播放/暂停/拖动进度/变速/切换记录
"""
import sys, os, json, glob
import numpy as np


def load(folder):
    recs = []
    for csv in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        jf = csv.replace(".csv", ".json")
        if not os.path.exists(jf):
            continue
        j = json.load(open(jf))
        if j.get("valid") is False:
            continue
        d = np.genfromtxt(csv, delimiter=",", names=True)
        B = np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]]
        w = j.get("action_window_s") or {}
        recs.append(dict(
            action=j["action"],
            t=[round(float(v), 4) for v in d["t_s"]],
            x=[round(float(v), 2) for v in B[:, 0]],
            y=[round(float(v), 2) for v in B[:, 1]],
            z=[round(float(v), 2) for v in B[:, 2]],
            win=[w.get("start"), w.get("end")] if w else None,
            fs=round(float(j.get("mean_sample_rate_hz", 100.0)), 2),
            B0=[round(j["baseline_B0_uT"][k], 1) for k in ("Bx_uT", "By_uT", "Bz_uT")],
            note=j.get("note", ""),
        ))
    return recs


HTML = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ΔB 回放 · 形变量与形变方向</title>
<style>
:root{--bg:#0e1116;--panel:#161b22;--line:#2b3442;--fg:#e6edf3;--dim:#9aa7b5;
      --x:#4aa3ff;--y:#ffa64a;--z:#b6bfcc;--m:#ff4d6d;--acc:#3fb950}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.5 system-ui,-apple-system,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;
       gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:17px;margin:0;font-weight:600}
.sub{color:var(--dim);font-size:12px}
.wrap{padding:14px 18px;max-width:1500px;margin:0 auto}
.recs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.recs button{background:var(--panel);color:var(--fg);border:1px solid var(--line);
  border-radius:7px;padding:7px 13px;cursor:pointer;font-size:13px}
.recs button.on{border-color:var(--acc);color:var(--acc);background:#12261a}
.ctl{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px;
     background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:10px 13px}
.ctl button{background:#21262d;color:var(--fg);border:1px solid var(--line);
  border-radius:6px;padding:6px 14px;cursor:pointer;min-width:66px}
.ctl button:hover{border-color:var(--acc)}
input[type=range]{flex:1;min-width:220px;accent-color:var(--acc)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:11px}
.card h2{font-size:12px;margin:0 0 8px;color:var(--dim);font-weight:600;letter-spacing:.03em}
canvas{width:100%;display:block;border-radius:5px;cursor:crosshair}
.readout{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:9px;margin-bottom:12px}
.kv{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:9px 11px}
.kv .k{color:var(--dim);font-size:11px}
.kv .v{font-size:19px;font-weight:600}
.legend{display:flex;gap:13px;font-size:11.5px;color:var(--dim);margin-top:7px;flex-wrap:wrap}
.sw{display:inline-block;width:11px;height:3px;vertical-align:middle;margin-right:4px;border-radius:2px}
.hint{color:var(--dim);font-size:11.5px;margin-top:6px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style></head><body>
<header>
  <h1>ΔB 回放 · 形变量与形变方向</h1>
  <span class="sub" id="meta"></span>
</header>
<div class="wrap">
  <div class="recs" id="recs"></div>
  <div class="ctl">
    <button id="play">▶ 播放</button>
    <input type="range" id="seek" min="0" value="0" step="1">
    <span class="mono" id="tlab">0.000 s</span>
    <label class="sub">速度</label>
    <select id="rate" style="background:#21262d;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px">
      <option value="0.25">0.25×</option><option value="0.5">0.5×</option>
      <option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option>
    </select>
    <label class="sub"><input type="checkbox" id="trail" checked> 拖尾</label>
    <button id="jump" title="跳到人工标记的动作起点">⇥ 跳到动作</button>
  </div>
  <div class="readout">
    <div class="kv"><div class="k">形变量 |ΔB|</div><div class="v mono" id="r_mag">–</div></div>
    <div class="kv"><div class="k">面内 |ΔBxy|</div><div class="v mono" id="r_xy">–</div></div>
    <div class="kv"><div class="k">方位角 φ</div><div class="v mono" id="r_phi">–</div></div>
    <div class="kv"><div class="k">极角 θ(与+z)</div><div class="v mono" id="r_th">–</div></div>
    <div class="kv"><div class="k">ΔBx</div><div class="v mono" id="r_x" style="color:var(--x)">–</div></div>
    <div class="kv"><div class="k">ΔBy</div><div class="v mono" id="r_y" style="color:var(--y)">–</div></div>
    <div class="kv"><div class="k">ΔBz</div><div class="v mono" id="r_z" style="color:var(--z)">–</div></div>
  </div>
  <div class="grid">
    <div class="card">
      <h2>★ 坐标系中的点 — ΔB 向量末端 (3D, 可拖拽旋转)</h2>
      <canvas id="c3d" height="330"></canvas>
      <div class="hint">点的位置 = (ΔBx, ΔBy, ΔBz)；离原点的距离就是形变量，方向就是形变方向。拖动可转视角。</div>
    </div>
    <div class="card">
      <h2>XY 平面罗盘 — 面内方向与幅值</h2>
      <canvas id="cxy" height="330"></canvas>
      <div class="hint">半径 = |ΔBxy|，角度 = 方位角 φ。虚线圆为幅值刻度。</div>
    </div>
    <div class="card">
      <h2>三轴 ΔB 随时间</h2>
      <canvas id="cts" height="230"></canvas>
      <div class="legend">
        <span><i class="sw" style="background:var(--x)"></i>ΔBx</span>
        <span><i class="sw" style="background:var(--y)"></i>ΔBy</span>
        <span><i class="sw" style="background:var(--z)"></i>ΔBz</span>
        <span style="color:#8a94a3">橙色区 = 人工标记的动作窗</span>
      </div>
    </div>
    <div class="card">
      <h2>形变量 / 形变方向 随时间</h2>
      <canvas id="cmg" height="230"></canvas>
      <div class="legend">
        <span><i class="sw" style="background:var(--m)"></i>|ΔB| 形变量</span>
        <span><i class="sw" style="background:var(--acc)"></i>|ΔBxy| 面内</span>
        <span><i class="sw" style="background:#a371f7"></i>方位角 φ (右轴 ±180°)</span>
        <span style="color:#8a94a3">φ 仅在 |ΔB| ≥ 噪声门控时绘制（幅值太小时方向无物理意义）</span>
      </div>
    </div>
  </div>
  <p class="hint">数据：真机 MLX90393 @100 Hz，ΔB = B − B0（每段自带基线）。单位 µT。
  分析见 <span class="mono">docs/deltab-v0-analysis.md</span>。</p>
</div>
<script>
const DATA = __DATA__;
const GATE = __GATE__;          // 方向门控阈值(µT) = 3× 静止噪声底; 低于此方向无意义
// 默认打开第一条非 idle 记录(idle 是纯噪声, 没什么可看)
let ri = Math.max(0, DATA.findIndex(d => d.action !== 'idle'));
let idx = 0, playing = false, rot = {az: -0.6, el: 0.5}, drag = null;
const $ = id => document.getElementById(id);
const cur = () => DATA[ri];

// ---------- HiDPI ----------
function fit(c){
  const r = window.devicePixelRatio || 1, w = c.clientWidth, h = c.height;
  if (c.width !== w * r || c._h !== h * r){ c.width = w * r; c._h = h * r; c.height = h * r; }
  const g = c.getContext('2d'); g.setTransform(r, 0, 0, r, 0, 0);
  return {g, W: w, H: h};
}
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ---------- 记录切换 ----------
function buildRecs(){
  $('recs').innerHTML = '';
  DATA.forEach((d, i) => {
    const b = document.createElement('button');
    b.textContent = d.action; b.className = i === ri ? 'on' : '';
    b.onclick = () => { ri = i; idx = 0; setup(); };
    $('recs').appendChild(b);
  });
}
function setup(){
  const d = cur();
  $('seek').max = d.t.length - 1; $('seek').value = 0;
  $('meta').textContent = `${d.action} · ${d.t.length} 样本 · ${d.t[d.t.length-1].toFixed(2)} s · ${d.fs} Hz · B0=(${d.B0.join(', ')}) µT`;
  buildRecs(); draw();
}

// ---------- 播放 ----------
let last = 0;
function loop(ts){
  if (playing){
    const d = cur(), rate = parseFloat($('rate').value);
    if (last){
      const step = (ts - last) / 1000 * d.fs * rate;
      idx += step;
      if (idx >= d.t.length - 1){ idx = d.t.length - 1; playing = false; $('play').textContent = '▶ 播放'; }
    }
    last = ts; $('seek').value = Math.round(idx); draw();
  } else last = 0;
  requestAnimationFrame(loop);
}
$('play').onclick = () => {
  const d = cur();
  if (Math.round(idx) >= d.t.length - 1) idx = 0;
  playing = !playing; $('play').textContent = playing ? '⏸ 暂停' : '▶ 播放'; last = 0;
};
$('seek').oninput = e => { idx = +e.target.value; draw(); };
$('rate').onchange = () => {};
$('trail').onchange = draw;
$('jump').onclick = () => {
  const d = cur(); if (!d.win || d.win[0] == null) return;
  let k = 0; while (k < d.t.length - 1 && d.t[k] < d.win[0]) k++;
  idx = k; $('seek').value = k; draw();
};

// ---------- 3D ----------
function proj(p, s, W, H){
  const ca = Math.cos(rot.az), sa = Math.sin(rot.az), ce = Math.cos(rot.el), se = Math.sin(rot.el);
  const x = p[0] * ca - p[1] * sa, y = p[0] * sa + p[1] * ca;
  const yy = y * ce - p[2] * se;
  return [W / 2 + x * s, H / 2 - yy * s];
}
function draw3d(){
  const c = $('c3d'), {g, W, H} = fit(c), d = cur(), i = Math.round(idx);
  g.clearRect(0, 0, W, H);
  let mx = 1;
  for (let k = 0; k < d.t.length; k++) mx = Math.max(mx, Math.abs(d.x[k]), Math.abs(d.y[k]), Math.abs(d.z[k]));
  const s = Math.min(W, H) * 0.36 / mx;
  // 轴
  const axes = [[[mx,0,0],'X',css('--x')],[[0,mx,0],'Y',css('--y')],[[0,0,mx],'Z',css('--z')]];
  g.lineWidth = 1.2;
  axes.forEach(([v,lab,col]) => {
    const o = proj([0,0,0], s, W, H), a = proj(v, s, W, H), b = proj([-v[0],-v[1],-v[2]], s, W, H);
    g.strokeStyle = col; g.globalAlpha = .75; g.beginPath(); g.moveTo(b[0],b[1]); g.lineTo(a[0],a[1]); g.stroke();
    g.globalAlpha = 1; g.fillStyle = col; g.font = '11px monospace'; g.fillText(lab, a[0]+4, a[1]-3);
  });
  // 拖尾
  if ($('trail').checked){
    const n0 = Math.max(0, i - 260);
    g.lineWidth = 1.4;
    for (let k = n0 + 1; k <= i; k++){
      const p = proj([d.x[k-1], d.y[k-1], d.z[k-1]], s, W, H), q = proj([d.x[k], d.y[k], d.z[k]], s, W, H);
      g.strokeStyle = css('--m'); g.globalAlpha = 0.08 + 0.72 * (k - n0) / (i - n0 + 1);
      g.beginPath(); g.moveTo(p[0],p[1]); g.lineTo(q[0],q[1]); g.stroke();
    }
    g.globalAlpha = 1;
  }
  // 当前向量 + 点
  const o = proj([0,0,0], s, W, H), p = proj([d.x[i], d.y[i], d.z[i]], s, W, H);
  g.strokeStyle = css('--m'); g.lineWidth = 2; g.beginPath(); g.moveTo(o[0],o[1]); g.lineTo(p[0],p[1]); g.stroke();
  g.fillStyle = css('--m'); g.beginPath(); g.arc(p[0], p[1], 5.5, 0, 7); g.fill();
  g.fillStyle = '#7d8794'; g.font = '10px monospace';
  g.fillText('满量程 ±' + mx.toFixed(0) + ' µT', 8, H - 8);
}
(function(){
  const c = $('c3d');
  c.onmousedown = e => drag = {x: e.clientX, y: e.clientY};
  window.addEventListener('mouseup', () => drag = null);
  window.addEventListener('mousemove', e => {
    if (!drag) return;
    rot.az += (e.clientX - drag.x) * 0.01; rot.el += (e.clientY - drag.y) * 0.01;
    rot.el = Math.max(-1.5, Math.min(1.5, rot.el));
    drag = {x: e.clientX, y: e.clientY}; draw3d();
  });
})();

// ---------- XY 罗盘 ----------
function drawXY(){
  const c = $('cxy'), {g, W, H} = fit(c), d = cur(), i = Math.round(idx);
  g.clearRect(0, 0, W, H);
  const cx = W/2, cy = H/2;
  let mx = 1; for (let k = 0; k < d.t.length; k++) mx = Math.max(mx, Math.hypot(d.x[k], d.y[k]));
  const s = Math.min(W, H) * 0.40 / mx;
  g.strokeStyle = css('--line'); g.fillStyle = '#7d8794'; g.font = '10px monospace';
  for (let f = 0.25; f <= 1.001; f += 0.25){
    g.setLineDash([3,4]); g.beginPath(); g.arc(cx, cy, mx*f*s, 0, 7); g.stroke(); g.setLineDash([]);
    g.fillText((mx*f).toFixed(0), cx + mx*f*s + 3, cy - 2);
  }
  g.strokeStyle = css('--line'); g.beginPath();
  g.moveTo(cx-mx*s, cy); g.lineTo(cx+mx*s, cy); g.moveTo(cx, cy-mx*s); g.lineTo(cx, cy+mx*s); g.stroke();
  g.fillStyle = css('--x'); g.fillText('+X', cx+mx*s+4, cy+11);
  g.fillStyle = css('--y'); g.fillText('+Y', cx+3, cy-mx*s-4);
  if ($('trail').checked){
    const n0 = Math.max(0, i - 260); g.lineWidth = 1.4;
    for (let k = n0 + 1; k <= i; k++){
      g.strokeStyle = css('--acc'); g.globalAlpha = 0.08 + 0.72*(k-n0)/(i-n0+1);
      g.beginPath(); g.moveTo(cx + d.x[k-1]*s, cy - d.y[k-1]*s); g.lineTo(cx + d.x[k]*s, cy - d.y[k]*s); g.stroke();
    }
    g.globalAlpha = 1;
  }
  const px = cx + d.x[i]*s, py = cy - d.y[i]*s;
  g.strokeStyle = css('--m'); g.lineWidth = 2; g.beginPath(); g.moveTo(cx,cy); g.lineTo(px,py); g.stroke();
  g.fillStyle = css('--m'); g.beginPath(); g.arc(px, py, 5.5, 0, 7); g.fill();
}

// ---------- 时序图 ----------
function axesBox(g, W, H){ return {L: 42, R: W - 46, T: 10, B: H - 20}; }
function drawSeries(cid, series, opts){
  const c = $(cid), {g, W, H} = fit(c), d = cur(), i = Math.round(idx);
  g.clearRect(0, 0, W, H);
  const bx = axesBox(g, W, H), n = d.t.length, T = d.t[n-1];
  let lo = 0, hi = 0;
  series.forEach(s => s.v.forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v); }));
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = t => bx.L + (t / T) * (bx.R - bx.L);
  const Y = v => bx.B - (v - lo) / (hi - lo) * (bx.B - bx.T);
  // 动作窗
  if (d.win && d.win[0] != null){
    g.fillStyle = 'rgba(255,166,74,.11)';
    g.fillRect(X(d.win[0]), bx.T, X(d.win[1]) - X(d.win[0]), bx.B - bx.T);
  }
  // 网格 + 零线
  g.strokeStyle = css('--line'); g.lineWidth = 1; g.fillStyle = '#7d8794'; g.font = '10px monospace';
  [lo, (lo+hi)/2, hi].forEach(v => {
    g.globalAlpha = .5; g.beginPath(); g.moveTo(bx.L, Y(v)); g.lineTo(bx.R, Y(v)); g.stroke(); g.globalAlpha = 1;
    g.fillText(v.toFixed(0), 4, Y(v) + 3);
  });
  if (lo < 0 && hi > 0){ g.strokeStyle = '#3d4756'; g.beginPath(); g.moveTo(bx.L, Y(0)); g.lineTo(bx.R, Y(0)); g.stroke(); }
  for (let k = 0; k <= 4; k++){
    const t = T*k/4; g.fillText(t.toFixed(1)+'s', X(t) - 10, H - 6);
  }
  // 曲线(抽稀到像素)
  const step = Math.max(1, Math.floor(n / (bx.R - bx.L) / 2));
  series.forEach(s => {
    g.strokeStyle = s.c; g.lineWidth = s.w || 1.2; g.beginPath();
    for (let k = 0; k < n; k += step){
      const px = X(d.t[k]), py = Y(s.v[k]);
      k === 0 ? g.moveTo(px, py) : g.lineTo(px, py);
    }
    g.stroke();
  });
  // 右轴(方位角) —— 幅值低于噪声门控时方向无意义, 断开不画
  if (opts && opts.right){
    const Yr = v => bx.B - (v + 180) / 360 * (bx.B - bx.T);
    g.strokeStyle = '#a371f7'; g.lineWidth = 1.2; g.globalAlpha = .9;
    let pen = false, prev = null; g.beginPath();
    for (let k = 0; k < n; k += step){
      if (opts.gate[k] < GATE){ pen = false; prev = null; continue; }   // 噪声区: 抬笔
      const v = opts.right[k];
      if (prev !== null && Math.abs(v - prev) > 180) pen = false;       // ±180° 环绕: 断开, 不画竖线
      const px = X(d.t[k]), py = Yr(v);
      pen ? g.lineTo(px, py) : g.moveTo(px, py); pen = true; prev = v;
    }
    g.stroke(); g.globalAlpha = 1;
    g.fillStyle = '#a371f7'; g.fillText('+180', bx.R + 3, Yr(180) + 8); g.fillText('-180', bx.R + 3, Yr(-180));
  }
  // 游标
  const cxp = X(d.t[i]);
  g.strokeStyle = css('--acc'); g.lineWidth = 1.5; g.setLineDash([4,3]);
  g.beginPath(); g.moveTo(cxp, bx.T); g.lineTo(cxp, bx.B); g.stroke(); g.setLineDash([]);
  // 点击/拖动定位
  c.onmousedown = e => {
    const seek = ev => {
      const r = c.getBoundingClientRect(), t = (ev.clientX - r.left - bx.L) / (bx.R - bx.L) * T;
      idx = Math.max(0, Math.min(n - 1, Math.round(t / T * (n - 1))));
      $('seek').value = idx; draw();
    };
    seek(e);
    const mv = ev => seek(ev), up = () => { window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); };
    window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
  };
}

// ---------- 主绘制 ----------
function draw(){
  const d = cur(), i = Math.round(idx), n = d.t.length;
  if (!d._mag){
    d._mag = new Array(n); d._xy = new Array(n); d._phi = new Array(n); d._th = new Array(n);
    for (let k = 0; k < n; k++){
      const x = d.x[k], y = d.y[k], z = d.z[k];
      d._xy[k] = Math.hypot(x, y);
      d._mag[k] = Math.hypot(d._xy[k], z);
      d._phi[k] = Math.atan2(y, x) * 180 / Math.PI;
      d._th[k] = Math.atan2(d._xy[k], z) * 180 / Math.PI;
    }
  }
  $('tlab').textContent = d.t[i].toFixed(3) + ' s';
  $('r_mag').textContent = d._mag[i].toFixed(1);
  $('r_xy').textContent = d._xy[i].toFixed(1);
  const live = d._mag[i] >= GATE;                    // 幅值够大, 方向才有意义
  $('r_phi').textContent = live ? d._phi[i].toFixed(1) + '°' : '—';
  $('r_th').textContent = live ? d._th[i].toFixed(1) + '°' : '—';
  $('r_phi').style.opacity = $('r_th').style.opacity = live ? 1 : .35;
  $('r_x').textContent = d.x[i].toFixed(1);
  $('r_y').textContent = d.y[i].toFixed(1);
  $('r_z').textContent = d.z[i].toFixed(1);
  draw3d(); drawXY();
  drawSeries('cts', [
    {v: d.x, c: css('--x')}, {v: d.y, c: css('--y')}, {v: d.z, c: css('--z'), w: 1.4}]);
  drawSeries('cmg', [
    {v: d._mag, c: css('--m'), w: 1.6}, {v: d._xy, c: css('--acc')}],
    {right: d._phi, gate: d._mag});
}
window.addEventListener('resize', draw);
// URL 定位: #line_rl 或 #line_rl@8.0 (秒) —— 方便分享/引用某一时刻
function fromHash(){
  const h = decodeURIComponent(location.hash.slice(1)); if (!h) return;
  const [name, ts] = h.split('@');
  const i = DATA.findIndex(d => d.action === name);
  if (i >= 0) ri = i;
  setup();
  if (ts != null){
    const d = cur(); let k = 0;
    while (k < d.t.length - 1 && d.t[k] < parseFloat(ts)) k++;
    idx = k; $('seek').value = k; draw();
  }
}
setup(); fromHash(); window.addEventListener('hashchange', fromHash);
requestAnimationFrame(loop);
</script></body></html>
"""


def main(folder, out):
    recs = load(folder)
    if not recs:
        print("没找到数据"); return
    # 方向门控 = 3× 静止噪声底(|σ|); 低于它时 ΔB 方向由噪声主导, 不该显示
    idle = next((r for r in recs if r["action"] == "idle"), None)
    if idle is not None:
        s = np.array([np.std(idle[k]) for k in "xyz"])
        gate = 3.0 * float(np.linalg.norm(s))
    else:
        gate = 20.0
    html = (HTML.replace("__DATA__", json.dumps(recs, ensure_ascii=False, separators=(",", ":")))
                .replace("__GATE__", "%.2f" % gate))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    n = sum(len(r["t"]) for r in recs)
    print("回放页 → %s  (%d 条记录, %d 样本, %.1f KB)  方向门控=%.1f µT (=3×噪声底)"
          % (out, len(recs), n, os.path.getsize(out) / 1024, gate))
    print("用浏览器打开即可(离线, 无外部依赖):  xdg-open %s" % out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "delta_b_v0_20260724",
         sys.argv[2] if len(sys.argv) > 2 else "deltab_replay.html")
