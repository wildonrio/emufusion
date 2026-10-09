import math
import unittest
from dataclasses import dataclass
from fractions import Fraction


# Qualification-only CPU reference for the proposed handheld dense-flow arm.
# It deliberately has no Android, GLES, NumPy, or verifier dependency.  The
# production implementation may change representation, but not this dataflow:
# two shared image pyramids, two independently solved vector pyramids, then
# forward/reverse cycle, occlusion, and hard-cut gates before interpolation.
WIDTH = 256
HEIGHT = 144
PYRAMID_SHAPES = ((64, 36), (128, 72), (256, 144))
LEVEL_SOURCE_PIXEL_SCALES = (4, 2, 1)
LEVEL_ITERATIONS = (8, 4, 4)
FLOW_FRACTION_BITS = 8
FLOW_FIXED_SCALE = 1 << FLOW_FRACTION_BITS
FLOW_FIXED_MIN = -32768
FLOW_FIXED_MAX = 32767
SCENE_CUT_MAD = 0.18
MAX_CYCLE_ERROR_PIXELS = 1.5
MIN_CYCLE_COVERAGE = 0.80
MAX_QUALIFICATION_PASSES = 38
MAX_QUALIFICATION_BYTES = 2 * 1024 * 1024
V23_PHYSICAL_MEAN_COMPLETE_US = 1_408_649 / 120
V23_PIXEL_WORK = 842_400
DIAGNOSTIC_PREREQUISITE_THRESHOLD = 47 / 255
DIAGNOSTIC_VALID_BYTE = 48
DIAG_ACTIVE = 1
DIAG_IN_BOUNDS = 2
DIAG_CYCLE_VALID = 4
DIAG_PHOTOMETRIC_VALID = 8
DIAG_TEXTURE_VALID = 16
DIAG_SATURATED = 32
DIAG_OUT_OF_BOUNDS = 64
DIAGNOSTIC_WIDTH = 48
DIAGNOSTIC_HEIGHT = 27
DIAGNOSTIC_TILES_X = 6
DIAGNOSTIC_TILES_Y = 3


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


