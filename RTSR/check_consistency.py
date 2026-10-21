"""Cross-check key numbers across the RTSR documents."""
import glob
import os
import re

R = '/home/penghao/code/EMT-Pytorch-ECCV2022/RTSR'
FILES = ['答辩提纲.md', 'RTSR_复现对照表.md', 'RTSR_TOTAL_REPORT.md', 'README.md',
         'results/latency.md', 'results/seed_variance.md',
         'results/capacity_sweep_summary.md', 'results/multicell_summary.md']

# canonical metric -> regex that should match exactly this value
CANON = [
    ('VMAF @5Mbps (local)',      r'90\.99'),
    ('VMAF @5Mbps (paper)',      r'90\.09'),
    ('traffic saving ΔT=6s',     r'43\.0%'),
    ('traffic saving ΔT=60s',    r'49\.3%'),
    ('SR model @24UE',           r'36\.4%'),
    ('M2->M3 per doubling',      r'0\.179'),
    ('paper M2->M3',             r'0\.075'),
    ('latency M2 @2160p',        r'218\.6'),
    ('FPS M2 @2160p',            r'4\.6'),
    ('seed variance',            r'2\.4'),
    ('multicell 7site 20MHz',    r'94\.2%'),
    ('single 20MHz 15UE',        r'64\.9%'),
    ('Table I M2 540p',          r'35\.702'),
    ('Table II 4K PSNR @5Mbps',  r'42\.295'),
    ('capacity knee',            r'10[–-]20 MHz'),
]

# superseded values that must not appear anywhere
STALE = [
    ('781 KB (old model size)',  r'781 ?KB'),
    ('45 % (old saving)',        r'45%'),
    ('36.22 (old 32-feat PSNR)', r'36\.22'),
    ('82 % (old progress)',      r'82%'),
    ('❌ Fig.4',                 r'❌\s*Fig\.4'),
    ('~68-93 ms (old latency)',  r'68[–-]93'),
    ('first-session 24.58',      r'24\.58'),
]

print('=== coverage of canonical numbers ===')
print('{:<26}'.format('metric') + ''.join('{:<6}'.format(f.split('/')[-1][:5]) for f in FILES))
for label, pat in CANON:
    marks = []
    for f in FILES:
        p = os.path.join(R, f)
        hit = 'Y' if os.path.isfile(p) and re.search(pat, open(p, encoding='utf-8').read()) else '.'
        marks.append(hit)
    print('{:<26}'.format(label) + ''.join('{:<6}'.format(m) for m in marks))

print()
print('=== stale values still present ===')
found = False
for label, pat in STALE:
    hits = []
    for f in FILES:
        p = os.path.join(R, f)
        if not os.path.isfile(p):
            continue
        s = open(p, encoding='utf-8').read()
        m = re.search(pat, s)
        if m:
            line = s[:m.start()].count('\n') + 1
            hits.append('{}:{}'.format(f, line))
    if hits:
        found = True
        print('  {} -> {}'.format(label, ', '.join(hits)))
if not found:
    print('  none')

print()
print('=== numeric agreements ===')
pairs = [
    ('答辩提纲', 'RTSR_复现对照表.md', r'43\.0%'),
    ('答辩提纲', 'RTSR_TOTAL_REPORT.md', r'49\.3%'),
    ('RTSR_复现对照表.md', 'RTSR_TOTAL_REPORT.md', r'90\.99'),
]
for a, b, pat in pairs:
    pa, pb = os.path.join(R, a if a.endswith('.md') else a + '.md'), os.path.join(R, b)
    ha = re.search(pat, open(pa, encoding='utf-8').read()) is not None if os.path.isfile(pa) else None
    hb = re.search(pat, open(pb, encoding='utf-8').read()) is not None if os.path.isfile(pb) else None
    print('  {} vs {} [{}]: {} / {}'.format(a, b, pat, ha, hb))