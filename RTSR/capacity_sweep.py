"""UE-density sweep for the RTSR network layer (single-cell, 5 MHz).

Runs the 5G-LENA XR example with an increasing number of UEs per cell, parses the
FlowMonitor dump, and reports per-UE delivery ratio / mean delay plus the ratio of
"satisfied" UEs (delivery ratio >= 99.5%, the paper's criterion).

    python3 capacity_sweep.py --ues 1 2 3 4 5 6

Output: capacity_sweep.json and capacity_sweep.md next to this file.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from calc_traffic_saving import parse_flows  # noqa: E402

NS3 = '/home/penghao/code/ns-allinone-3.39/ns-3.39'
SATISFIED_RATIO = 0.995


def run_one(per_type, bandwidth_mhz, numerology, app_duration, num_sites, rng_run):
    program = ('cttc-nr-traffic-3gpp-xr --arUeNum={u} --vrUeNum={u} --cgUeNum={u} '
               '--bandwidth={b}e6 --numerology={n} --appDuration={d} --numSites={s} --rngRun={r}'
               .format(u=per_type, b=bandwidth_mhz, n=numerology, d=app_duration,
                       s=num_sites, r=rng_run))
    proc = subprocess.run(['./ns3', 'run', program], cwd=NS3,
                          capture_output=True, text=True)
    return proc.stdout


def summarise(text, per_type, pdb_ms, num_sites, rng_run):
    tmp = '/tmp/capacity_run.txt'
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write(text)
    flows = parse_flows(tmp)
    video = [f for f in flows if f['dst_port'] != 5000]
    sr = [f for f in flows if f['dst_port'] == 5000]
    if not video:
        return None

    def ratio(f):
        return f['rx_bytes'] / f['tx_bytes'] if f['tx_bytes'] else 0.0

    total_ues = per_type * 3
    sat = sum(1 for f in video if ratio(f) >= SATISFIED_RATIO) / float(len(video))
    sat_pdb = sum(1 for f in video
                  if ratio(f) >= SATISFIED_RATIO and f['delay_ms'] <= pdb_ms) \
        / float(len(video))
    return {
        'ues_per_cell': total_ues,
        'num_sites': num_sites,
        'rng_run': rng_run,
        'video_flows': len(video),
        'video_ratio_mean': sum(ratio(f) for f in video) / len(video),
        'video_delay_mean_ms': sum(f['delay_ms'] for f in video) / len(video),
        'sr_ratio_mean': (sum(ratio(f) for f in sr) / len(sr)) if sr else None,
        'satisfied_ue_ratio': sat,
        'satisfied_ue_ratio_pdb': sat_pdb,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bandwidth', type=float, default=5.0, help='cell bandwidth in MHz')
    ap.add_argument('--numerology', type=int, default=0)
    ap.add_argument('--tag', default='')
    ap.add_argument('--app-duration', type=int, default=20000,
                    help='simulated milliseconds per run')
    ap.add_argument('--pdb-ms', type=float, default=10.0)
    ap.add_argument('--num-sites', type=int, default=1)
    ap.add_argument('--rng-run', type=int, default=1)
    ap.add_argument('--ues', nargs='+', type=int, default=[1, 2, 3, 4, 5, 6],
                    help='UEs per XR type (AR/VR/CG); total = 3x this value')
    args = ap.parse_args()

    rows = []
    for per_type in args.ues:
        print('== {} UEs per type ({} total) =='.format(per_type, per_type * 3), flush=True)
        text = run_one(per_type, args.bandwidth, args.numerology, args.app_duration,
                       args.num_sites, args.rng_run)
        row = summarise(text, per_type, args.pdb_ms, args.num_sites, args.rng_run)
        if row:
            rows.append(row)
            print('   video ratio {:.1%}, delay {:.0f} ms, satisfied {:.0%}'.format(
                row['video_ratio_mean'], row['video_delay_mean_ms'],
                row['satisfied_ue_ratio']), flush=True)

    suffix = args.tag or '{:g}mhz'.format(args.bandwidth)
    raw_dir = os.path.join(HERE, 'results', 'raw')
    os.makedirs(raw_dir, exist_ok=True)
    out_json = os.path.join(raw_dir, 'capacity_sweep_{}.json'.format(suffix))
    json.dump(rows, open(out_json, 'w', encoding='utf-8'), indent=2)

    lines = ['# RTSR 容量扫描（{} 小区，{:g} MHz，{:g} s）'.format(
        args.num_sites, args.bandwidth, args.app_duration / 1000.0), '',
             '由 `capacity_sweep.py` 生成。每档 UE 数 = AR:VR:CG 各 N 个。',
             '满意度判据：该 UE 的视频流投递率 ≥ 99.5%（论文定义）。', '',
             '| UE 数/小区 | 视频投递率 | 平均时延 | SR 模型投递率 | 满意(投递率) | 满意(+PDB) |',
             '|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        sr = '{:.1%}'.format(r['sr_ratio_mean']) if r['sr_ratio_mean'] is not None else '-'
        lines.append('| {} | {:.1%} | {:.0f} ms | {} | {:.0%} | {:.0%} |'.format(
            r['ues_per_cell'], r['video_ratio_mean'], r['video_delay_mean_ms'],
            sr, r['satisfied_ue_ratio'], r['satisfied_ue_ratio_pdb']))
    lines += ['', '注意：这是**单小区（{:g} MHz）**下的趋势，不是论文 Fig.5 的'.format(args.bandwidth),
              '21 cell wraparound 容量曲线；不同带宽下的绝对值不可直接比较。']
    md = '\n'.join(lines) + '\n'
    open(os.path.join(raw_dir, 'capacity_sweep_{}.md'.format(suffix)), 'w', encoding='utf-8').write(md)
    print(md)


if __name__ == '__main__':
    main()