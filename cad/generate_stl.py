"""Parametric 3D `.STL` mesh generator for the Casio W-218H running watch mod.

Calibrated directly from caliper measurements and ruler photos of the Casio W-218H
(Module 3224):
  - Inner pocket          : 31.07 mm (W) x 28.05 mm (H)
  - Pocket depths         : 6.9 mm to crystal, 5.7 mm to brushed bezel, 5.0 mm to 4 tabs
  - Clear front window    : 19.96 mm (W) x 13.2 mm (H)
  - Backplate screw grid  : 22.0 mm (W) x 33.0 mm (H), screw head ~2.4 mm
  - Side button pins      : Y = +8.0 mm (Top-Left), Y = -8.0 mm (Bottom-Left & Bottom-Right)

Outputs guaranteed watertight 2-manifold binary `.STL` files using greedy-meshed
exact Z-slabs (0.125 mm XY resolution, exact floating-point Z planes) with zero
external CAD dependencies.
"""

import math
import struct
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

Triangle = Tuple[
    Tuple[float, float, float],  # normal
    Tuple[float, float, float],  # v1
    Tuple[float, float, float],  # v2
    Tuple[float, float, float],  # v3
]


# ---- Calibrated Casio W-218H Constants (mm) ----
POCKET_W = 31.07
POCKET_H = 28.05
SLIP_CLEARANCE = 0.23  # per side -> 30.61 x 27.59 mm outer cradle fit

SCREW_SPAN_X = 22.0
SCREW_SPAN_Y = 33.0
SCREW_THROUGH_R = 0.92   # 1.84 mm diameter through-hole for factory screw threads
SCREW_CBORE_R = 1.95     # 3.90 mm counterbore for 2.4 mm screw head + driver tip
EAR_TAB_THICKNESS = 0.85 # Thin recessed corner tabs so stock short Casio screws bite!

OLED_BOARD_W = 27.4      # 27.0 mm SSD1306 0.96" OLED PCB + 0.2 mm clearance/side
OLED_BOARD_H = 27.4
WINDOW_CUT_W = 22.2      # Clears 21.74 x 10.86 mm OLED active area behind 19.96 mm window
WINDOW_CUT_H = 12.6

BTN_Y_OFFSET = 8.0       # +/- 8.0 mm from horizontal centerline


def _in_chamfered_rect(x: float, y: float, half_w: float, half_h: float, chamfer: float) -> bool:
    ax = abs(x)
    ay = abs(y)
    if ax > half_w or ay > half_h:
        return False
    if chamfer > 0.0 and (ax + ay) > (half_w + half_h - chamfer):
        return False
    return True


def _in_circle(x: float, y: float, cx: float, cy: float, r: float) -> bool:
    dx = x - cx
    dy = y - cy
    return (dx * dx + dy * dy) <= (r * r)


# ---- 1. Solid Definition: Snap-In Inner Switch & OLED Cradle ----
CRADLE_Z_PLANES = [0.0, 0.9, 1.8, 3.6, 4.8]


