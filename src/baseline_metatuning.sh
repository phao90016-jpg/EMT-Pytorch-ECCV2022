cd "$(dirname "$0")"

MAML=/home/penghao/code/EMT-Pytorch-ECCV2022/experiment/experiment/local_maml_espcn_x2_p144_b8_e50/model/46/model_best.pt
DATA=/home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1
EXP=/home/penghao/code/EMT-Pytorch-ECCV2022/experiment

COMMON="--model espcn --scale 2 --patch_size 144 --batch_size 8 --maml \
  --data_train DIV2K_PSNR --data_test DIV2K --is45s \
  --dir_data $DATA --save_every"

# ============ MG1: 1-150 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/baseline_lol_metatuning_MG1 --pre_train $MAML --reset \
  --data_range 1-150/1-150 --epochs 2 --test_every 100

# ============ MG2: 151-300 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/baseline_lol_metatuning_MG2 \
  --pre_train $EXP/baseline_lol_metatuning_MG1/model/model_best.pt --reset \
  --data_range 151-300/151-300 --epochs 2 --test_every 100

# ============ MG3: 301-450 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/baseline_lol_metatuning_MG3 \
  --pre_train $EXP/baseline_lol_metatuning_MG2/model/model_best.pt --reset \
  --data_range 301-450/301-450 --epochs 2 --test_every 100

# ============ MG4: 451-495 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/baseline_lol_metatuning_MG4 \
  --pre_train $EXP/baseline_lol_metatuning_MG3/model/model_best.pt --reset \
  --data_range 451-495/451-495 --epochs 2 --test_every 100
