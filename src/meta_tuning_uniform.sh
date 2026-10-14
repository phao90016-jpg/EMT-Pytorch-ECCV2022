cd "$(dirname "$0")"

# 路径变量
MAML=/home/penghao/code/EMT-Pytorch-ECCV2022/experiment/experiment/local_maml_espcn_x2_p144_b8_e50/model/46/model_best.pt
DATA=/home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1
EXP=/home/penghao/code/EMT-Pytorch-ECCV2022/experiment
MASK_DIR=/home/penghao/code/EMT-Pytorch-ECCV2022/grad_mask

# 共用参数（注意：data_train 用 DIV2K，不是 DIV2K_PSNR）
COMMON="--model espcn --scale 2 --patch_size 144 --batch_size 8 --maml \
  --data_train DIV2K --data_test DIV2K --is45s \
  --dir_data $DATA --save_every"

# ============ MG1 uniform: 1-150, p_mask=0.20 ============
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG1_uniform \
  --pre_train $MAML --reset \
  --data_range 1-150/1-150 \
  --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.20 --data_partion 0.20 \
  --dir_mask $MASK_DIR/mask_lol_uniform_MG1.pt

CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG1_uniform \
  --pre_train $MAML --reset \
  --data_range 1-150/1-150 \
  --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.20 --data_partion 0.20 \
  --dir_mask $MASK_DIR/mask_lol_uniform_MG1.pt

# ============ MG3 uniform: 301-450, p_mask=0.01, pre_train=MG2_uniform ============
# 注意：为了公平对比，MG3_uniform 的 pre_train 应该是 MG2_uniform 的结果
# 为了简化，先跳过 MG2_uniform，直接用 MG3 的链式结构（pre_train=MG2）
# 如果只跑 MG3_uniform，可以改为 pre_train=MG2（PSNR优先版），但这会引入混淆
# 更严谨的做法是先补 MG2_uniform。下面给出补全版：

# ---- MG2 uniform: 151-300, p_mask=0.01 ----
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG2_uniform \
  --pre_train $EXP/local_tuning_lol_MG1_uniform/model/model_best.pt --reset \
  --data_range 151-300/151-300 \
  --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.01 --data_partion 0.20 \
  --dir_mask $MASK_DIR/mask_lol_uniform_MG2.pt

CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG2_uniform \
  --pre_train $EXP/local_tuning_lol_MG1_uniform/model/model_best.pt --reset \
  --data_range 151-300/151-300 \
  --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.01 --data_partion 0.20 \
  --dir_mask $MASK_DIR/mask_lol_uniform_MG2.pt

# ---- MG3 uniform: 301-450, p_mask=0.01, pre_train=MG2_uniform ----
CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG3_uniform \
  --pre_train $EXP/local_tuning_lol_MG2_uniform/model/model_best.pt --reset \
  --data_range 301-450/301-450 \
  --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.01 --data_partion 0.20 \
  --dir_mask $MASK_DIR/mask_lol_uniform_MG3.pt

CUDA_VISIBLE_DEVICES=0 python main.py $COMMON \
  --save $EXP/local_tuning_lol_MG3_uniform \
  --pre_train $EXP/local_tuning_lol_MG2_uniform/model/model_best.pt --reset \
  --data_range 301-450/301-450 \
  --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.01 --data_partion 0.20 \
  --dir_mask $MASK_DIR/mask_lol_uniform_MG3.pt
