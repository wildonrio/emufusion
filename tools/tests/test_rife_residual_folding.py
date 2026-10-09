import sys
from pathlib import Path
import unittest
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fold_rife_residual_scale import FoldedResidual


class ResidualFoldTest(unittest.TestCase):
    def test_signed_scales_and_bias_preserve_residual_and_original(self):
        torch.manual_seed(91)
        class Block(torch.nn.Module):
            def __init__(self):
                super().__init__();self.conv=torch.nn.Conv2d(3,3,3,padding=1)
                self.beta=torch.nn.Parameter(torch.tensor([-.7,0.,1.3]).reshape(1,3,1,1))
                self.relu=torch.nn.LeakyReLU(.2)
            def forward(self,x):return self.relu(self.conv(x)*self.beta+x)
        original=Block();weights=original.conv.weight.detach().clone()
        folded=FoldedResidual(original)
        x=torch.randn(2,3,17,19)
        torch.testing.assert_close(folded(x),original(x),atol=1e-6,rtol=1e-5)
        torch.testing.assert_close(original.conv.weight,weights,atol=0,rtol=0)
