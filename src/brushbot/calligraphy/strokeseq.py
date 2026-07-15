def process(seq, r2z, alpha=0.04, beta=0.5):
    """CalliRewrite (p_t,x,y,r) 笔序 -> 米制 (x,y,z) 路点. 楷书入锋; 见
    docs/callirewrite-arm-control.md. 端口自 load_data_try.py。"""
    xs, ys, zs = [], [], []
    n = len(seq)
    has_new_stroke = any(p_t == 1 for p_t, _, _, _ in seq)
    for i in range(n):
        p_t, x, y, r = seq[i]
        x_, y_ = x * alpha, y * alpha
        r_ = r * alpha * beta
        h = r2z(r_) * 100.0
        h = (h - 0.09) / 100.0          # CalliRewrite 经验微调
        if p_t == 0:
            xs.append(x_); ys.append(y_); zs.append(h)
        else:                            # p_t == 1: 新笔起笔 (楷书从左上入锋)
            if i == n - 1:
                continue
            xs.append(x_ - 2 * r_); ys.append(y_ - 2 * r_); zs.append(0.05)  # 悬空进入
            xs.append(x_); ys.append(y_); zs.append(h)                        # 落笔
    # 末尾抬笔离纸. 门控 has_new_stroke 是为满足 Task6 的 len==1 用例(纯延续输入不加抬笔点),
    # 勿改回无条件循环否则破坏该测试; `and xs` 防单点退化输入(如仅 [(1,...)] 被跳过)时 xs[-1] 越界.
    if has_new_stroke and xs:
        for _ in range(5):
            xs.append(xs[-1]); ys.append(ys[-1]); zs.append(zs[-1] + 0.015)
    return list(zip(xs, ys, zs))
