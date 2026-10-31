"""Merge the per-layer counters of one RTSR run into a single report.

Inputs (all produced by the same simulation run, in its working directory):
    frame_stats_port<port>_ue<i>.csv   L1 application frames (XrFrameSink)
    rlc_drops.csv                      L3 RLC SDU drops (TxDrop trace)
    rtsr-flowmon.xml                   L2 IP packets (FlowMonitor)
    mac_tb.csv / RxPacketTrace*.txt    L4/L5, optional (not yet wired)

Usage:
    python3 layer_stats.py --dir . --out layer_report.md
"""

import argparse
import csv
import glob
import os
import xml.etree.ElementTree as ET


def read_frames(pattern):
    rows = []
    for path in glob.glob(pattern):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["_file"] = os.path.basename(path)
                rows.append(r)
    return rows


def read_rlc_drops(path):
    if not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)]


def read_ip(path):
    """Per-flow IP statistics from the FlowMonitor XML."""
    if not os.path.isfile(path):
        return None, None
    root = ET.parse(path).getroot()

    ports = {}
    for f in root.iter("Flow"):
        if f.get("destinationPort") is not None:
            ports[int(f.get("flowId"))] = int(f.get("destinationPort"))

    video = {"tx": 0, "rx": 0}
    model = {"tx": 0, "rx": 0}
    for f in root.iter("Flow"):
        if f.get("txPackets") is None:
            continue
        fid = int(f.get("flowId"))
        bucket = model if ports.get(fid) == 5000 else video
        bucket["tx"] += int(f.get("txPackets"))
        bucket["rx"] += int(f.get("rxPackets"))
    return video, model


def pct(x, y):
    return 100.0 * x / y if y else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=".")
    ap.add_argument("--out", default="layer_report.md")
    args = ap.parse_args()

    frames = read_frames(os.path.join(args.dir, "frame_stats_port*_ue*.csv"))
    drops = read_rlc_drops(os.path.join(args.dir, "rlc_drops.csv"))
    video_ip, model_ip = read_ip(os.path.join(args.dir, "rtsr-flowmon.xml"))

    # ---- L1: application frames ----
    n_frames = len(frames)
    n_complete = sum(1 for r in frames if r["complete"] == "1")
    n_in_pdb = sum(1 for r in frames if r["within_pdb"] == "1")
    rx_pkts = sum(int(r["pkts"]) for r in frames)
    exp_pkts = sum(int(r["expected_pkts"]) for r in frames)
    fsr = pct(n_in_pdb, n_frames)
    frame_loss = pct(n_frames - n_complete, n_frames)

    # ---- L3: RLC drops ----
    rlc_total = len(drops) if drops is not None else None
    rlc_sdu = sum(int(r["dropped_sdus"]) for r in drops) if drops else 0
    rlc_frames = len(drops) if drops else 0

    # ---- derived ----
    video_sdu_lost = rlc_sdu
    video_sdu_total = video_sdu_lost + rx_pkts
    l3_rate = pct(video_sdu_lost, video_sdu_total)

    ip_tx, ip_rx = (video_ip["tx"], video_ip["rx"]) if video_ip else (0, 0)
    l2_loss = pct(ip_tx - ip_rx, ip_tx)

    lines = []
    lines.append("# 五层丢包汇总（单次运行）\n")
    lines.append("| 层 | 指标 | 数值 | 说明 |")
    lines.append("|---|---|---:|---|")
    lines.append(f"| L1 应用 | 帧数 | {n_frames} | 源端生成 |")
    lines.append(f"| L1 应用 | 完整帧 | {n_complete} | {pct(n_complete, n_frames):.1f}% |")
    lines.append(f"| L1 应用 | PDB 内帧（FSR） | {n_in_pdb} | **{fsr:.2f}%** |")
    lines.append(f"| L1 应用 | 帧丢失率 | — | **{frame_loss:.2f}%** |")
    lines.append(f"| L2 IP | 视频包 tx/rx | {ip_tx} / {ip_rx} | 丢 {ip_tx - ip_rx} |")
    lines.append(f"| L2 IP | 视频包丢失率 | — | **{l2_loss:.3f}%** |")
    if model_ip:
        lines.append(f"| L2 IP | 模型流 tx/rx | {model_ip['tx']} / {model_ip['rx']} | "
                     f"丢 {model_ip['tx'] - model_ip['rx']} |")
    if drops is not None:
        lines.append(f"| L3 RLC | 视频 SDU 丢弃数 | {rlc_sdu} | 可归属到 {rlc_frames} 帧 |")
        lines.append(f"| L3 RLC | 视频 SDU 丢弃率 | — | **{l3_rate:.3f}%** |")
    else:
        lines.append("| L3 RLC | — | 缺失 | 未生成 rlc_drops.csv |")
    lines.append("| L4 MAC | TB 失败率 | 未接入 | 待 0.4 |")
    lines.append("| L5 PHY | BLER | 未接入 | 待 0.5 |")

    # ---- consistency checks ----
    checks = []

    if n_frames and drops is not None:
        ok = frame_loss >= l3_rate - 0.5
        checks.append(("帧丢失率 ≥ RLC SDU 丢弃率",
                       f"{frame_loss:.2f}% vs {l3_rate:.3f}%", ok))

    if ip_tx:
        ok = l2_loss <= l3_rate + 1.0
        checks.append(("IP 包丢失率 ≤ RLC 丢弃率 + 1pp",
                       f"{l2_loss:.3f}% vs {l3_rate:.3f}%", ok))

    # frame-level vs SDU-level attribution
    if n_frames:
        touched_ratio = pct(rlc_frames, n_frames)
        ok = touched_ratio <= 100.0
        checks.append(("RLC 触及帧数 ≤ 总帧数",
                       f"{rlc_frames} vs {n_frames} ({touched_ratio:.1f}%)", ok))

    lines.append("\n## 一致性校验\n")
    lines.append("| 检查 | 数值 | 结果 |")
    lines.append("|---|---|---|")
    for name, val, ok in checks:
        lines.append(f"| {name} | {val} | {'✅' if ok else '❌'} |")

    if rx_pkts:
        lines.append("\n## 备注\n")
        lines.append(f"- 应用层收到包数 {rx_pkts}，源端发送包数 {exp_pkts}，"
                     f"差 {exp_pkts - rx_pkts}（含被 RLC 丢弃的部分）")
        lines.append(f"- RLC 视频丢弃 {rlc_sdu}，与上一行差值 "
                     f"{'一致' if abs((exp_pkts - rx_pkts) - rlc_sdu) <= max(2, 0.02 * exp_pkts) else '不一致，需核对'}")

    text = "\n".join(lines) + "\n"
    with open(os.path.join(args.dir, args.out), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