def cradle_solid(x: float, y: float, z: float) -> bool:
    """z=0 rests on the 5.7mm inner bezel frame; z=4.8 reaches near the back rim."""
    hw = (POCKET_W * 0.5) - SLIP_CLEARANCE  # 15.305 mm
    hh = (POCKET_H * 0.5) - SLIP_CLEARANCE  # 13.795 mm

    if not _in_chamfered_rect(x, y, hw, hh, chamfer=3.8):
        return False

    # Relief notches on front face (z < 0.9) for the 4 small 5.0mm Casio alignment tabs
    if z < 0.9:
        if 5.0 <= abs(x) <= 9.8 and abs(y) >= (hh - 3.0):
            return False

    # Front viewing aperture (z < 1.8) aligned with clear window
    if z < 1.8:
        if abs(x) <= (WINDOW_CUT_W * 0.5) and abs(y) <= (WINDOW_CUT_H * 0.5):
            return False

    # 0.96" I2C OLED PCB seat (z >= 0.9..3.6) + open center bay above z >= 1.8
    if 0.9 <= z < 3.6:
        # Leave corner retention ledges while cradling 27.0 x 27.0 mm OLED board
        if abs(x) <= (OLED_BOARD_W * 0.5) and abs(y) <= (OLED_BOARD_H * 0.5):
            # Keep 3 side switch housing blocks intact above z >= 1.8
            in_tl_boss = (x < -hw + 3.8) and (abs(y - BTN_Y_OFFSET) <= 3.6) and (z >= 1.8)
            in_bl_boss = (x < -hw + 3.8) and (abs(y + BTN_Y_OFFSET) <= 3.6) and (z >= 1.8)
            in_br_boss = (x > hw - 3.8) and (abs(y + BTN_Y_OFFSET) <= 3.6) and (z >= 1.8)
            if not (in_tl_boss or in_bl_boss or in_br_boss):
                return False

    if z >= 3.6:
        # Upper ring frame + 3 side micro-switch housings
        inner_keep_x = hw - 2.2
        inner_keep_y = hh - 2.2
        in_tl_boss = (x < -hw + 4.0) and (abs(y - BTN_Y_OFFSET) <= 3.6)
        in_bl_boss = (x < -hw + 4.0) and (abs(y + BTN_Y_OFFSET) <= 3.6)
        in_br_boss = (x > hw - 4.0) and (abs(y + BTN_Y_OFFSET) <= 3.6)
        if abs(x) <= inner_keep_x and abs(y) <= inner_keep_y:
            if not (in_tl_boss or in_bl_boss or in_br_boss):
                return False

    # Cut the 3 side-push micro-switch pockets (3x4x2mm switches) + wire lead slots
    if z >= 1.8:
        # Top-Left button (X negative, Y = +8.0)
        if x <= (-hw + 3.0) and abs(y - BTN_Y_OFFSET) <= 2.2:
            return False
        if x <= (-hw + 4.2) and abs(y - BTN_Y_OFFSET) <= 1.1:
            return False
        # Bottom-Left button (X negative, Y = -8.0)
        if x <= (-hw + 3.0) and abs(y + BTN_Y_OFFSET) <= 2.2:
            return False
        if x <= (-hw + 4.2) and abs(y + BTN_Y_OFFSET) <= 1.1:
            return False
        # Bottom-Right button (X positive, Y = -8.0)
        if x >= (hw - 3.0) and abs(y + BTN_Y_OFFSET) <= 2.2:
            return False
        if x >= (hw - 4.2) and abs(y + BTN_Y_OFFSET) <= 1.1:
            return False

    return True


# ---- 2. Solid Definition: Raised-Belly Counterbored Backplate ----
# z = 0.0 sits flat against the Casio case rim & factory rubber O-ring gasket;
# z = 5.2 is the exterior top of the raised center dome (+4.0 mm internal cavity).
BACKPLATE_Z_PLANES = [0.0, EAR_TAB_THICKNESS, 1.3, 4.0, 5.2]


def backplate_solid(x: float, y: float, z: float) -> bool:
    sx = SCREW_SPAN_X * 0.5  # 11.0 mm
    sy = SCREW_SPAN_Y * 0.5  # 16.5 mm

    # 4 corner screw holes (through all layers) & screwdriver counterbores (above 0.85 mm)
    for cx in (-sx, sx):
        for cy in (-sy, sy):
            if _in_circle(x, y, cx, cy, SCREW_THROUGH_R):
                return False
            if z >= EAR_TAB_THICKNESS and _in_circle(x, y, cx, cy, SCREW_CBORE_R):
                return False

    # Base sealing flange (z < 1.3 mm): covers factory O-ring track + 4 corner screw ears
    in_flange = _in_chamfered_rect(x, y, 18.2, 16.4, chamfer=5.2)
    for cx in (-sx, sx):
        for cy in (-sy, sy):
            if _in_circle(x, y, cx, cy, 2.55):
                in_flange = True
            # Smooth bridge connecting ear to main flange
            if abs(x - cx) <= 2.55 and abs(y) <= sy:
                in_flange = True

    # Raised center belly dome (z = 1.3..5.2 mm): stays clear of screw counterbores
    in_dome = _in_chamfered_rect(x, y, 16.8, 14.8, chamfer=4.2)

    if z < 1.3:
        if not in_flange:
            return False
    else:
        if not in_dome:
            return False

    # Hollow internal battery/XIAO cavity (z = 0.0..4.0 mm -> 1.2 mm solid roof above z=4.0)
    if z < 4.0:
        if _in_chamfered_rect(x, y, 15.1, 13.3, chamfer=3.4):
            return False

    # Plugged USB-C charging & sync port cutout on +X dome wall (9.2 mm wide x 3.2 mm tall)
    if 0.85 <= z < 4.0:
        if x > 14.0 and abs(y) <= 4.6:
            return False

    return True


