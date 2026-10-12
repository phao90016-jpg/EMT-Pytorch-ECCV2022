cd "$(dirname "$0")"

# ===== MG1: find_mask =====
CUDA_VISIBLE_DEVICES=0 python main.py \
  --model espcn --scale 2 --patch_size 144 --batch_size 8 \
  --maml \
  --save /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/local_tuning_lol_MG1 \
  --pre_train /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/experiment/local_maml_espcn_x2_p144_b8_e50/model/46/model_best.pt \
  --reset \
  --data_train DIV2K --data_test DIV2K \
  --data_range 1-150/1-150 \
  --is45s \
  --dir_data /home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1 \
  --save_every --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.20 --data_partion 0.20 \
  --dir_mask /home/penghao/code/EMT-Pytorch-ECCV2022/grad_mask/mask_lol.pt

# ===== MG1: grad_mask =====
CUDA_VISIBLE_DEVICES=0 python main.py \
  --model espcn --scale 2 --patch_size 144 --batch_size 8 \
  --maml \
  --save /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/local_tuning_lol_MG1 \
  --pre_train /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/experiment/local_maml_espcn_x2_p144_b8_e50/model/46/model_best.pt \
  --reset \
  --data_train DIV2K --data_test DIV2K \
  --data_range 1-150/1-150 \
  --is45s \
  --dir_data /home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1 \
  --save_every --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.20 --data_partion 0.20 \
  --dir_mask /home/penghao/code/EMT-Pytorch-ECCV2022/grad_mask/mask_lol.pt