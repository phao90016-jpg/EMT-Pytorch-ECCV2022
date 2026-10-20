"""Compute VMAF for a set of trained Table-II bitrate variants.

    python3 tools/make_vmaf.py                                   # 540p -> vmaf_results.json
    python3 tools/make_vmaf.py --pattern 'experiment_t2_4k_b{}' \
        --data-dir 'dataset/4k_b{}' --rates 3000 3500 4000 4500 5000 \
        --out vmaf_results_4k.json                               # paper setting

Needs an ffmpeg built with --enable-libvmaf (the system 6.1.1 has none).
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
PY = sys.executable
FFMPEG = os.environ.get(
    'VMAF_FFMPEG', '/home/penghao/bin/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg')
VMAF_RE = re.compile(r'VMAF score:\s*([0-9.]+)')


def dump(exp_name, data_dir):
    exp = os.path.join(ROOT, exp_name)
    best = os.path.join(exp, 'model', 'model_best.pt')
    if not os.path.isfile(best):
        print('  skip {}: no checkpoint'.format(exp_name))
        return None
    cmd = [PY, 'main.py', '--template', 'RTSR_M2', '--model', 'EDSR',
           '--scale', '2', '--data_test', 'DIV2K', '--data_range', '401-495',
           '--dir_data', '../{}'.format(data_dir), '--test_only',
           '--pre_train', '../{}/model/model_best.pt'.format(exp_name),
           '--save_results', '--save_gt', '--save', '../{}'.format(exp_name)]
    subprocess.run(cmd, cwd=SRC, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.join(exp, 'results-DIV2K')


def sequences(results_dir, tmp):
    srs = sorted(glob.glob(os.path.join(results_dir, '*_SR.png')))
    if not srs:
        return None, None
    sr_dir, hr_dir = os.path.join(tmp, 'sr'), os.path.join(tmp, 'hr')
    for d in (sr_dir, hr_dir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    n = 0
    for sr_path in srs:
        hr_path = sr_path.replace('_SR.png', '_HR.png')
        if not os.path.isfile(hr_path):
            continue
        n += 1
        os.symlink(os.path.abspath(sr_path), os.path.join(sr_dir, '{:04d}.png'.format(n)))
        os.symlink(os.path.abspath(hr_path), os.path.join(hr_dir, '{:04d}.png'.format(n)))
    return (sr_dir, hr_dir) if n else (None, None)


def vmaf(sr_dir, hr_dir):
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'info',
           '-i', os.path.join(sr_dir, '%04d.png'),
           '-i', os.path.join(hr_dir, '%04d.png'),
           '-lavfi', 'libvmaf', '-f', 'null', '-']
    proc = subprocess.run(cmd, capture_output=True, text=True)
    hit = VMAF_RE.search(proc.stderr)
    if not hit:
        print('    ffmpeg rc={} tail={}'.format(
            proc.returncode, proc.stderr.strip().splitlines()[-2:]))
    return float(hit.group(1)) if hit else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pattern', default='experiment_t2_b{}')
    ap.add_argument('--data-dir', default='dataset/ld_b{}')
    ap.add_argument('--rates', nargs='+', type=int,
                    default=[750, 875, 1000, 1125, 1250, 2500])
    ap.add_argument('--out', default='vmaf_results.json')
    args = ap.parse_args()

    if not os.access(FFMPEG, os.X_OK):
        raise SystemExit('libvmaf ffmpeg not found: {}'.format(FFMPEG))

    tmp = '/tmp/vmaf_seq'
    result = {}
    for rate in args.rates:
        exp_name = args.pattern.format(rate)
        data_dir = args.data_dir.format(rate)
        print('== {} kbps ({}) =='.format(rate, exp_name))
        results_dir = dump(exp_name, data_dir)
        if not results_dir:
            continue
        sr_dir, hr_dir = sequences(results_dir, tmp)
        if not sr_dir:
            print('  no dumped frames')
            continue
        score = vmaf(sr_dir, hr_dir)
        print('  VMAF = {}'.format(score))
        if score is not None:
            result[str(rate)] = score

    out = os.path.join(ROOT, args.out)
    json.dump(result, open(out, 'w', encoding='utf-8'), indent=2)
    print('written:', out)


if __name__ == '__main__':
    main()