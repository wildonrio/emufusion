"""Learned phase-centred frame interpolation, sized for GLES3 fragment passes.

Our own network and weights. Its structure follows the REA study of LSFG 3.1
(shapes and data flow only; none of its code, shaders or weights are used):

Per real frame (phase-independent):
  * a 2x2-mean image pyramid M_k of the frame;
  * ONE encoder shared by every level: 3x3 convs 3->8 (stride 2), 8->8,
    8->16 (stride 2), 16->16, giving 16 feature channels Q_k at a quarter of
    M_k. Every hidden activation is clip(x, 0, 1) quantised to 1/255, which is
    exactly what storing to an RGBA8 render target does.

Per generated phase t, coarse to fine over the levels:
  * head 1 (every level): warp A features to x + 2t*f and B features to
    x + 2(1-t)*b around the upsampled coarser field (half-interval vectors in
    Q_k texels), correlate the A vector with B's at the nine integer offsets
    {-1,0,1}^2 (plain 16-channel dot products, per-offset affine, clip), then
    3x3 convs 9->16->16->16->2 give ONE motion increment d: f = up(f) + d,
    b = up(b) - d;
  * at the three finest levels, head 2 (same shapes, own weights) refines the
    same coarser field from the same normalised correlation into a second
    hypothesis F2,
    and a visibility branch turns both coarser fields into endpoint matches,
    scores them with four 3x3 correlation volumes (36 channels), and through
    1x1 36->8, 3x3 8->8 x3, 3x3 8->4 accumulates four logits W over levels;
  * the output pixel is a softmax over the four candidates (A and B under F1
    and F2, each logit read at its own source position) times the linear phase
    weights, normalised.

Padding is edge-replicate (GL_CLAMP_TO_EDGE); sampling is bilinear at texel
centres (GL_LINEAR, align_corners=False).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

FEATURES = 16
DELTA_LEVELS = 3
OFFSETS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def conv(cin, cout, stride=1, kernel=3):
    return nn.Conv2d(cin, cout, kernel, stride, kernel // 2, padding_mode='replicate')


def store8(x):
    """clip(x, 0, 1) quantised to 1/255 (an RGBA8 render target).

    The forward value is exactly what the device stores. The backward pass is
    leaky (slope 0.05 outside [0, 1]): with a hard clip a layer whose outputs
    all leave [0, 1] gets no gradient and never recovers (the heads' last
    hidden layer died this way and the network collapsed to a cross-fade).
    """
    y = x.clamp(0, 1)
    soft = y + 0.05 * (x - y)
    return soft + (torch.round(y * 255) / 255 - soft).detach()


def sample(image, field):
    """image (N,C,H,W) sampled at x + field (field in pixels of image, (N,2,H',W')).

    Bilinear at texel centres with edge clamping: GL_LINEAR + CLAMP_TO_EDGE.
    Written with gather because MPS lacks grid_sample's border mode and backward.
    """
    n, c, ih, iw = image.shape
    h, w = field.shape[-2:]
    xs = (torch.arange(w, device=field.device, dtype=field.dtype) + 0.5) * (iw / w) - 0.5
    ys = (torch.arange(h, device=field.device, dtype=field.dtype) + 0.5) * (ih / h) - 0.5
    px = (xs.view(1, 1, w) + field[:, 0]).clamp(0, iw - 1)
    py = (ys.view(1, h, 1) + field[:, 1]).clamp(0, ih - 1)
    x0 = px.detach().floor().clamp(max=iw - 1)
    y0 = py.detach().floor().clamp(max=ih - 1)
    fx = (px - x0).unsqueeze(1)
    fy = (py - y0).unsqueeze(1)
    x0 = x0.long(); y0 = y0.long()
    x1 = (x0 + 1).clamp(max=iw - 1); y1 = (y0 + 1).clamp(max=ih - 1)
    flat = image.reshape(n, c, ih * iw)

    def take(yy, xx):
        index = (yy * iw + xx).view(n, 1, h * w).expand(n, c, h * w)
        return flat.gather(2, index).view(n, c, h, w)

    top = take(y0, x0) * (1 - fx) + take(y0, x1) * fx
    bottom = take(y1, x0) * (1 - fx) + take(y1, x1) * fx
    return top * (1 - fy) + bottom * fy


def upsample(x, size):
    return F.interpolate(x, size=size, mode='bilinear', align_corners=False)


def upsample_field(field, size):
    """Bilinear upsample of a vector field, rescaling its texel units."""
    h, w = field.shape[-2:]
    up = upsample(field, size)
    sx, sy = size[1] / w, size[0] / h
    scale = torch.tensor([sx, sy, sx, sy][:field.shape[1]], device=field.device,
                         dtype=field.dtype).view(1, -1, 1, 1)
    return up * scale


def nine_shifts(features):
    """Stack of the nine integer-shifted copies (offset order OFFSETS), edge-replicated.

    Bilinear sampling commutes with an integer shift, so one gather of this
    stack at p gives the nine samples at p + d (shader: textureOffset).
    """
    h, w = features.shape[-2:]
    p = F.pad(features, (1, 1, 1, 1), mode='replicate')
    return torch.cat([p[..., 1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dx, dy in OFFSETS], 1)


def correlate(vector, nine):
    """Matching score of one feature vector (N,C,h,w) against nine candidates (N,9C,h,w).

    Negative squared feature distance. (A raw dot product of [0, 1] features
    rewards bright candidates rather than matching ones, so an untrained
    network never finds the motion in it; the distance is a matching cost
    even for random features and costs the same on the GPU.)
    """
    n, c, h, w = vector.shape
    return -((nine.view(n, 9, c, h, w) - vector.unsqueeze(1)) ** 2).sum(2)


class Encoder(nn.Module):
    def __init__(self, inputs=3, width=8):
        super().__init__()
        self.c0 = conv(inputs, width, 2)
        self.c1 = conv(width, width)
        self.c2 = conv(width, FEATURES, 2)
        self.c3 = conv(FEATURES, FEATURES)

    def forward(self, image):
        x = store8(self.c0(image))
        x = store8(self.c1(x))
        x = store8(self.c2(x))
        return store8(self.c3(x))


class Head(nn.Module):
    """Correlation (9) -> 16 -> 16 -> 16 -> one motion increment (2)."""

    def __init__(self, width=16, affine=True):
        super().__init__()
        self.affine = nn.Conv2d(9, 9, 1, groups=9) if affine else None
        self.c1 = conv(9, width)
        self.c2 = conv(width, width)
        self.c3 = conv(width, width)
        self.c4 = conv(width, 2)
        with torch.no_grad():
            if self.affine is not None:
                self.affine.weight.fill_(1.0 / FEATURES)
                self.affine.bias.zero_()
            # Near-zero increment at init: the head is shared by every level and
            # the field doubles per level, so a constant offset grows ~31x. Not
            # exactly zero: zero weights block all gradient to the layers before.
            self.c4.weight.normal_(0.0, 1e-3)
            self.c4.bias.zero_()

    def correlation(self, raw):
        return store8(self.affine(raw))

    def forward(self, corr):
        x = store8(self.c1(corr))
        x = store8(self.c2(x))
        x = store8(self.c3(x))
        return self.c4(x)


class Visibility(nn.Module):
    """Four endpoint-consistency correlations (36) -> 8 -> 8 x3 -> four logits."""

    def __init__(self, width=8):
        super().__init__()
        self.affine = nn.Conv2d(36, 36, 1, groups=36)
        self.c0 = conv(36, width, kernel=1)
        self.c1 = conv(width, width)
        self.c2 = conv(width, width)
        self.c3 = conv(width, width)
        self.c4 = conv(width, 4)
        with torch.no_grad():
            self.affine.weight.fill_(1.0 / FEATURES)
            self.affine.bias.zero_()
            self.c4.weight.normal_(0.0, 1e-3)
            self.c4.bias.zero_()

    def forward(self, raw):
        x = store8(self.affine(raw))
        x = store8(self.c0(x))
        x = store8(self.c1(x))
        x = store8(self.c2(x))
        x = store8(self.c3(x))
        return self.c4(x)


def endpoint_matches(coarse, size, t):
    """For each texel taken as a pixel of B (resp. A), its match in A (resp. B).

    coarse: (N,4,h',w') coarser-level half-interval vectors (f toward A, b
    toward B) at phase t, in coarse texels; it is read bilinearly at the
    displaced points, as the device reads the coarse texture.
    Returns displacements (N,2,h,w) in texels of `size`: B-pixel -> A match,
    A-pixel -> B match.
    """
    tt = t.view(-1, 1, 1, 1)
    h, w = size
    ch, cw = coarse.shape[-2:]
    scale = torch.tensor([w / cw, h / ch, w / cw, h / ch], device=coarse.device,
                         dtype=coarse.dtype).view(1, 4, 1, 1)
    inverse = (1 / scale[:, :2])

    def at(offset):
        return sample(coarse, offset * inverse) * scale

    here = at(coarse.new_zeros(coarse.shape[0], 2, h, w))
    f, b = here[:, 0:2], here[:, 2:4]
    q = -2 * (1 - tt) * b               # B pixel y sits at y + q at time t
    to_a = q + 2 * tt * at(q)[:, 0:2]
    q2 = -2 * tt * f                    # A pixel z sits at z + q2 at time t
    to_b = q2 + 2 * (1 - tt) * at(q2)[:, 2:4]
    return to_a, to_b


class PhaseNet(nn.Module):
    def __init__(self, levels=5, delta_levels=DELTA_LEVELS, head_width=16):
        super().__init__()
        self.levels = levels
        self.delta_levels = delta_levels
        self.encoder = Encoder()
        self.head1 = Head(head_width)
        self.head2 = Head(head_width, affine=False)
        self.visibility = Visibility()

    def features(self, image):
        """Per-real-frame work: feature pyramid, finest first."""
        out, level = [], image
        for k in range(self.levels):
            out.append(self.encoder(level))
            if k + 1 < self.levels:
                level = F.avg_pool2d(level, 2, ceil_mode=True)
        return out

    def fields(self, feats_a, feats_b, t, collect=None):
        """Per-phase work: F1, F2 (N,4,h,w half-interval vectors in Q_0 texels) and W.

        collect: optional list receiving (F1, F2 or None) after every level
        (coarse to fine), for deep supervision during training.
        """
        tt = t.view(-1, 1, 1, 1)
        f1 = f2 = logits = None
        for k in reversed(range(self.levels)):
            fa, fb = feats_a[k], feats_b[k]
            n, _, h, w = fa.shape
            coarse = fa.new_zeros(n, 4, h, w) if f1 is None else upsample_field(f1, (h, w))
            wa = sample(fa, 2 * tt * coarse[:, 0:2])
            nb = sample(nine_shifts(fb), 2 * (1 - tt) * coarse[:, 2:4])
            raw = correlate(wa, nb)
            corr = self.head1.correlation(raw)
            d1 = self.head1(corr)
            new_f1 = coarse + torch.cat([d1, -d1], 1)
            if k < self.delta_levels:
                # Head 2 reads the same normalised correlation (one pass on the device).
                d2 = self.head2(corr)
                new_f2 = coarse + torch.cat([d2, -d2], 1)
                low1 = f1 if f1 is not None else fa.new_zeros(n, 4, 1, 1)
                low2 = f2 if f2 is not None else low1
                volumes = []
                for low in (low1, low2):
                    to_a, to_b = endpoint_matches(low, (h, w), t)
                    volumes.append(correlate(sample(fa, to_a), nine_shifts(fb)))
                    volumes.append(correlate(sample(fb, to_b), nine_shifts(fa)))
                step = self.visibility(torch.cat(volumes, 1))
                logits = step if logits is None else step + upsample(logits, (h, w))
                f2 = new_f2
            f1 = new_f1
            if collect is not None:
                collect.append((f1, f2 if k < self.delta_levels else None))
        return f1, f2, logits

    def synthesize(self, a, b, t, f1, f2, logits):
        h, w = a.shape[-2:]
        tt = t.view(-1, 1, 1, 1)
        g1, g2 = upsample_field(f1, (h, w)), upsample_field(f2, (h, w))
        lh, lw = logits.shape[-2:]
        to_low = torch.tensor([lw / w, lh / h], device=a.device, dtype=a.dtype).view(1, 2, 1, 1)
        candidates = (
            (a, 2 * tt * g1[:, 0:2], 0, 1 - tt),
            (b, 2 * (1 - tt) * g1[:, 2:4], 1, tt),
            (a, 2 * tt * g2[:, 0:2], 2, 1 - tt),
            (b, 2 * (1 - tt) * g2[:, 2:4], 3, tt),
        )
        colours, scores, phases = [], [], []
        for image, offset, channel, phase in candidates:
            colours.append(sample(image, offset))
            # Logits are read from the low-resolution map at the candidate's
            # source position (GL: one bilinear tap of the Q_0 texture).
            scores.append(sample(logits[:, channel:channel + 1], offset * to_low))
            phases.append(phase.expand_as(scores[-1]))
        soft = torch.softmax(torch.cat(scores, 1), 1)
        weights = soft * torch.cat(phases, 1)
        weights = weights / (weights.sum(1, keepdim=True) + 1e-8)
        out = sum(weights[:, i:i + 1] * colours[i] for i in range(4))
        return out, g1, g2, weights

    def clipped_layers(self):
        """Every conv whose output is stored to RGBA8 (clip activation), in forward order."""
        e, h1, h2, v = self.encoder, self.head1, self.head2, self.visibility
        return [e.c0, e.c1, e.c2, e.c3, h1.affine, h1.c1, h1.c2, h1.c3, h2.c1, h2.c2, h2.c3,
                v.affine, v.c0, v.c1, v.c2, v.c3]

    @torch.no_grad()
    def calibrate(self, a, b, t, mean=0.5, spread=0.2, rounds=2):
        """Data-dependent init: each clipped layer's pre-activation gets per-channel
        mean 0.5 and std 0.2, so training starts inside the linear range of the
        clip (otherwise gradients vanish through the stacked clips)."""
        for layer in self.clipped_layers() * rounds:
            stats = []
            hook = layer.register_forward_hook(lambda m, i, o: stats.append(o.detach()))
            self.forward(a, b, t)
            hook.remove()
            x = torch.cat([o.transpose(0, 1).reshape(o.shape[1], -1) for o in stats], 1)
            mu, sd = x.mean(1), x.std(1).clamp(min=1e-4)
            gain = spread / sd
            layer.weight.mul_(gain.view(-1, *([1] * (layer.weight.dim() - 1))))
            layer.bias.copy_((layer.bias - mu) * gain + mean)

    def forward(self, a, b, t):
        levels = []
        f1, f2, logits = self.fields(self.features(a), self.features(b), t, levels)
        out, g1, g2, weights = self.synthesize(a, b, t, f1, f2, logits)
        return out, {'f1': g1, 'f2': g2, 'weights': weights, 'levels': levels}


def parameter_count(model):
    return sum(p.numel() for p in model.parameters())


def pad_to(x, multiple):
    h, w = x.shape[-2:]
    ph, pw = (-h) % multiple, (-w) % multiple
    if ph or pw:
        x = F.pad(x, (0, pw, 0, ph), mode='replicate')
    return x, h, w


if __name__ == '__main__':
    net = PhaseNet()
    a = torch.rand(2, 3, 160, 160)
    out, aux = net(a, a, torch.tensor([0.5, 0.3]))
    out.mean().backward()
    print(out.shape, parameter_count(net), torch.isfinite(out).all().item())
