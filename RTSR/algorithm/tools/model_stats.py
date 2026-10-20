"""Report parameter count and on-wire size of the EDSR variants used in the
RTSR (WCNC 2023) Table I.

Run from anywhere (PyTorch optional -- it is only used as a cross-check):

    /home/penghao/code/EMT-Pytorch-ECCV2022/emt-env/bin/python \
        EDSR-PyTorch/tools/model_stats.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

PRESETS = (('M1', 8, 9), ('M2', 8, 26), ('M3', 16, 64))


def n_params_analytic(blocks, feats, scale, colors=3, k=3):
    """Parameter count of src/model/edsr.py, biases included.

    head        : C*F*k*k + F
    res block   : 2 * (F*F*k*k + F)              x blocks
    body conv   : F*F*k*k + F
    upsampler   : F*(mF)*k*k + mF                x log2(scale) stages, m=4 (m=9 for x3)
    tail conv   : F*C*k*k + C
    (MeanShift adds 2*(C*C + C) = 24 frozen parameters, omitted.)
    """
    total = colors * feats * k * k + feats
    total += blocks * 2 * (feats * feats * k * k + feats)
    total += feats * feats * k * k + feats
    if scale == 3:
        total += feats * 9 * feats * k * k + 9 * feats
    else:
        n = scale
        while n > 1:
            total += feats * 4 * feats * k * k + 4 * feats
            n //= 2
    total += feats * colors * k * k + colors
    return total


def n_params_torch(blocks, feats, scale, colors=3):
    from importlib import import_module

    class _A(object):
        pass

    a = _A()
    a.model = 'EDSR'
    a.n_resblocks = blocks
    a.n_feats = feats
    a.scale = [scale]
    a.n_colors = colors
    a.rgb_range = 255
    a.res_scale = 1
    a.shift_mean = True
    net = import_module('model.edsr').make_model(a)
    return sum(p.numel() for p in net.parameters())


def main():
    scale = 2
    header = '{:<6}{:>7}{:>7}{:>15}{:>14}{:>11}{:>11}'.format(
        'model', 'blocks', 'feats', 'params(anal.)', 'params(torch)', 'fp32 KB', 'fp16 KB')
    print('EDSR x{} (3-channel input, 3x3 kernels)'.format(scale))
    print(header)
    print('-' * len(header))
    torch_ok = True
    for name, blocks, feats in PRESETS:
        n = n_params_analytic(blocks, feats, scale)
        if torch_ok:
            try:
                t = '{:,}'.format(n_params_torch(blocks, feats, scale))
            except Exception:
                torch_ok = False
                t = 'n/a'
        else:
            t = 'n/a'
        print('{:<6}{:>7}{:>7}{:>15,}{:>14}{:>11.1f}{:>11.1f}'.format(
            name, blocks, feats, n, t, n * 4 / 1024, n * 2 / 1024))
    print()
    print('paper (Table I):  M1 26 KB / 33.22 dB | M2 530 KB / 35.78 dB | M3 5362 KB / 36.03 dB')


if __name__ == '__main__':
    main()