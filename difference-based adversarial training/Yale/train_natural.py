from __future__ import print_function
import os
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms

#from models.net_mnist import *
from model import *
from trades import trades_loss
import numpy as np
import sys
sys.path.append('../../')
from utils import *

os.environ['CUDA_DEVICE_ORDER']="PCI_BUS_ID"
os.environ['CUDA_VISIBLE_DEVICES']='2' 

parser = argparse.ArgumentParser(description='PyTorch MNIST TRADES Adversarial Training')
parser.add_argument('--batch-size', type=int, default=20, metavar='N',
                    help='input batch size for training (default: 128)')
parser.add_argument('--test-batch-size', type=int, default=100, metavar='N',
                    help='input batch size for testing (default: 128)')
parser.add_argument('--epochs', type=int, default=150, metavar='N',
                    help='number of epochs to train')
parser.add_argument('--lr', type=float, default=0.0001, metavar='LR',
                    help='learning rate')
parser.add_argument('--weight_decay', type=float, default=5e-4, metavar='M',
                    help='weight_decay')
parser.add_argument('--no-cuda', action='store_true', default=False,
                    help='disables CUDA training')
parser.add_argument('--epsilon', default=0.0314,
                    help='perturbation')
parser.add_argument('--num-steps', default=10,
                    help='perturb number of steps')
parser.add_argument('--step-size', default=0.0078,
                    help='perturb step size')
parser.add_argument('--beta', default=1.0,
                    help='regularization, i.e., 1/lambda in TRADES')
parser.add_argument('--seed', type=int, default=1, metavar='S',
                    help='random seed (default: 1)')
parser.add_argument('--log-interval', type=int, default=50, metavar='N',
                    help='how many batches to wait before logging training status')
parser.add_argument('--model-dir', default='./model_natural',
                    help='directory of model for saving checkpoint')
parser.add_argument('--save-freq', '-s', default=5, type=int, metavar='N',
                    help='save frequency')
args = parser.parse_args()

# settings
model_dir = args.model_dir
if not os.path.exists(model_dir):
    os.makedirs(model_dir)
#use_cuda = not args.no_cuda and torch.cuda.is_available()
torch.manual_seed(args.seed)
#device = torch.device("cuda" if use_cuda else "cpu")
kwargs = {'num_workers': 1, 'pin_memory': True}

# setup data loader
def YALEBXF_loader(batch_size=20, test_batch_size=2):
    train_data, train_label, test_data, test_label = YALE_split('../../datasets/yale/YALEBXF.mat') 
    train_data = train_data.transpose((0, 3, 1, 2) )
    test_data = test_data.transpose((0, 3, 1, 2) )
    print(np.amax(train_data), np.amin(test_data), train_data.shape, test_data.shape)
    tensor_x = torch.stack([torch.FloatTensor(i) for i in train_data]) # transform to torch tensors
    tensor_y = torch.stack([torch.LongTensor(np.array(i)) for i in train_label])
    train_dataset = torch.utils.data.TensorDataset(tensor_x,tensor_y)
    
    tensor_x = torch.stack([torch.FloatTensor(i) for i in test_data]) # transform to torch tensors
    tensor_y = torch.stack([torch.LongTensor(np.array(i)) for i in test_label])
    test_dataset = torch.utils.data.TensorDataset(tensor_x,tensor_y)
    
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size,
        shuffle=True, pin_memory=True)
    
    test_loader = torch.utils.data.DataLoader(test_dataset, batch_size=test_batch_size,
        shuffle=False, pin_memory=True)
    return train_loader, test_loader

train_loader, test_loader = YALEBXF_loader(args.batch_size, args.test_batch_size)


def train(args, model, train_loader, optimizer, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.cuda(), target.cuda()
        optimizer.zero_grad()
        loss = F.cross_entropy(model(data), target)
        loss.backward()
        optimizer.step()
        
        # print progress
        if batch_idx % args.log_interval == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss.item()))
    


def eval_train(model, train_loader):
    model.eval()
    train_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in train_loader:
            data, target = data.cuda(), target.cuda()
            output = model(data)
            train_loss += F.cross_entropy(output, target, size_average=False).item()
            pred = output.max(1, keepdim=True)[1]
            correct += pred.eq(target.view_as(pred)).sum().item()
    train_loss /= len(train_loader.dataset)
    print('Training: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)'.format(
        train_loss, correct, len(train_loader.dataset),
        100. * correct / len(train_loader.dataset)))
    training_accuracy = correct / len(train_loader.dataset)
    return train_loss, training_accuracy


def eval_test(model, test_loader):
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.cuda(), target.cuda()
            output = model(data)
            test_loss += F.cross_entropy(output, target, size_average=False).item()
            pred = output.max(1, keepdim=True)[1]
            correct += pred.eq(target.view_as(pred)).sum().item()
    test_loss /= len(test_loader.dataset)
    print('Test: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)'.format(
        test_loss, correct, len(test_loader.dataset),
        100. * correct / len(test_loader.dataset)))
    test_accuracy = correct / len(test_loader.dataset)
    return test_loss, test_accuracy


def adjust_learning_rate(optimizer, epoch):
    """decrease the learning rate"""
    lr = args.lr
    if epoch >= 0.9*args.epochs:
        lr = args.lr * 0.01
    elif epoch >= 0.75*args.epochs:
        lr = args.lr * 0.1
    elif epoch >= 0.5*args.epochs:
        lr = args.lr * 0.5
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def main():
    # init model, Net() can be also used here for training
    model = VGG(width_num=2).cuda()
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    for epoch in range(1, args.epochs + 1):
        # adjust learning rate for SGD
        adjust_learning_rate(optimizer, epoch)

        # adversarial training
        train(args, model, train_loader, optimizer, epoch)

        # evaluation on natural examples
        print('================================================================')
        eval_train(model, train_loader)
        eval_test(model, test_loader)
        print('================================================================')

        # save checkpoint
        if epoch % args.save_freq == 0:
            torch.save(model.state_dict(),
                       os.path.join(model_dir, 'YALEB_vgg_natural-epoch{}.pt'.format(epoch)))
            torch.save(optimizer.state_dict(),
                       os.path.join(model_dir, 'opt-nn-checkpoint_epoch{}.tar'.format(epoch)))


if __name__ == '__main__':
    main()