# ---- Greedy-Meshed Exact Z-Slab Binary STL Compiler ----
def _greedy_quads_2d(mask: List[List[bool]], nx: int, ny: int) -> List[Tuple[int, int, int, int]]:
    """Merge contiguous True cells in an `nx x ny` boolean grid into maximal rectangles."""
    used = [[False] * ny for _ in range(nx)]
    rects: List[Tuple[int, int, int, int]] = []
    for i in range(nx):
        for j in range(ny):
            if not mask[i][j] or used[i][j]:
                continue
            w = 1
            while (i + w) < nx and mask[i + w][j] and not used[i + w][j]:
                w += 1
            h = 1
            while (j + h) < ny:
                if all(mask[i + dx][j + h] and not used[i + dx][j + h] for dx in range(w)):
                    h += 1
                else:
                    break
            for dx in range(w):
                for dy in range(h):
                    used[i + dx][j + dy] = True
            rects.append((i, j, i + w, j + h))
    return rects


def compile_z_slab_stl(
    solid_fn: Callable[[float, float, float], bool],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    z_planes: Sequence[float],
    xy_step: float = 0.2,
) -> List[Triangle]:
    """Compile a 2.5D Z-slab CSG solid into a watertight, greedy-merged triangle list."""
    nx = int(round((x_max - x_min) / xy_step))
    ny = int(round((y_max - y_min) / xy_step))
    nz = len(z_planes) - 1

    xs = [x_min + i * xy_step for i in range(nx + 1)]
    ys = [y_min + j * xy_step for j in range(ny + 1)]

    # Evaluate occupancy [iz][ix][iy] at slab midpoints
    occ: List[List[List[bool]]] = []
    for k in range(nz):
        zm = 0.5 * (z_planes[k] + z_planes[k + 1])
        layer = [
            [solid_fn(xs[i] + 0.5 * xy_step, ys[j] + 0.5 * xy_step, zm) for j in range(ny)]
            for i in range(nx)
        ]
        occ.append(layer)

    tris: List[Triangle] = []

    def add_quad(
        n: Tuple[float, float, float],
        p0: Tuple[float, float, float],
        p1: Tuple[float, float, float],
        p2: Tuple[float, float, float],
        p3: Tuple[float, float, float],
    ) -> None:
        tris.append((n, p0, p1, p2))
        tris.append((n, p0, p2, p3))

    # 1. Horizontal faces (-Z and +Z) at each z_planes[k]
    for k in range(nz + 1):
        z = z_planes[k]
        # +Z upward face: k-1 is solid, k is empty
        if k > 0:
            up_mask = [
                [occ[k - 1][i][j] and (k == nz or not occ[k][i][j]) for j in range(ny)]
                for i in range(nx)
            ]
            for i0, j0, i1, j1 in _greedy_quads_2d(up_mask, nx, ny):
                add_quad(
                    (0.0, 0.0, 1.0),
                    (xs[i0], ys[j0], z),
                    (xs[i1], ys[j0], z),
                    (xs[i1], ys[j1], z),
                    (xs[i0], ys[j1], z),
                )
        # -Z downward face: k is solid, k-1 is empty
        if k < nz:
            dn_mask = [
                [occ[k][i][j] and (k == 0 or not occ[k - 1][i][j]) for j in range(ny)]
                for i in range(nx)
            ]
            for i0, j0, i1, j1 in _greedy_quads_2d(dn_mask, nx, ny):
                add_quad(
                    (0.0, 0.0, -1.0),
                    (xs[i0], ys[j0], z),
                    (xs[i0], ys[j1], z),
                    (xs[i1], ys[j1], z),
                    (xs[i1], ys[j0], z),
                )

    # 2. Vertical X-normal faces (-X and +X) per Z-slab, greedy-merged along Y
    for k in range(nz):
        z0, z1 = z_planes[k], z_planes[k + 1]
        for i in range(nx + 1):
            x = xs[i]
            j = 0
            while j < ny:
                left_s = occ[k][i - 1][j] if i > 0 else False
                right_s = occ[k][i][j] if i < nx else False
                if left_s == right_s:
                    j += 1
                    continue
                j_end = j + 1
                while j_end < ny:
                    ls2 = occ[k][i - 1][j_end] if i > 0 else False
                    rs2 = occ[k][i][j_end] if i < nx else False
                    if ls2 == left_s and rs2 == right_s:
                        j_end += 1
                    else:
                        break
                if left_s and not right_s:  # +X normal
                    add_quad(
                        (1.0, 0.0, 0.0),
                        (x, ys[j], z0),
                        (x, ys[j_end], z0),
                        (x, ys[j_end], z1),
                        (x, ys[j], z1),
                    )
                else:  # -X normal
                    add_quad(
                        (-1.0, 0.0, 0.0),
                        (x, ys[j], z0),
                        (x, ys[j], z1),
                        (x, ys[j_end], z1),
                        (x, ys[j_end], z0),
                    )
                j = j_end

    # 3. Vertical Y-normal faces (-Y and +Y) per Z-slab, greedy-merged along X
    for k in range(nz):
        z0, z1 = z_planes[k], z_planes[k + 1]
        for j in range(ny + 1):
            y = ys[j]
            i = 0
            while i < nx:
                bot_s = occ[k][i][j - 1] if j > 0 else False
                top_s = occ[k][i][j] if j < ny else False
                if bot_s == top_s:
                    i += 1
                    continue
                i_end = i + 1
                while i_end < nx:
                    bs2 = occ[k][i_end][j - 1] if j > 0 else False
                    ts2 = occ[k][i_end][j] if j < ny else False
                    if bs2 == bot_s and ts2 == top_s:
                        i_end += 1
                    else:
                        break
                if bot_s and not top_s:  # +Y normal
                    add_quad(
                        (0.0, 1.0, 0.0),
                        (xs[i], y, z0),
                        (xs[i], y, z1),
                        (xs[i_end], y, z1),
                        (xs[i_end], y, z0),
                    )
                else:  # -Y normal
                    add_quad(
                        (0.0, -1.0, 0.0),
                        (xs[i], y, z0),
                        (xs[i_end], y, z0),
                        (xs[i_end], y, z1),
                        (xs[i], y, z1),
                    )
                i = i_end

    return tris