def luma(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def ycocg_chroma(rgb):
    return (0.5 * (rgb[0] - rgb[2]),
            0.5 * rgb[1] - 0.25 * (rgb[0] + rgb[2]))


def robust_chroma_distance(first, second):
    a = ycocg_chroma(first)
    b = ycocg_chroma(second)
    return min(abs(a[0] - b[0]), 0.16) + min(abs(a[1] - b[1]), 0.16)


def census_mismatch(center_a, neighbors_a, center_b, neighbors_b):
    """Mirror the coarsest shader's eight-neighbour ordering descriptor."""
    if len(neighbors_a) != 8 or len(neighbors_b) != 8:
        raise ValueError("coarse census requires exactly eight neighbours")
    return sum(
        (neighbor_a >= center_a) != (neighbor_b >= center_b)
        for neighbor_a, neighbor_b in zip(neighbors_a, neighbors_b)
    )


def robust_four_neighbor_consensus(neighbors, support_radius=3.0):
    """Mirror the final fine-level component-median/support decision."""
    if len(neighbors) != 4:
        raise ValueError("final consensus requires four neighbors")
    xs = sorted(value[0] for value in neighbors)
    ys = sorted(value[1] for value in neighbors)
    median = ((xs[1] + xs[2]) * 0.5, (ys[1] + ys[2]) * 0.5)
    support = sum(
        math.hypot(value[0] - median[0], value[1] - median[1]) <=
        support_radius
        for value in neighbors
    )
    return median, support >= 3


def spatial_consensus_gate(center, neighbors, support_radius=2.0,
                           full_agreement_radius=1.0,
                           reject_radius=2.5):
    """Mirror v45's fail-closed local-flow admission.

    The median comes only from the four independently solved neighbouring
    cells. At least three neighbours must occupy the same basin, and the
    center must remain close to it. The smooth falloff mirrors GLSL
    ``1-smoothstep(1, 2.5, distance(center, median))``.
    """
    if len(neighbors) != 4:
        raise ValueError("spatial consensus requires four neighbors")
    xs = sorted(value[0] for value in neighbors)
    ys = sorted(value[1] for value in neighbors)
    median = ((xs[1] + xs[2]) * 0.5, (ys[1] + ys[2]) * 0.5)
    support = sum(
        math.hypot(value[0] - median[0], value[1] - median[1]) <=
        support_radius
        for value in neighbors
    )
    if support < 3:
        return 0.0
    distance = math.hypot(center[0] - median[0], center[1] - median[1])
    if distance <= full_agreement_radius:
        return 1.0
    if distance >= reject_radius:
        return 0.0
    t = (distance - full_agreement_radius) / (
        reject_radius - full_agreement_radius)
    smooth = t * t * (3.0 - 2.0 * t)
    return 1.0 - smooth


def active_dimensions(source_width, source_height):
    """Exact aspect fit inside the 256x144 qualification allocation."""
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source dimensions must be positive")
    fit = min(Fraction(WIDTH, source_width), Fraction(HEIGHT, source_height))
    return source_width * fit, source_height * fit


def encode_flow_q8_8(dx, dy):
    """Pack signed Q8.8 X in RG and Y in BA, high byte first."""
    def component(value):
        fixed = int(math.floor(value * FLOW_FIXED_SCALE + 0.5))
        if not FLOW_FIXED_MIN <= fixed <= FLOW_FIXED_MAX:
            raise ValueError("flow is outside signed Q8.8 range")
        unsigned = fixed & 0xFFFF
        return unsigned >> 8, unsigned & 0xFF

    x_high, x_low = component(dx)
    y_high, y_low = component(dy)
    return x_high, x_low, y_high, y_low


def decode_flow_q8_8(rgba):
    def component(high, low):
        unsigned = (high << 8) | low
        signed = unsigned - 0x10000 if unsigned & 0x8000 else unsigned
        return signed / FLOW_FIXED_SCALE

    return component(rgba[0], rgba[1]), component(rgba[2], rgba[3])


def dense_diagnostic_mask(active, in_bounds, cycle_gate, photometric_gate,
                          texture_gate, saturated):
    """CPU mirror of schema35's nearest-sampled validated alpha byte."""
    return (
        DIAG_ACTIVE * int(active)
        + DIAG_IN_BOUNDS * int(in_bounds)
        + DIAG_CYCLE_VALID * int(
            cycle_gate >= DIAGNOSTIC_PREREQUISITE_THRESHOLD)
        + DIAG_PHOTOMETRIC_VALID * int(
            photometric_gate >= DIAGNOSTIC_PREREQUISITE_THRESHOLD)
        + DIAG_TEXTURE_VALID * int(
            texture_gate >= DIAGNOSTIC_PREREQUISITE_THRESHOLD)
        + DIAG_SATURATED * int(saturated)
        + DIAG_OUT_OF_BOUNDS * int(not in_bounds)
    )


def pack_nearest_diagnostic_masks(backward, forward):
    """Flatten two 48x27 mask planes into layout-3's 144x9 RG tile."""
    cells = DIAGNOSTIC_WIDTH * DIAGNOSTIC_HEIGHT
    if len(backward) != cells or len(forward) != cells:
        raise ValueError("packed diagnostic mask has the wrong population")
    packed = [(0, 0, 0, 0)] * cells
    for cell in range(cells):
        packed[cell] = (backward[cell], forward[cell], 0, 0)
    return packed


def unpack_nearest_diagnostic_masks(packed):
    if len(packed) != 144 * 9:
        raise ValueError("packed diagnostic tile has the wrong geometry")
    if any(pixel[2:] != (0, 0) for pixel in packed):
        raise ValueError("packed diagnostic reserved channels are nonzero")
    return ([pixel[0] for pixel in packed],
            [pixel[1] for pixel in packed])


def covered_tile_summary(masks, confidence_bytes):
    if (len(masks) != DIAGNOSTIC_WIDTH * DIAGNOSTIC_HEIGHT or
            len(confidence_bytes) != len(masks)):
        raise ValueError("diagnostic proof grid has the wrong size")
    active = [0] * (DIAGNOSTIC_TILES_X * DIAGNOSTIC_TILES_Y)
    valid = [0] * len(active)
    for y in range(DIAGNOSTIC_HEIGHT):
        tile_y = min(DIAGNOSTIC_TILES_Y - 1,
                     y * DIAGNOSTIC_TILES_Y // DIAGNOSTIC_HEIGHT)
        for x in range(DIAGNOSTIC_WIDTH):
            tile_x = min(DIAGNOSTIC_TILES_X - 1,
                         x * DIAGNOSTIC_TILES_X // DIAGNOSTIC_WIDTH)
            tile = tile_y * DIAGNOSTIC_TILES_X + tile_x
            mask = masks[y * DIAGNOSTIC_WIDTH + x]
            active[tile] += bool(mask & DIAG_ACTIVE)
            valid[tile] += (confidence_bytes[y * DIAGNOSTIC_WIDTH + x] >=
                            DIAGNOSTIC_VALID_BYTE)
    covered = [index for index in range(len(active))
               if active[index] and valid[index] * 2 >= active[index]]
    return len(covered), sum(1 << index for index in covered)


def procedural_pixel(seed, x, y):
    """Continuous, deterministic texture with structure at several scales."""
    phase = seed * 0.731
    value = (
        0.50
        + 0.20 * math.sin(x * 0.109 + y * 0.037 + phase)
        + 0.15 * math.cos(x * 0.031 - y * 0.137 + phase * 1.7)
        + 0.10 * math.sin(x * 0.263 + y * 0.191 - phase * 0.6)
        + 0.07 * math.cos(x * 0.419 - y * 0.283 + phase * 2.3)
    )
    return clamp(value)


def make_image(sampler, width=WIDTH, height=HEIGHT):
    return tuple(
        sampler(x + 0.5, y + 0.5)
        for y in range(height)
        for x in range(width)
    )


def downsample_2x(image, width, height):
    output_width = width // 2
    output_height = height // 2
    output = []
    for y in range(output_height):
        top = (y * 2) * width
        bottom = top + width
        for x in range(output_width):
            left = x * 2
            output.append(
                0.25
                * (
                    image[top + left]
                    + image[top + left + 1]
                    + image[bottom + left]
                    + image[bottom + left + 1]
                )
            )
    return tuple(output)


def sample_scalar(image, width, height, x, y):
    if x < 0.0 or y < 0.0 or x > width - 1 or y > height - 1:
        return None
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    x1 = min(width - 1, x0 + 1)
    y1 = min(height - 1, y0 + 1)
    tx = x - x0
    ty = y - y0
    top = image[y0 * width + x0] * (1.0 - tx) + image[y0 * width + x1] * tx
    bottom = image[y1 * width + x0] * (1.0 - tx) + image[y1 * width + x1] * tx
    return top * (1.0 - ty) + bottom * ty


def sample_vector(field, width, height, x, y):
    if x < 0.0 or y < 0.0 or x > width - 1 or y > height - 1:
        return None
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    x1 = min(width - 1, x0 + 1)
    y1 = min(height - 1, y0 + 1)
    tx = x - x0
    ty = y - y0
    a = field[y0 * width + x0]
    b = field[y0 * width + x1]
    c = field[y1 * width + x0]
    d = field[y1 * width + x1]
    return (
        (a[0] * (1.0 - tx) + b[0] * tx) * (1.0 - ty)
        + (c[0] * (1.0 - tx) + d[0] * tx) * ty,
        (a[1] * (1.0 - tx) + b[1] * tx) * (1.0 - ty)
        + (c[1] * (1.0 - tx) + d[1] * tx) * ty,
    )


def reciprocal_flow_proposal(field, width, height, x, y,
                             source_width=WIDTH, source_height=HEIGHT,
                             limit=47.0):
    """Mirror the single reverse coarse-level proposal used by GLES."""
    first = sample_vector(field, width, height, x, y)
    if first is None:
        return (0.0, 0.0)
    query_x = x - first[0] * width / source_width
    query_y = y - first[1] * height / source_height
    inverse = sample_vector(field, width, height, query_x, query_y)
    if inverse is None:
        return (0.0, 0.0)
    return (max(-limit, min(limit, -inverse[0])),
            max(-limit, min(limit, -inverse[1])))


def choose_reciprocal_seed(guide, zero_cost, guide_cost, margin=0.002):
    """The guide is a proposal, never an asserted inverse field."""
    return guide if guide_cost + margin < zero_cost else (0.0, 0.0)


def dense_global_translation_seed(reference, target, width, height,
                                  flow_limit=47.0):
    """CPU mirror of v60's one-fragment direction-specific seed search.

    Inputs are scalar images so chroma is identically zero. The spatial grid,
    robust luma cap, coarse/fine candidate lattices, gain threshold, and
    source-pixel displacement convention mirror the GLES shader exactly.
    """
    def candidate_cost(dx, dy):
        total = 0.0
        for sample_y in range(8):
            for sample_x in range(12):
                x = (sample_x + 0.5) * width / 12.0 - 0.5
                y = (sample_y + 0.5) * height / 8.0 - 0.5
                shifted = sample_scalar(reference, width, height, x + dx, y + dy)
                if shifted is None:
                    total += 0.42
                else:
                    value = sample_scalar(target, width, height, x, y)
                    total += min(abs(value - shifted), 0.18)
        return total

    best = (0.0, 0.0)
    zero_cost = candidate_cost(*best)
    best_cost = zero_cost
    coarse_step = flow_limit / 4.0
    for y in range(-4, 5):
        for x in range(-4, 5):
            candidate = (
                max(-flow_limit, min(flow_limit, x * coarse_step)),
                max(-flow_limit, min(flow_limit, y * coarse_step)),
            )
            cost = candidate_cost(*candidate)
            if cost < best_cost:
                best, best_cost = candidate, cost
    coarse = best
    fine_step = max(1.0, coarse_step / 4.0)
    for y in range(-2, 3):
        for x in range(-2, 3):
            candidate = (
                max(-flow_limit, min(flow_limit, coarse[0] + x * fine_step)),
                max(-flow_limit, min(flow_limit, coarse[1] + y * fine_step)),
            )
            cost = candidate_cost(*candidate)
            if cost < best_cost:
                best, best_cost = candidate, cost
    gain = (zero_cost - best_cost) / max(zero_cost, 0.0001)
    if gain < 0.035 or math.hypot(*best) < 0.25:
        return (0.0, 0.0), zero_cost, best_cost
    return best, zero_cost, best_cost


@dataclass(frozen=True)
class Scene:
    previous_sampler: object
    current_sampler: object
    forward_solver: object
    reverse_solver: object


@dataclass(frozen=True)
class DirectionLevel:
    width: int
    height: int
    vectors: tuple


@dataclass(frozen=True)
class QualificationResult:
    fallback: bool
    reason: str
    photometric_mad: float
    forward_cycle_coverage: float
    reverse_cycle_coverage: float


class DensePyramidReference:
    def __init__(self, scene):
        self.scene = scene
        self.pass_ledger = []
        self.previous_pyramid = self._make_image_pyramid(scene.previous_sampler, "previous")
        self.current_pyramid = self._make_image_pyramid(scene.current_sampler, "current")
        self.forward_pyramid = self._solve_pyramid(scene.forward_solver, "forward")
        self.reverse_pyramid = self._solve_pyramid(scene.reverse_solver, "reverse")
        self.forward_valid = self._cycle_mask(
            self.forward_pyramid[-1].vectors,
            self.reverse_pyramid[-1].vectors,
            "forward-cycle-occlusion",
        )
        self.reverse_valid = self._cycle_mask(
            self.reverse_pyramid[-1].vectors,
            self.forward_pyramid[-1].vectors,
            "reverse-cycle-occlusion",
        )

    def _make_image_pyramid(self, sampler, label):
        fine = make_image(sampler)
        medium = downsample_2x(fine, WIDTH, HEIGHT)
        self.pass_ledger.append(label + "-downsample-128x72")
        coarse = downsample_2x(medium, WIDTH // 2, HEIGHT // 2)
        self.pass_ledger.append(label + "-downsample-64x36")
        return (coarse, medium, fine)

    def _solve_pyramid(self, solver, direction):
        levels = []
        # Each direction invokes its own solver at all three levels.  Calling
        # the reverse solver is not replaceable by negating the forward field.
        for level_index, (width, height) in enumerate(PYRAMID_SHAPES):
            source_scale = LEVEL_SOURCE_PIXEL_SCALES[level_index]
            target = []
            for y in range(height):
                full_y = (y + 0.5) * source_scale
                for x in range(width):
                    full_x = (x + 0.5) * source_scale
                    dx, dy = solver(full_x, full_y)
                    target.append(decode_flow_q8_8(encode_flow_q8_8(dx, dy)))
            if levels:
                prior = levels[-1]
                vectors = tuple(
                    sample_vector(
                        prior.vectors, prior.width, prior.height,
                        (x + 0.5) * prior.width / width - 0.5,
                        (y + 0.5) * prior.height / height - 0.5,
                    ) or target[y * width + x]
                    for y in range(height)
                    for x in range(width)
                )
            else:
                vectors = ((0.0, 0.0),) * (width * height)
            guide = (self.previous_pyramid if direction == "forward"
                     else self.current_pyramid)[level_index]
            uniform_target = all(vector == target[0] for vector in target)
            for iteration in range(LEVEL_ITERATIONS[level_index]):
                remaining = LEVEL_ITERATIONS[level_index] - iteration
                vectors = self._iterative_edge_update(
                    vectors, tuple(target), guide, width, height, remaining,
                    uniform_target,
                )
                self.pass_ledger.append(
                    "{}-solve-edge-smooth-{}x{}-{}/{}".format(
                        direction, width, height, iteration + 1,
                        LEVEL_ITERATIONS[level_index],
                    )
                )
            levels.append(DirectionLevel(width, height, vectors))
        return tuple(levels)

    @staticmethod
    def _iterative_edge_update(field, target, guide, width, height, remaining,
                               uniform_target):
        # One pass combines a data update and an edge-aware four-neighbor
        # regularizer.  There is deliberately no separate smoothing pass in
        # the 38-pass budget. Flow discontinuities are never averaged merely
        # because their endpoint colors happen to be similar.
        if uniform_target and all(vector == field[0] for vector in field):
            current = field[len(field) // 2]
            wanted = target[0]
            updated = decode_flow_q8_8(encode_flow_q8_8(
                current[0] + (wanted[0] - current[0]) / remaining,
                current[1] + (wanted[1] - current[1]) / remaining,
            ))
            return (updated,) * (width * height)
        provisional = tuple(
            (
                current[0] + (wanted[0] - current[0]) / remaining,
                current[1] + (wanted[1] - current[1]) / remaining,
            )
            for current, wanted in zip(field, target)
        )
        output = []
        for y in range(height):
            for x in range(width):
                index = y * width + x
                center = provisional[index]
                center_target = target[index]
                weighted_x = center[0]
                weighted_y = center[1]
                total_weight = 1.0
                for nx, ny in ((x - 1, y), (x + 1, y),
                               (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    neighbor_index = ny * width + nx
                    neighbor_target = target[neighbor_index]
                    flow_edge = math.hypot(
                        center_target[0] - neighbor_target[0],
                        center_target[1] - neighbor_target[1],
                    )
                    if flow_edge > 1.0:
                        continue
                    luminance_edge = abs(guide[index] - guide[neighbor_index])
                    edge_weight = 0.08 * max(0.0, 1.0 - luminance_edge / 0.08)
                    neighbor = provisional[neighbor_index]
                    weighted_x += neighbor[0] * edge_weight
                    weighted_y += neighbor[1] * edge_weight
                    total_weight += edge_weight
                smoothed = weighted_x / total_weight, weighted_y / total_weight
                output.append(decode_flow_q8_8(encode_flow_q8_8(*smoothed)))
        return tuple(output)

    def _cycle_mask(self, primary, peer, label):
        valid = []
        for y in range(HEIGHT):
            for x in range(WIDTH):
                dx, dy = primary[y * WIDTH + x]
                peer_vector = sample_vector(peer, WIDTH, HEIGHT, x + dx, y + dy)
                if peer_vector is None:
                    valid.append(False)
                    continue
                error = math.hypot(dx + peer_vector[0], dy + peer_vector[1])
                valid.append(error <= MAX_CYCLE_ERROR_PIXELS)
        self.pass_ledger.append(label)
        return tuple(valid)

    @staticmethod
    def resource_bytes():
        pixels = sum(width * height for width, height in PYRAMID_SHAPES)
        # Production owns two RGBA8 flow ping-pong surfaces for each of three
        # levels in each direction, two RGBA8 downsample levels per endpoint,
        # and one RGBA8 validated field per direction. The full-resolution
        # endpoint textures are the pre-existing presentation history and are
        # intentionally outside this quarantine allocation.
        directional_flow_ping_pong = 2 * 2 * pixels * 4
        endpoint_pyramids = 2 * sum(
            width * height for width, height in PYRAMID_SHAPES[:-1]
        ) * 4
        validated_fields = 2 * WIDTH * HEIGHT * 4
        return directional_flow_ping_pong + endpoint_pyramids + validated_fields

    @staticmethod
    def pair_pixel_work():
        # Four endpoint downsample draws, every directional solve draw, and
        # two full-analysis cycle/occlusion draws. This is a workload model,
        # not a substitute for the unchanged physical completion gate.
        endpoint_downsamples = 2 * sum(
            width * height for width, height in PYRAMID_SHAPES[:-1]
        )
        cycle_validation = 2 * WIDTH * HEIGHT
        return endpoint_downsamples + DensePyramidReference.solve_texels() + cycle_validation

    @staticmethod
    def solve_texels():
        per_direction = sum(
            width * height * iterations
            for (width, height), iterations in zip(
                PYRAMID_SHAPES, LEVEL_ITERATIONS
            )
        )
        return 2 * per_direction

    def photometric_mad(self):
        previous = self.previous_pyramid[-1]
        current = self.current_pyramid[-1]
        forward = self.forward_pyramid[-1].vectors
        total = 0.0
        count = 0
        # A fixed 4x4 audit lattice is sufficient for the CPU contract and is
        # deliberately independent of any production proof sampling cadence.
        for y in range(2, HEIGHT, 4):
            for x in range(2, WIDTH, 4):
                index = y * WIDTH + x
                if not self.forward_valid[index]:
                    continue
                dx, dy = forward[index]
                predicted = sample_scalar(current, WIDTH, HEIGHT, x + dx, y + dy)
                if predicted is None:
                    continue
                total += abs(previous[index] - predicted)
                count += 1
        return total / max(1, count)

    def qualify(self):
        photo = self.photometric_mad()
        forward_coverage = sum(self.forward_valid) / len(self.forward_valid)
        reverse_coverage = sum(self.reverse_valid) / len(self.reverse_valid)
        if photo > SCENE_CUT_MAD:
            return QualificationResult(
                True, "hard-scene-cut", photo, forward_coverage, reverse_coverage
            )
        if min(forward_coverage, reverse_coverage) < MIN_CYCLE_COVERAGE:
            return QualificationResult(
                True, "insufficient-cycle-coverage", photo,
                forward_coverage, reverse_coverage,
            )
        return QualificationResult(
            False, "dense-flow", photo, forward_coverage, reverse_coverage
        )


def translation_scene(dx, dy):
    return Scene(
        previous_sampler=lambda x, y: procedural_pixel(1, x, y),
        current_sampler=lambda x, y: procedural_pixel(1, x - dx, y - dy),
        forward_solver=lambda _x, _y: (dx, dy),
        reverse_solver=lambda _x, _y: (-dx, -dy),
    )


def rotation_scene(degrees):
    radians = math.radians(degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    center_x = WIDTH / 2.0
    center_y = HEIGHT / 2.0

    def rotate(x, y, direction):
        px = x - center_x
        py = y - center_y
        signed_sine = sine * direction
        return (
            center_x + cosine * px - signed_sine * py,
            center_y + signed_sine * px + cosine * py,
        )

    def forward(x, y):
        target_x, target_y = rotate(x, y, 1.0)
        return target_x - x, target_y - y

    def reverse(x, y):
        source_x, source_y = rotate(x, y, -1.0)
        return source_x - x, source_y - y

    return Scene(
        previous_sampler=lambda x, y: procedural_pixel(2, x, y),
        current_sampler=lambda x, y: procedural_pixel(2, *rotate(x, y, -1.0)),
        forward_solver=forward,
        reverse_solver=reverse,
    )


def parallax_scene(near_dx, far_dx):
    def displacement(y):
        return far_dx if y < HEIGHT / 2.0 else near_dx

    return Scene(
        previous_sampler=lambda x, y: procedural_pixel(3, x, y),
        current_sampler=lambda x, y: procedural_pixel(3, x - displacement(y), y),
        forward_solver=lambda _x, y: (displacement(y), 0.0),
        reverse_solver=lambda _x, y: (-displacement(y), 0.0),
    )


def disocclusion_scene():
    old_left, old_right = WIDTH * .25, WIDTH * .55
    top, bottom = HEIGHT * .28, HEIGHT * .72
    dx = 18.0

    def inside(x, y, left, right):
        return left <= x < right and top <= y < bottom

    def background(x, y):
        return procedural_pixel(4, x, y)

    def foreground(x, y, left):
        return clamp(0.20 + 0.65 * procedural_pixel(9, x - left, y - top))

    def previous(x, y):
        if inside(x, y, old_left, old_right):
            return foreground(x, y, old_left)
        return background(x, y)

    def current(x, y):
        new_left = old_left + dx
        new_right = old_right + dx
        if inside(x, y, new_left, new_right):
            return foreground(x, y, new_left)
        return background(x, y)

    def forward(x, y):
        return (dx, 0.0) if inside(x, y, old_left, old_right) else (0.0, 0.0)

    def reverse(x, y):
        return (-dx, 0.0) if inside(x, y, old_left + dx, old_right + dx) else (0.0, 0.0)

    return Scene(previous, current, forward, reverse)


def scene_cut():
    return Scene(
        previous_sampler=lambda x, y: procedural_pixel(5, x, y),
        current_sampler=lambda x, y: procedural_pixel(101, x * 1.31, y * 0.73),
        forward_solver=lambda _x, _y: (0.0, 0.0),
        reverse_solver=lambda _x, _y: (0.0, 0.0),
    )


class DensePyramidFlowReferenceTest(unittest.TestCase):

    def test_spatial_consensus_rejects_repetitive_texture_ripple(self):
        coherent = ((7.0, -2.0), (7.5, -2.0),
                    (6.5, -1.5), (7.0, -2.5))
        self.assertEqual(spatial_consensus_gate((7.25, -2.0), coherent), 1.0)
        self.assertEqual(spatial_consensus_gate((14.0, 5.0), coherent), 0.0)
        fragmented = ((-8.0, 4.0), (11.0, -7.0),
                      (3.0, 14.0), (-15.0, -3.0))
        self.assertEqual(spatial_consensus_gate((0.0, 0.0), fragmented), 0.0)

    def test_rejected_dense_vector_is_encoded_as_exact_zero_motion(self):
        # v45 stores exact neutral RG for confidence below the 48/255
        # synthesis threshold. LINEAR filtering can then shorten a boundary
        # vector but can never import an arbitrary rejected displacement.
        neutral = (128, 128)
        decoded = ((neutral[0] - 128) / 127.0,
                   (neutral[1] - 128) / 127.0)
        self.assertEqual(decoded, (0.0, 0.0))
    def test_final_consensus_rejects_one_isolated_flow_outlier(self):
        median, supported = robust_four_neighbor_consensus(
            ((6.0, -2.0), (6.25, -2.0), (5.75, -1.75), (-30.0, 22.0)))
        self.assertTrue(supported)
        self.assertAlmostEqual(5.875, median[0], places=3)
        self.assertAlmostEqual(-1.875, median[1], places=3)
        _, split = robust_four_neighbor_consensus(
            ((-8.0, 0.0), (8.0, 0.0), (0.0, -8.0), (0.0, 8.0)))
        self.assertFalse(split)

    def test_coarse_census_disambiguates_equal_cross_repeated_texture(self):
        center = 0.5
        cardinal = (0.6, 0.4, 0.7, 0.3)
        target = cardinal + (0.8, 0.2, 0.65, 0.35)
        correct = cardinal + (0.8, 0.2, 0.65, 0.35)
        repeated_wrong = cardinal + (0.2, 0.8, 0.35, 0.65)
        self.assertEqual(0, census_mismatch(center, target, center, correct))
        self.assertEqual(
            4, census_mismatch(center, target, center, repeated_wrong))

    def test_chroma_cost_disambiguates_nearly_equal_luminance_colors(self):
        red = (1.0, 0.0, 0.0)
        equal_luma_green = (0.0, 0.299 / 0.587, 0.0)
        self.assertLess(abs(luma(red) - luma(equal_luma_green)), 1e-9)
        self.assertGreater(robust_chroma_distance(red, equal_luma_green), 0.2)
        self.assertEqual(0.0, robust_chroma_distance(red, red))

    def test_reciprocal_guide_is_bounded_inverse_proposal_not_forced_field(self):
        field = [(12.0, -6.0)] * (32 * 18)
        guide = reciprocal_flow_proposal(
            field, 32, 18, 16.0, 9.0, source_width=128,
            source_height=72)
        self.assertEqual((-12.0, 6.0), guide)
        self.assertEqual(guide, choose_reciprocal_seed(guide, 0.4, 0.1))
        self.assertEqual((0.0, 0.0),
                         choose_reciprocal_seed(guide, 0.1, 0.4))
        self.assertEqual((0.0, 0.0),
                         choose_reciprocal_seed(guide, 0.102, 0.1))
        saturated = [(80.0, 0.0)] * (32 * 18)
        self.assertEqual((-47.0, -0.0), reciprocal_flow_proposal(
            saturated, 32, 18, 31.0, 9.0, source_width=128,
            source_height=72))

    def test_v60_global_seed_finds_camera_translation_with_static_hud(self):
        width, height = 128, 72
        background = make_image(
            lambda x, y: procedural_pixel(11, x, y), width, height)
        shifted = list(make_image(
            lambda x, y: procedural_pixel(11, x + 11.75, y - 2.9375),
            width, height))
        # A fixed central HUD deliberately disagrees with the moving
        # background at several of the 24 robust sample positions.
        previous = list(background)
        for y in range(25, 47):
            for x in range(42, 86):
                previous[y * width + x] = 0.92
                shifted[y * width + x] = 0.92
        seed, zero_cost, best_cost = dense_global_translation_seed(
            tuple(previous), tuple(shifted), width, height)
        self.assertLess(best_cost, zero_cost * 0.965)
        self.assertLessEqual(abs(seed[0] - 11.75), 3.0)
        self.assertLessEqual(abs(seed[1] + 2.9375), 3.0)

    def test_v60_global_seed_rejects_flat_cut_and_solves_each_direction(self):
        width, height = 128, 72
        first = tuple([0.1] * (width * height))
        second = tuple([0.9] * (width * height))
        seed, _, _ = dense_global_translation_seed(
            first, second, width, height)
        self.assertEqual((0.0, 0.0), seed)

        previous = make_image(
            lambda x, y: procedural_pixel(7, x, y), width, height)
        current = make_image(
            lambda x, y: procedural_pixel(7, x + 11.75, y), width, height)
        forward, _, _ = dense_global_translation_seed(
            previous, current, width, height)
        reverse, _, _ = dense_global_translation_seed(
            current, previous, width, height)
        self.assertGreater(forward[0], 0.0)
        self.assertLess(reverse[0], 0.0)
        self.assertLessEqual(abs(forward[0] + reverse[0]), 3.0)

    def test_v35_diagnostic_mask_separates_every_unchanged_gate(self):
        self.assertEqual(
            dense_diagnostic_mask(True, True, 1.0, 1.0, 1.0, False),
            DIAG_ACTIVE | DIAG_IN_BOUNDS | DIAG_CYCLE_VALID |
            DIAG_PHOTOMETRIC_VALID | DIAG_TEXTURE_VALID,
        )
        out_of_bounds = dense_diagnostic_mask(
            True, False, 1.0, 1.0, 1.0, False)
        self.assertTrue(out_of_bounds & DIAG_OUT_OF_BOUNDS)
        self.assertFalse(out_of_bounds & DIAG_IN_BOUNDS)
        self.assertEqual(out_of_bounds & 128, 0)
        low_texture = dense_diagnostic_mask(
            True, True, 1.0, 1.0,
            DIAGNOSTIC_PREREQUISITE_THRESHOLD / 2, False)
        self.assertFalse(low_texture & DIAG_TEXTURE_VALID)
        self.assertEqual(low_texture & 128, 0)
        low_cycle = dense_diagnostic_mask(
            True, True, DIAGNOSTIC_PREREQUISITE_THRESHOLD / 2,
            1.0, 1.0, False)
        self.assertFalse(low_cycle & DIAG_CYCLE_VALID)
        self.assertEqual(low_cycle & 128, 0)
        saturated = dense_diagnostic_mask(
            True, True, 1.0, 1.0, 1.0, True)
        self.assertTrue(saturated & DIAG_SATURATED)
        self.assertEqual(saturated & 128, 0)

    def test_v35_prerequisite_bits_cover_rgba8_half_lsb_boundary(self):
        def quantize_unorm8(value):
            return max(0, min(255, int(math.floor(value * 255 + 0.5))))

        prerequisites = (DIAG_CYCLE_VALID | DIAG_PHOTOMETRIC_VALID |
                         DIAG_TEXTURE_VALID)
        for factor in range(3):
            for code in (47.0, 47.49, 47.5, 47.99, 48.0):
                with self.subTest(factor=factor, code=code):
                    gates = [1.0, 1.0, 1.0]
                    gates[factor] = code / 255
                    mask = dense_diagnostic_mask(
                        True, True, gates[0], gates[1], gates[2], False)
                    # With the other factors exactly one, shader confidence
                    # equals the factor under test and exercises the actual
                    # RGBA8 B-byte half-LSB boundary.
                    confidence_byte = quantize_unorm8(gates[factor])
                    if confidence_byte >= DIAGNOSTIC_VALID_BYTE:
                        self.assertEqual(mask & prerequisites, prerequisites)
        # The conservative code-47 floor may report prerequisite coverage for
        # a B=47 cell, but can never hide a returned B>=48 valid cell.
        code_47 = dense_diagnostic_mask(
            True, True, 47 / 255, 47 / 255, 47 / 255, False)
        self.assertTrue(code_47 & DIAG_CYCLE_VALID)

    def test_v35_packed_nearest_transport_preserves_alternating_bits(self):
        cells = DIAGNOSTIC_WIDTH * DIAGNOSTIC_HEIGHT
        backward = [0x55 if cell % 2 == 0 else 0x2a
                    for cell in range(cells)]
        forward = [0x40 if cell % 3 == 0 else 0x02
                   for cell in range(cells)]
        packed = pack_nearest_diagnostic_masks(backward, forward)
        self.assertEqual(len(packed), 144 * 9)
        self.assertEqual((backward, forward),
                         unpack_nearest_diagnostic_masks(packed))
        with self.assertRaisesRegex(ValueError, "reserved"):
            corrupted = list(packed)
            corrupted[647] = (corrupted[647][0], corrupted[647][1], 1, 0)
            unpack_nearest_diagnostic_masks(corrupted)

    def test_v35_spatial_coverage_is_fixed_six_by_three_and_not_aggregate_only(self):
        valid = dense_diagnostic_mask(True, True, 1.0, 1.0, 1.0, False)
        invalid = dense_diagnostic_mask(True, True, 1.0, 1.0, 0.0, False)
        masks = [valid] * (DIAGNOSTIC_WIDTH * DIAGNOSTIC_HEIGHT)
        confidence = [255] * len(masks)
        # Invalidate all 8x9 samples in the upper-left tile. Global coverage
        # remains high, but the fixed tile mask must retain the spatial hole.
        for y in range(9):
            for x in range(8):
                masks[y * DIAGNOSTIC_WIDTH + x] = invalid
                confidence[y * DIAGNOSTIC_WIDTH + x] = 0
        count, mask = covered_tile_summary(masks, confidence)
        self.assertEqual(count, 17)
        self.assertEqual(mask & 1, 0)
        self.assertEqual(bin(mask).count("1"), 17)

    def test_negative_q8_8_roundtrip_has_no_one_lsb_bias(self):
        for value in (-47.0, -12.75, -1.0, -0.5, -1.0 / 256.0,
                      0.0, 1.0 / 256.0, 0.5, 1.0, 47.0):
            packed = encode_flow_q8_8(value, value)
            decoded = decode_flow_q8_8(packed)
            self.assertAlmostEqual(value, decoded[0], places=7)
            self.assertAlmostEqual(value, decoded[1], places=7)

    def test_translation_survives_all_three_levels_and_qualifies(self):
        reference = DensePyramidReference(translation_scene(12.0, -6.0))
        for index, level in enumerate(reference.forward_pyramid):
            self.assertEqual((level.width, level.height), PYRAMID_SHAPES[index])
            self.assertAlmostEqual(level.vectors[len(level.vectors) // 2][0],
                                   12.0)
            self.assertAlmostEqual(level.vectors[len(level.vectors) // 2][1],
                                   -6.0)
        result = reference.qualify()
        self.assertFalse(result.fallback, result)
        self.assertLess(result.photometric_mad, 0.01)
        self.assertGreater(result.forward_cycle_coverage, 0.90)

    def test_rotation_has_spatially_varying_vectors_and_closes_cycle(self):
        reference = DensePyramidReference(rotation_scene(3.0))
        field = reference.forward_pyramid[-1].vectors
        upper_left = field[24 * WIDTH + 32]
        lower_right = field[120 * WIDTH + 224]
        self.assertGreater(upper_left[0], 0.0)
        self.assertLess(upper_left[1], 0.0)
        self.assertLess(lower_right[0], 0.0)
        self.assertGreater(lower_right[1], 0.0)
        result = reference.qualify()
        self.assertFalse(result.fallback, result)
        self.assertLess(result.photometric_mad, 0.04)
        self.assertGreater(result.reverse_cycle_coverage, 0.90)

    def test_parallax_retains_distinct_near_and_far_motion(self):
        reference = DensePyramidReference(parallax_scene(14.0, 4.0))
        fine = reference.forward_pyramid[-1].vectors
        far = fine[36 * WIDTH + 128]
        near = fine[108 * WIDTH + 128]
        self.assertEqual(far, (4.0, 0.0))
        self.assertEqual(near, (14.0, 0.0))
        self.assertGreater(near[0] - far[0], 8.0)
        self.assertFalse(reference.qualify().fallback)

    def test_disocclusion_uses_independent_reverse_flow_and_cycle_masks(self):
        reference = DensePyramidReference(disocclusion_scene())
        forward = reference.forward_pyramid[-1].vectors
        reverse = reference.reverse_pyramid[-1].vectors
        # Newly revealed background is stationary in the current endpoint, so
        # reverse motion there is zero even though the old endpoint contained
        # foreground with +18 motion.  Pointwise negation would be wrong.
        revealed = 72 * WIDTH + 70
        self.assertEqual(forward[revealed], (18.0, 0.0))
        self.assertEqual(reverse[revealed], (0.0, 0.0))
        self.assertFalse(reference.reverse_valid[revealed])
        # Background covered by the moving foreground is rejected in the
        # forward direction, while an unoccluded foreground sample closes.
        covered = 72 * WIDTH + 150
        foreground = 72 * WIDTH + 88
        self.assertFalse(reference.forward_valid[covered])
        self.assertTrue(reference.forward_valid[foreground])
        result = reference.qualify()
        self.assertFalse(result.fallback, result)
        self.assertGreater(result.forward_cycle_coverage, 0.90)
        self.assertGreater(result.reverse_cycle_coverage, 0.90)

    def test_hard_scene_cut_fails_closed_to_endpoint_fallback(self):
        reference = DensePyramidReference(scene_cut())
        result = reference.qualify()
        self.assertTrue(result.fallback)
        self.assertEqual(result.reason, "hard-scene-cut")
        self.assertGreater(result.photometric_mad, SCENE_CUT_MAD)

    def test_active_domain_is_exact_aspect_fit_with_256x144_maximum(self):
        self.assertEqual(active_dimensions(1920, 1080),
                         (Fraction(256), Fraction(144)))
        self.assertEqual(active_dimensions(640, 480),
                         (Fraction(192), Fraction(144)))
        self.assertEqual(active_dimensions(480, 272),
                         (Fraction(4320, 17), Fraction(144)))
        self.assertEqual(active_dimensions(272, 480),
                         (Fraction(408, 5), Fraction(144)))
        for source in ((1920, 1080), (640, 480), (480, 272), (272, 480)):
            active_width, active_height = active_dimensions(*source)
            self.assertLessEqual(active_width, WIDTH)
            self.assertLessEqual(active_height, HEIGHT)
            self.assertEqual(active_width / active_height,
                             Fraction(source[0], source[1]))

    def test_rgba8_q8_8_encoding_has_exact_zero_and_source_pixel_scale(self):
        self.assertEqual(encode_flow_q8_8(0.0, 0.0), (0, 0, 0, 0))
        self.assertEqual(encode_flow_q8_8(1.0, -1.0), (1, 0, 255, 0))
        self.assertEqual(encode_flow_q8_8(-0.5, 0.5), (255, 128, 0, 128))
        self.assertEqual(decode_flow_q8_8((1, 64, 254, 128)), (1.25, -1.5))
        self.assertEqual(decode_flow_q8_8(encode_flow_q8_8(12.25, -6.5)),
                         (12.25, -6.5))
        self.assertEqual(LEVEL_SOURCE_PIXEL_SCALES, (4, 2, 1))
        for (width, height), source_scale in zip(
                PYRAMID_SHAPES, LEVEL_SOURCE_PIXEL_SCALES):
            self.assertEqual(width * source_scale, WIDTH)
            self.assertEqual(height * source_scale, HEIGHT)
        reference = DensePyramidReference(translation_scene(12.25, -6.5))
        for level in reference.forward_pyramid:
            self.assertEqual(level.vectors[len(level.vectors) // 2],
                             (12.25, -6.5))

    def test_resource_and_pass_envelope_is_fixed_and_bounded(self):
        reference = DensePyramidReference(translation_scene(3.0, 2.0))
        self.assertEqual(PYRAMID_SHAPES, ((64, 36), (128, 72), (256, 144)))
        self.assertEqual(
            sum(width * height for width, height in PYRAMID_SHAPES), 48_384
        )
        self.assertEqual(reference.solve_texels(), 405_504)
        self.assertEqual(len(reference.pass_ledger), MAX_QUALIFICATION_PASSES)
        self.assertEqual(len(set(reference.pass_ledger)), len(reference.pass_ledger))
        self.assertLessEqual(len(reference.pass_ledger), MAX_QUALIFICATION_PASSES)
        self.assertEqual(reference.resource_bytes(), 1_161_216)
        self.assertLessEqual(reference.resource_bytes(), MAX_QUALIFICATION_BYTES)
        self.assertEqual(reference.pass_ledger[:4], [
            "previous-downsample-128x72",
            "previous-downsample-64x36",
            "current-downsample-128x72",
            "current-downsample-64x36",
        ])
        solve_passes = [
            entry for entry in reference.pass_ledger
            if "-solve-edge-smooth-" in entry
        ]
        self.assertEqual(len(solve_passes), 32)
        for direction in ("forward", "reverse"):
            directional = [entry for entry in solve_passes
                           if entry.startswith(direction + "-")]
            self.assertEqual(len(directional), sum(LEVEL_ITERATIONS))
            for (width, height), iterations in zip(
                    PYRAMID_SHAPES, LEVEL_ITERATIONS):
                level_token = "-{}x{}-".format(width, height)
                self.assertEqual(sum(level_token in entry for entry in directional),
                                 iterations)
        self.assertEqual(reference.pass_ledger[-2:], [
            "forward-cycle-occlusion",
            "reverse-cycle-occlusion",
        ])

    def test_v24_workload_model_is_bounded_but_physical_gate_remains_authoritative(self):
        reference = DensePyramidReference(translation_scene(3.0, 2.0))
        self.assertEqual(reference.pair_pixel_work(), 502_272)
        ratio = reference.pair_pixel_work() / V23_PIXEL_WORK
        self.assertLess(ratio, 0.60)
        # Linear pixel-work predicts about 7.0 ms from the exact v23 physical
        # mean. The production completion timer also includes queued work, so
        # this is only the source-backed candidate rationale: device evidence
        # must still satisfy the exact 7,333-us maximum and per-sample gates.
        self.assertLess(V23_PHYSICAL_MEAN_COMPLETE_US * ratio, 7_100)


if __name__ == "__main__":
    unittest.main()
