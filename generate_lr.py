"""从 DIV2K 高清图批量生成 2 倍下采样的低清图（bicubic）。

本项目自研的辅助脚本：训练超分模型需要成对的「高清 / 低清」样本，
这里用 PIL 的 bicubic 把 DIV2K_train_HR 缩到 X2 目录，作为训练输入。
"""

from pathlib import Path
from PIL import Image

root = Path.home() / "code/EMT-Pytorch-ECCV2022/data/DIV2K"
src_dir = root / "DIV2K_train_HR"
dst_dir = root / "DIV2K_train_LR_bicubic" / "X2"
dst_dir.mkdir(parents=True, exist_ok=True)

files = sorted(src_dir.glob("*.png"))
print(f"Found {len(files)} HR images")
for i, f in enumerate(files, 1):
    img = Image.open(f).convert("RGB")
    w, h = img.size
    lr = img.resize((w // 2, h // 2), Image.BICUBIC)
    out_name = f.stem + "x2.png"          # 0001.png -> 0001x2.png
    lr.save(dst_dir / out_name)
    if i % 100 == 0:
        print(f"  {i}/{len(files)} done")
print("All done.")
