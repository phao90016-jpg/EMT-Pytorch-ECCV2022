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
