cd "$(dirname "$0")"

# 路径变量（集中管理，方便修改）
MAML=/home/penghao/code/EMT-Pytorch-ECCV2022/experiment/experiment/local_maml_espcn_x2_p144_b8_e50/model/46/model_best.pt
DATA=/home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1
MASK=/home/penghao/code/EMT-Pytorch-ECCV2022/grad_mask/mask_lol.pt
EXP=/home/penghao/code/EMT-Pytorch-ECCV2022/experiment

COMMON="--model espcn --scale 2 --patch_size 144 --batch_size 8 --maml \
  --data_train DIV2K_PSNR --data_test DIV2K --is45s \
  --dir_data $DATA --save_every --dir_mask $MASK"

# ============ MG1: 1-150, p_mask=0.20 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG1 \
  --pre_train $MAML --reset \
  --data_range 1-150/1-150 \
  --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.20 --data_partion 0.20

CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG1 \
  --pre_train $MAML --reset \
  --data_range 1-150/1-150 \
  --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.20 --data_partion 0.20

# ============ MG2: 151-300, p_mask=0.01, pre_train=MG1 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG2 \
  --pre_train $EXP/local_tuning_lol_MG1/model/model_best.pt --reset \
  --data_range 151-300/151-300 \
  --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.01 --data_partion 0.20

CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG2 \
  --pre_train $EXP/local_tuning_lol_MG1/model/model_best.pt --reset \
  --data_range 151-300/151-300 \
  --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.01 --data_partion 0.20

# ============ MG3: 301-450, p_mask=0.01, pre_train=MG2 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG3 \
  --pre_train $EXP/local_tuning_lol_MG2/model/model_best.pt --reset \
  --data_range 301-450/301-450 \
  --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.01 --data_partion 0.20

CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG3 \
  --pre_train $EXP/local_tuning_lol_MG2/model/model_best.pt --reset \
  --data_range 301-450/301-450 \
  --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.01 --data_partion 0.20