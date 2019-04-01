import argparse
import os
from util import util
import torch
import GPUtil
import numpy as np


class Options():
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.initialized = False

    def initialize(self):
        self.parser.add_argument('--gpu_ids', type=str, default='auto', help='auto or gpu_ids seperated by comma.')

        self.parser.add_argument('--dataset', type=str, default='modelnet', help='modelnet / shrec / shapenet')
        self.parser.add_argument('--dataroot', default='/ssd/jiaxin/dataset/modelnet40-normal_numpy/', help='path to images & laser point clouds')
        self.parser.add_argument('--classes', type=int, default=10, help='ModelNet40 or ModelNet10')
        self.parser.add_argument('--name', type=str, default='train', help='name of the experiment. It decides where to store samples and models')
        self.parser.add_argument('--checkpoints_dir', type=str, default='./checkpoints', help='models are saved here')

        self.parser.add_argument('--batch_size', type=int, default=8, help='input batch size')
        self.parser.add_argument('--input_pc_num', type=int, default=1024, help='# of input points')
        self.parser.add_argument('--surface_normal', type=bool, default=True, help='use surface normal in the pc input')
        self.parser.add_argument('--nThreads', default=8, type=int, help='# threads for loading data')

        self.parser.add_argument('--display_winsize', type=int, default=256, help='display window size')
        self.parser.add_argument('--display_id', type=int, default=1, help='window id of the web display')

        self.parser.add_argument('--feature_num', type=int, default=1024, help='length of encoded feature')
        self.parser.add_argument('--activation', type=str, default='relu', help='activation function: relu, elu')
        self.parser.add_argument('--normalization', type=str, default='batch', help='normalization function: batch, instance')

        self.parser.add_argument('--lr', type=float, default=0.0005, help='learning rate')
        self.parser.add_argument('--dropout', type=float, default=0.7, help='probability of an element to be zeroed')
        self.parser.add_argument('--node_num', type=int, default=64, help='som node number')
        self.parser.add_argument('--k', type=int, default=3, help='k nearest neighbor')
        self.parser.add_argument('--pretrain', type=str, default=None, help='pre-trained encoder dict path')
        self.parser.add_argument('--pretrain_lr_ratio', type=float, default=1, help='learning rate ratio between pretrained encoder and classifier')

        self.parser.add_argument('--som_k', type=int, default=9, help='k nearest neighbor of SOM nodes searching on SOM nodes')
        self.parser.add_argument('--som_k_type', type=str, default='avg', help='avg / center')

        self.parser.add_argument('--random_pc_dropout_lower_limit', type=float, default=1, help='keep ratio lower limit')
        self.parser.add_argument('--bn_momentum', type=float, default=0.1, help='normalization momentum, typically 0.1. Equal to (1-m) in TF')
        self.parser.add_argument('--bn_momentum_decay_step', type=int, default=None, help='BN momentum decay step. e.g, 0.5->0.01.')
        self.parser.add_argument('--bn_momentum_decay', type=float, default=0.5, help='BN momentum decay step. e.g, 0.5->0.01.')

        self.parser.add_argument('--rot_equivariant_pooling_mode', type=str, default='per-hierarchy', help='global, per-hierarchy')
        self.parser.add_argument('--rot_equivariant_mode', type=str, default='3d', help='2d, 3d (cube group, tetrahedral group, klein 4-group)')
        self.parser.add_argument('--rot_equivariant_no', type=int, default=4, help='Number of rotations encoded in the rotation equivariant network.')
        # self.parser.add_argument('--rot_horizontal', type=bool, default=False, help='Rotation augmentation around vertical axis.')
        # self.parser.add_argument('--rot_3d', type=bool, default=True, help='Rotation augmentation around xyz axis.')
        self.parser.add_argument('--rot_perturbation', type=bool, default=False, help='Small rotation augmentation around 3 axis.')
        self.parser.add_argument('--translation_perturbation', type=bool, default=False, help='Small translation augmentation around 3 axis.')

        self.parser.add_argument('--weight_decay_l2', type=float, default=0, help='L2 weight decay.')

        self.initialized = True

    def parse(self):
        if not self.initialized:
            self.initialize()
        self.opt = self.parser.parse_args()

        # === processing options === begin ===
        # determine which GPU to use
        # auto, throw exception when no GPU is available
        if self.opt.gpu_ids == 'auto':
            GPUtil.showUtilization()
            deviceIDs = GPUtil.getAvailable(order='first', limit=4, maxLoad=0.5, maxMemory=0.5,
                                            excludeID=[], excludeUUID=[])
            deviceID_costs = [-1*x for x in deviceIDs]
            # reorder the deviceID according to the computational capacity, i.e., total memory size
            # memory size is divided by 1000 without remainder, to avoid small fluctuation
            gpus = GPUtil.getGPUs()
            memory_size_costs = [-1*(gpu.memoryTotal//1000) for gpu in gpus if (gpu.load < 0.5 and gpu.memoryUtil < 0.5)]
            names = [gpu.name for gpu in gpus if (gpu.load < 0.5 and gpu.memoryUtil < 0.5)]
            sorted_idx = np.lexsort((deviceID_costs, memory_size_costs))

            self.opt.gpu_ids = [deviceIDs[sorted_idx[0]]]
            print('### selected GPU PCI_ID: %d, Name: %s ###' % (self.opt.gpu_ids[0], names[sorted_idx[0]]))
        else:
            # split into integer list, manual or multi-gpu
            self.opt.gpu_ids = list(map(int, self.opt.gpu_ids.split(',')))

        self.opt.device = torch.device("cuda:%d" % self.opt.gpu_ids[0] if (torch.cuda.is_available() and len(self.opt.gpu_ids) >= 1) else "cpu")

        # set unique display_id
        self.opt.display_id = int(self.opt.display_id + 100 * self.opt.gpu_ids[0])

        # ensure rotation equivariant group is properly configured
        assert '2d' == self.opt.rot_equivariant_mode or '3d' == self.opt.rot_equivariant_mode
        if '3d' == self.opt.rot_equivariant_mode:
            assert self.opt.rot_equivariant_no == 1 or self.opt.rot_equivariant_no == 4 or self.opt.rot_equivariant_no == 12 or self.opt.rot_equivariant_no == 24

        # assure that 3d equivariant with 3d augmentation
        if '3d' == self.opt.rot_equivariant_mode:
            self.opt.rot_3d = True
            self.opt.rot_horizontal = False
            assert self.opt.rot_3d
            assert self.opt.rot_horizontal == False
        # assure that 2d equivariant with 2d augmentation
        if '2d' == self.opt.rot_equivariant_mode:
            self.opt.rot_3d = False
            self.opt.rot_horizontal = True
            assert self.opt.rot_3d == False
            assert self.opt.rot_horizontal
        # === processing options === end ===

        args = vars(self.opt)

        print('------------ Options -------------')
        for k, v in sorted(args.items()):
            print('%s: %s' % (str(k), str(v)))
        print('-------------- End ----------------')

        # save to the disk
        expr_dir =  os.path.join(self.opt.checkpoints_dir, self.opt.name)
        util.mkdirs(expr_dir)
        file_name = os.path.join(expr_dir, 'opt.txt')
        with open(file_name, 'wt') as opt_file:
            opt_file.write('------------ Options -------------\n')
            for k, v in sorted(args.items()):
                opt_file.write('%s: %s\n' % (str(k), str(v)))
            opt_file.write('-------------- End ----------------\n')
        return self.opt