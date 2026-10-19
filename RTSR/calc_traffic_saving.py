"""Quantify the RTSR traffic saving from an ns-3 FlowMonitor dump.

Usage (from RTSR/):

    python3 calc_traffic_saving.py --ns3-log rtsr_output.txt --duration 60 --ues 3
    python3 calc_traffic_saving.py --ns3-log rtsr_output.txt --hd-ld-ratio 2.0

Measured vs assumed
-------------------
measured : every flow's offered (Tx) and delivered (Rx) bytes, from the
           FlowMonitor block printed by rtsr-simulation.cc.
assumed  : (a) the conventional (non-RTSR) stream is NOT simulated; it is
           video_bytes * hd_ld_ratio (default 2.0 = 20 Mbps vs 10 Mbps).
           (b) all UEs receive the same stream, so per-UE figures divide the
           aggregate by --ues.

Everything is reported both aggregate and per-UE; the per-UE numbers are the ones
comparable to the paper's 10 Mbps / 20 Mbps per-user framing.
"""

import argparse
import os
import re

FLOW_RE = re.compile(
    r'^Flow\s+(\d+)\s+\(([0-9.]+):(\d+)\s+->\s+([0-9.]+):(\d+)\)\s+proto\s+(\w+)')
FIELD_RE = re.compile(
    r'^\s+(Tx Packets|Tx Bytes|TxOffered|Rx Bytes|Throughput|Mean delay|'
    r'Mean jitter|Rx Packets):\s+([0-9.eE+-]+)\s*(\w+)?')

SR_MODEL_PORT = 5000


def parse_flows(path):
    flows = []
    current = None
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            hit = FLOW_RE.match(line)
            if hit:
                current = {
                    'id': int(hit.group(1)),
                    'dst_port': int(hit.group(5)),
                    'tx_bytes': 0,
                    'rx_bytes': 0,
                    'delay_ms': 0.0,
                }
                flows.append(current)
                continue
            if current is None:
                continue
            hit = FIELD_RE.match(line)
            if not hit:
                continue
            key, value = hit.group(1), float(hit.group(2))
            if key == 'Tx Bytes':
                current['tx_bytes'] = int(value)
            elif key == 'Rx Bytes':
                current['rx_bytes'] = int(value)
            elif key == 'Mean delay':
                current['delay_ms'] = value
    return flows


def to_mb(num_bytes):
    return num_bytes / (1024.0 * 1024.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ns3-log', default='rtsr_output.txt')
    ap.add_argument('--duration', type=float, default=60.0)
    ap.add_argument('--hd-ld-ratio', type=float, default=2.0)
    ap.add_argument('--ues', type=int, default=3,
                    help='number of UEs sharing the same stream (per-UE split)')
    ap.add_argument('--model-kb', type=float, default=530.0,
                    help='size of one SR model update in KiB (paper M2 = 530)')
    args = ap.parse_args()

    if not os.path.isfile(args.ns3_log):
        raise SystemExit('ns-3 log not found: {}'.format(args.ns3_log))
    flows = parse_flows(args.ns3_log)
    if not flows:
        raise SystemExit('no FlowMonitor blocks found in {}'.format(args.ns3_log))

    for f in flows:
        f['kind'] = 'SR model' if f['dst_port'] == SR_MODEL_PORT else 'XR video'

    print('=== per-flow (measured) ===')
    print('{:<6}{:>10}{:>10}{:>12}{:>12}{:>10}{:>11}'.format(
        'flow', 'dst port', 'kind', 'tx (MB)', 'rx (MB)', 'rx/tx', 'delay (ms)'))
    for f in flows[:8]:
        ratio = (f['rx_bytes'] / f['tx_bytes']) if f['tx_bytes'] else 0.0
        print('{:<6}{:>10}{:>10}{:>12.3f}{:>12.3f}{:>10.1%}{:>11.1f}'.format(
            f['id'], f['dst_port'], f['kind'], to_mb(f['tx_bytes']),
            to_mb(f['rx_bytes']), ratio, f['delay_ms']))
    if len(flows) > 8:
        print('... {} more flows'.format(len(flows) - 8))

    video_tx = sum(f['tx_bytes'] for f in flows if f['kind'] == 'XR video')
    video_rx = sum(f['rx_bytes'] for f in flows if f['kind'] == 'XR video')
    sr_tx = sum(f['tx_bytes'] for f in flows if f['kind'] == 'SR model')
    sr_rx = sum(f['rx_bytes'] for f in flows if f['kind'] == 'SR model')

    ues = max(args.ues, 1)
    model_bytes = args.model_kb * 1024.0
    updates_total = (sr_tx / model_bytes) if model_bytes else 0.0

    print()
    print('=== aggregate over {:.0f} s ({} UEs) ==='.format(args.duration, ues))
    print('XR video   offered {:9.3f} MB | delivered {:9.3f} MB  ({:.1%})'.format(
        to_mb(video_tx), to_mb(video_rx), video_rx / video_tx if video_tx else 0))
    print('SR models  offered {:9.3f} MB | delivered {:9.3f} MB  ({:.1%})'.format(
        to_mb(sr_tx), to_mb(sr_rx), sr_rx / sr_tx if sr_tx else 0))
    print('model updates observed: {:.1f} in total ({:.1f} per UE)'.format(
        updates_total, updates_total / ues))

    print()
    print('=== per UE (the comparable unit) ===')
    v_tx, v_rx = to_mb(video_tx) / ues, to_mb(video_rx) / ues
    m_tx = to_mb(sr_tx) / ues
    conv = v_tx * args.hd_ld_ratio
    print('LD video  offered {:8.3f} MB | delivered {:8.3f} MB  -> {:.2f} Mbps'.format(
        v_tx, v_rx, v_tx * 8.0 / args.duration))
    print('SR models offered {:8.3f} MB'.format(m_tx))
    print('RTSR total        {:8.3f} MB'.format(v_tx + m_tx))
    print('conventional HD   {:8.3f} MB  (assumed = LD x {:.2f})'.format(conv, args.hd_ld_ratio))
    print('traffic saved     {:.1f}%'.format(100.0 * (1.0 - (v_tx + m_tx) / conv)))

    print()
    print('=== update-period sensitivity (per UE) ===')
    print('{:<8}{:>10}{:>14}{:>14}{:>10}'.format(
        'period', 'updates', 'model (MB)', 'overhead', 'saved'))
    for period in (2.0, 6.0, 10.0, 30.0, 60.0):
        n = args.duration / period
        model_total = n * to_mb(model_bytes)
        total = v_tx + model_total
        mbps = to_mb(model_bytes) * 8.0 / period
        print('{:<8}{:>10.0f}{:>14.3f}{:>11.2f} Mbps{:>9.1f}%'.format(
            '{:.0f} s'.format(period), n, model_total, mbps,
            100.0 * (1.0 - total / conv)))

    print()
    print('notes: 1) the HD stream is NOT simulated; it is LD x --hd-ld-ratio.')
    print('       2) per-UE numbers assume every UE receives the same stream.')
    print('       3) this simulation runs the 3GPP XR traffic mix, so the')
    print('          per-UE video rate is not the paper\'s 10 Mbps.')


if __name__ == '__main__':
    main()