#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDD 图样探针：只改 --tddPattern，测下行占比对容量的影响。

用途
    回答"把更多时隙分给下行，能不能提容量"。结论见
    docs/stage1/09_容量扩展失败复盘.md §3.6：DL 占比 0.70→0.875
    容量只 +7% 且已饱和，所以时隙占比不是杠杆。

口径
    3 小区 x 12 UE x 1 s 探针（每次约 140 秒）。容量按
    `scheduled_bytes x 8 / 1.0 s / 小区数` 计，与 docs/stage1/06 的探针一致。
    ⚠️ 绝对值分母含启动期，**只有组间比值有意义**。

用法
    python RTSR/scripts/probe_tdd.py                 # 跑内置的 6 个图样
    python RTSR/scripts/probe_tdd.py DDDSU DDDDSU    # 只跑指定的

输出
    RTSR/results/tdd_probe/<图样>/    每次运行的原始 CSV
    RTSR/results/tdd_probe/summary_tdd.json   汇总
"""
import csv
import json
import os
import subprocess
import sys
import time

# ns-3 探针二进制（与 docs/stage1/04_执行手册.md 一致）
BIN = os.path.expanduser(
    "~/code/ns-allinone-3.39/ns-3.39/build/src/nr/examples/"
    "ns3.39-cttc-nr-traffic-3gpp-xr-optimized"
)
# 产物根目录：脚本位于 RTSR/scripts/，往上两级就是 RTSR/
# （这里曾漏写 RTSR/ 前缀，与 docs/stage3/03_总结.md §2.3 记的 M6 runner 是同一类 bug，
#  所以下面加了断言自检）
RTSR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(RTSR_DIR, "results", "tdd_probe")
assert os.path.basename(RTSR_DIR) == "RTSR", "产物目录少了 RTSR/ 前缀：%s" % RTSR_DIR

# 内置矩阵：5/6/7/8/9/12 槽，DL 占比 0.700 -> 0.875
# 其中 7 槽和 9 槽会触发 5G-LENA 的 TX/RX 定时冲突断言（见文档 §3.6 结论 3）
DEFAULT_PATTERNS = [
    "DDDSU",          # 5 槽, dl=0.700  基线
    "DDDDSU",         # 6 槽, dl=0.750
    "DDDDDSU",        # 7 槽, dl=0.786  预期中止
    "DDDDDDSU",       # 8 槽, dl=0.813
    "DDDDDDDSU",      # 9 槽, dl=0.833  预期中止
    "DDDDDDDDDDSU",   # 12 槽, dl=0.875
]


def dl_fraction(pattern):
    """按 D=1、S=0.5、U=0 计算下行占比（与 DDDSU=0.7 的官方口径一致）。"""
    return sum(1.0 if c == "D" else 0.5 if c == "S" else 0.0 for c in pattern) / len(pattern)


def read_metrics(run_dir):
    """把 mac_tb.csv / phy_tb.csv 的 metric->value 读成一个字典。"""
    out = {}
    for name in ("mac_tb.csv", "phy_tb.csv"):
        path = os.path.join(run_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out[(name, row["metric"])] = row["value"]
    return out


def run_one(pattern):
    """跑一个图样，返回一行汇总（中止的运行返回 rc 与空指标）。"""
    run_dir = os.path.join(OUT_ROOT, pattern)
    os.makedirs(run_dir, exist_ok=True)
    args = [
        BIN,
        "--trafficModel=paper", "--preset=paperTable3", "--scheme=conventional",
        "--sectorized=1", "--numSectors=3", "--numSites=1",
        "--siteRings=0", "--statsRings=0",
        "--uePerCell=12", "--indoorRatio=0.8", "--ueSpeedKmh=3",
        "--tddPattern=" + pattern,
        "--warmupMs=500", "--appDuration=1000",
        "--enablePing=0", "--flowmonProbes=0", "--rngRun=1",
    ]
    started = time.time()
    print("[run] %-14s dl=%.3f ..." % (pattern, dl_fraction(pattern)), flush=True)
    proc = subprocess.run(args, cwd=run_dir, capture_output=True, text=True)
    wall = time.time() - started

    metrics = read_metrics(run_dir)
    sched = metrics.get(("mac_tb.csv", "scheduled_bytes"))
    cells = metrics.get(("mac_tb.csv", "measured_cells"))
    cap = (float(sched) * 8 / 1.0 / float(cells) / 1e6) if sched and cells else None
    row = {
        "pattern": pattern,
        "dl": round(dl_fraction(pattern), 4),
        "rc": proc.returncode,
        "wall_s": round(wall, 1),
        "cap_mbps": round(cap, 2) if cap else None,
        "cap_per_dl": round(cap / dl_fraction(pattern), 2) if cap else None,
        "bler": metrics.get(("phy_tb.csv", "bler_percent")),
        "mean_sinr_db": metrics.get(("phy_tb.csv", "mean_sinr_db")),
    }
    print("      rc=%d wall=%.0fs cap=%s perDL=%s bler=%s" % (
        row["rc"], wall, row["cap_mbps"], row["cap_per_dl"], row["bler"]), flush=True)
    if proc.returncode != 0:
        # 中止时把断言原因留在目录里，方便回头查（不写入文档，只在本地）
        blob = (proc.stderr or "") + (proc.stdout or "")
        idx = blob.find("NS_FATAL")
        with open(os.path.join(run_dir, "aborted.txt"), "w", encoding="utf-8") as fh:
            fh.write("rc=%d\n%s\n" % (proc.returncode, blob[max(0, idx - 300):idx + 300]))
    return row


def main(argv):
    patterns = argv[1:] or DEFAULT_PATTERNS
    if not os.path.isfile(BIN):
        print("找不到探针二进制：%s\n先按 docs/stage1/04_执行手册.md 编译 ns-3。" % BIN)
        return 2
    os.makedirs(OUT_ROOT, exist_ok=True)

    rows = [run_one(p) for p in patterns]

    out_json = os.path.join(OUT_ROOT, "summary_tdd.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)

    print("\n=== 汇总 ===")
    print("%-14s %6s %10s %10s %8s %5s" % ("pattern", "dl", "cap", "cap/dl", "bler", "rc"))
    for r in rows:
        print("%-14s %6.3f %10s %10s %8s %5d" % (
            r["pattern"], r["dl"], r["cap_mbps"], r["cap_per_dl"], r["bler"], r["rc"]))
    print("\n汇总写入 %s" % out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))