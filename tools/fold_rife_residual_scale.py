"""Experimental inference-only algebraic folding; never mutate the pinned checkpoint."""
import copy
import torch


class FoldedResidual(torch.nn.Module):
    def __init__(self,original):
        super().__init__()
        self.conv=copy.deepcopy(original.conv)
        self.relu=copy.deepcopy(original.relu)
        scale=original.beta.detach().reshape(-1)
        if self.conv.out_channels!=scale.numel():raise ValueError('scale geometry mismatch')
        with torch.no_grad():
            self.conv.weight.mul_(scale[:,None,None,None])
            if self.conv.bias is not None:self.conv.bias.mul_(scale)

    def forward(self,x):return self.relu(self.conv(x)+x)


def fold(network):
    result=copy.deepcopy(network);count=0
    for module in list(result.modules()):
        for name,child in list(module.named_children()):
            if type(child).__name__=='ResConv':
                setattr(module,name,FoldedResidual(child));count+=1
    if count!=32:raise ValueError(f'expected pinned 32 residual blocks, got {count}')
    return result,count
