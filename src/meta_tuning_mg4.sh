cd "$(dirname "$0")"

# ============ MG4: 451-495, p_mask=0.01, pre_train=MG3 ============
CUDA_VISIBLE_DEVICES=0 python main.py \
  --model espcn --scale 2 --patch_size 144 --batch_size 8 \
  --maml \
  --save /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/local_tuning_lol_MG4 \
  --pre_train /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/local_tuning_lol_MG3/model/model_best.pt \
  --reset \
  --data_train DIV2K_PSNR --data_test DIV2K \
  --data_range 451-495/451-495 --is45s \
  --dir_data /home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1 \
  --save_every --find_mask --epochs 2 --test_every 1000 \
  --p_mask 0.01 --data_partion 0.20 \
  --dir_mask /home/penghao/code/EMT-Pytorch-ECCV2022/grad_mask/mask_lol.pt

CUDA_VISIBLE_DEVICES=0 python main.py \
  --model espcn --scale 2 --patch_size 144 --batch_size 8 \
  --maml \
  --save /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/local_tuning_lol_MG4 \
  --pre_train /home/penghao/code/EMT-Pytorch-ECCV2022/experiment/local_tuning_lol_MG3/model/model_best.pt \
  --reset \
  --data_train DIV2K_PSNR --data_test DIV2K \
  --data_range 451-495/451-495 --is45s \
  --dir_data /home/penghao/code/EMT-Pytorch-ECCV2022/data/VSD4K/lol_15s_1 \
  --save_every --grad_mask --epochs 2 --test_every 100 \
  --p_mask 0.01 --data_partion 0.20 \
  --dir_mask /home/penghao/code/EMT-Pytorch-ECCV2022/grad_mask/mask_lol.pt