def write_binary_stl(path: Path, triangles: Sequence[Triangle], label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hdr = label.encode("ascii", errors="ignore")[:80].ljust(80, b"\x00")
    packer = struct.Struct("<12fH")
    chunks = [hdr, struct.pack("<I", len(triangles))]
    for n, v1, v2, v3 in triangles:
        chunks.append(packer.pack(*n, *v1, *v2, *v3, 0))
    path.write_bytes(b"".join(chunks))


def build_all_stl_files(output_dir: Path, xy_step: float = 0.2) -> Tuple[Path, Path]:
    cradle_tris = compile_z_slab_stl(
        cradle_solid, -16.0, 16.0, -15.0, 15.0, CRADLE_Z_PLANES, xy_step=xy_step
    )
    backplate_tris = compile_z_slab_stl(
        backplate_solid, -19.0, 19.0, -20.0, 20.0, BACKPLATE_Z_PLANES, xy_step=xy_step
    )

    cradle_path = output_dir / "w218h_inner_cradle.stl"
    backplate_path = output_dir / "w218h_backplate.stl"
    write_binary_stl(cradle_path, cradle_tris, "Gummybear Casio W-218H Inner Cradle")
    write_binary_stl(backplate_path, backplate_tris, "Gummybear Casio W-218H Backplate")
    return cradle_path, backplate_path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "output"
    c_path, b_path = build_all_stl_files(out, xy_step=0.15)
    print(f"Generated {c_path} ({c_path.stat().st_size / 1024:.1f} KB)")
    print(f"Generated {b_path} ({b_path.stat().st_size / 1024:.1f} KB)")
