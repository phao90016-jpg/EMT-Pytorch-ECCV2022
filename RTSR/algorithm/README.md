# RTSR 算法层：工具与运行脚本

本目录是 `EDSR-PyTorch` 侧的**增量部分**，用于复现论文 Table I / Table II。
上游仓库是 [yjn870/EDSR-PyTorch](https://github.com/yjn870/EDSR-PyTorch)（官方 EDSR 实现），
本目录不重复存放上游代码，只放：

```
algorithm/
├── tools/                  # 数据准备、训练监控、结果汇总
│   ├── model_stats.py      参数量解析式（与 torch 实测交叉校验）
│   ├── collect_table1.py   扫实验目录 → TABLE1*.md
│   ├── collect_table2.py   码率-质量表（含 VMAF 列）
│   ├── collect_dt.py       在线训练窗扫描汇总
│   ├── make_vmaf.py        导出 SR/HR 序列并用 libvmaf 算分
│   ├── encode_ld.sh        540p LD 多码率编码（x264 2-pass）
│   ├── encode_ld_4k.sh     1080p LD @3-5 Mbps 编码（论文原始设置）
│   ├── make_4k_dataset.sh  从 4K 源抽帧，生成 1080p→2160p 数据集
│   └── prepare_*_bins.sh   用硬链接复用 pickle 缓存
├── run_table1.sh           M1/M2/M3 @ 540p→1080p
├── run_table1_4k.sh        M1/M2/M3 @ 1080p→2160p（干净 bicubic）
├── run_table2.sh           6 个码率的专属模型 + 通用基线（540p）
├── run_table2_4k.sh        3-5 Mbps 五个码率（1080p→2160p）
├── run_4k_5000.sh          5 Mbps 补 M1/M3 + 4K VMAF
├── run_dt_sweep.sh         在线训练窗扫描
└── patches/
    └── edsr_template.patch 对上游的两处改动（见下）
```

## 对上游的两处改动

```bash
cd EDSR-PyTorch
git apply algorithm/patches/edsr_template.patch
```

1. `src/model/edsr.py`：`url[...]` → `url.get(..., '')`
   原代码无条件查 `url` 字典，`--n_feats 9` / `26` 等论文配置一启动就 `KeyError`。
2. `src/template.py`：新增 `RTSR_M1` / `RTSR_M2` / `RTSR_M3` 预设
   （8 块/9 特征、8 块/26 特征、16 块/64 特征），一条 `--template` 即可切换。

## 复现步骤

```bash
# 0) 环境：本项目统一使用 emt-env
PY=~/code/EMT-Pytorch-ECCV2022/emt-env/bin/python

# 1) 把 tools/ 与 run_*.sh 放到 EDSR-PyTorch 根目录，按相对路径引用 src/
cp -r algorithm/tools        ~/code/EDSR-PyTorch/
cp    algorithm/run_*.sh     ~/code/EDSR-PyTorch/
cd ~/code/EDSR-PyTorch && git apply algorithm/patches/edsr_template.patch

# 2) Table I（540p→1080p）
bash run_table1.sh

# 3) Table II（540p，码率按像素 1/4 缩放）+ 通用基线
bash run_table2.sh
$PY tools/make_vmaf.py && $PY tools/collect_table2.py

# 4) 论文原始设置（1080p→2160p）
bash tools/make_4k_dataset.sh   # 需要 4K 源视频
bash run_table1_4k.sh
bash run_table2_4k.sh
$PY tools/make_vmaf.py --pattern 'experiment_t2_4k_b{}' --data-dir 'dataset/4k_b{}' \
    --rates 3000 3500 4000 4500 5000 --out vmaf_results_4k.json
```

结果表在 `../results/`，结论与偏差声明见 `../results/P1_REPORT.md`。