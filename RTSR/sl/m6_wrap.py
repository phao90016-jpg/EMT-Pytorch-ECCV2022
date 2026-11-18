#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M6 收尾：把 36 条 run 聚合成 summary_m6.csv，并画 Fig.5。

这是 M6 跑完之后唯一需要手工执行的脚本（见 docs/stage3/02_实验计划.md 的 P5 一节）。

做三件事：
    1. 收集结果（顺带兼容 2026-11 那次路径 bug 留下的旧目录）
    2. 按 (UE 数, 方案) 分组求均值/标准差 -> summary_m6.csv
    3. 画双面板图：左图满意率（论文 Fig.5）、右图承载吞吐

注意：本脚本会**覆盖** docs/figs/m6_fig5.png —— 那是阶段二的旧图，覆盖是预期的。
"""
import csv
import glob
import io
import os
import shutil

import numpy as np

REPO = "/home/penghao/code/EMT-Pytorch-ECCV2022"
DST = REPO + "/RTSR/sl/results/m6"         # 规范位置（run_m6.sh 直接写这里）
LEGACY = REPO + "/sl/results/m6"           # 旧版 runner 因路径 bug 写到的位置
FIG = REPO + "/RTSR/docs/figs"

# ---------------------------------------------------------------- 1. 收集结果
# 2026-11 之后的 runner 直接写进 DST。更早的那次因为少了 RTSR/ 前缀落到了 LEGACY。
# 只有两个目录**确实不同**时才去拷贝，否则 shutil.copy 会试图把文件拷给自己
# （SameFileError）。
os.makedirs(DST, exist_ok=True)
if os.path.isdir(LEGACY) and os.path.realpath(LEGACY) != os.path.realpath(DST):
    for f in glob.glob(os.path.join(LEGACY, "*.csv")):
        shutil.copy(f, DST)
    if os.path.isdir(os.path.join(LEGACY, "logs")):
        os.makedirs(os.path.join(DST, "logs"), exist_ok=True)
        for f in glob.glob(os.path.join(LEGACY, "logs", "*.log")):
            shutil.copy(f, os.path.join(DST, "logs"))
    print(f"merged legacy results from {LEGACY}")
print(f"found {len(glob.glob(os.path.join(DST, '*.csv')))} csv files in {DST}")
# ---------------------------------------------------------------- 2. aggregate
rows = []
for f in glob.glob(os.path.join(DST, "*.csv")):
    # 必须排除上一次自己生成的 summary_m6.csv，否则脚本不幂等：
    # 第二次运行时会把汇总表当成原始数据读进来，因缺 satisfied_pct 列而报 KeyError。
    if os.path.basename(f) == "summary_m6.csv":
        continue
    with io.open(f, encoding="utf-8") as fh:
        rows += [r for r in csv.DictReader(fh)]

by_point = {}
for r in rows:
    key = (int(r["ue"]), r["scheme"])
    by_point.setdefault(key, []).append(r)

summary = []
for (ue, scheme), rs in sorted(by_point.items()):
    sat = np.array([float(x["satisfied_pct"]) for x in rs])
    fsr = np.array([float(x["mean_fsr_pct"]) for x in rs])
    mbps = np.array([float(x["carried_mbps"]) for x in rs])
    summary.append({
        "ue": ue, "scheme": scheme, "seeds": len(rs),
        "sat_mean": sat.mean(), "sat_std": sat.std(ddof=1) if len(rs) > 1 else 0.0,
        "fsr_mean": fsr.mean(),
        "mbps_mean": mbps.mean(), "mbps_std": mbps.std(ddof=1) if len(rs) > 1 else 0.0,
    })

out = os.path.join(DST, "summary_m6.csv")
with io.open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write("ue,scheme,seeds,sat_mean,sat_std,fsr_mean,mbps_mean,mbps_std\n")
    for s in summary:
        f.write(f"{s['ue']},{s['scheme']},{s['seeds']},{s['sat_mean']:.2f},"
                f"{s['sat_std']:.2f},{s['fsr_mean']:.2f},{s['mbps_mean']:.1f},"
                f"{s['mbps_std']:.1f}\n")
print("wrote", out)

print(f"\n{'UE/cell':>7} {'scheme':<5} {'sat%':>7} {'sd':>5} {'FSR%':>7} {'Mbps':>7}")
for s in summary:
    print(f"{s['ue']:>7} {s['scheme']:<5} {s['sat_mean']:>7.1f} {s['sat_std']:>5.1f} "
          f"{s['fsr_mean']:>7.1f} {s['mbps_mean']:>7.0f}")

# ---------------------------------------------------------------- 3. figure
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

convs = [s for s in summary if s["scheme"] == "conv"]
rtsrs = [s for s in summary if s["scheme"] == "rtsr"]
xs_c = [s["ue"] for s in convs]
ys_c = [s["sat_mean"] for s in convs]
ec = [s["sat_std"] for s in convs]
xs_r = [s["ue"] for s in rtsrs]
ys_r = [s["sat_mean"] for s in rtsrs]
er = [s["sat_std"] for s in rtsrs]

fig, axes = plt.subplots(1, 2, figsize=(13, 5))
ax = axes[0]
ax.errorbar(xs_c, ys_c, yerr=ec, marker="o", ms=8, lw=2, capsize=4,
            color="#c0392b", label="Conventional 20 Mbps")
ax.errorbar(xs_r, ys_r, yerr=er, marker="s", ms=8, lw=2, capsize=4,
            color="#2565a8", label="RTSR 10 Mbps + model")
ax.axhline(90, ls="--", c="grey", lw=1)
ax.text(6.2, 91.5, "90% criterion", color="grey", fontsize=9)
ax.set_xlabel("UE per cell")
ax.set_ylabel("Satisfied UEs (%)  [per-UE FSR > 99.5%]")
ax.set_title("Fig.5  Satisfied UE ratio (ideal mode, 1000 s x 3 seeds)")
ax.set_ylim(0, 100)
ax.grid(alpha=0.3)
ax.legend(loc="lower left")

ax = axes[1]
ax.errorbar(xs_c, [s["mbps_mean"] for s in convs],
            yerr=[s["mbps_std"] for s in convs], marker="o", ms=8, lw=2, capsize=4,
            color="#c0392b", label="Conventional")
ax.errorbar(xs_r, [s["mbps_mean"] for s in rtsrs],
            yerr=[s["mbps_std"] for s in rtsrs], marker="s", ms=8, lw=2, capsize=4,
            color="#2565a8", label="RTSR")
ax.axhline(350, ls=":", c="green", lw=1.2)
ax.text(6.2, 358, "paper ~350 Mbps", color="green", fontsize=9)
ax.set_xlabel("UE per cell")
ax.set_ylabel("Carried throughput per cell (Mbps)")
ax.set_title("Carried throughput (21 centre cells)")
ax.grid(alpha=0.3)
ax.legend(loc="upper left")

fig.tight_layout()
path = os.path.join(FIG, "m6_fig5.png")
fig.savefig(path, dpi=140)
print("wrote", path)
