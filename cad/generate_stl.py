"""Parametric 3D `.STL` generator using Nominal Geometry + Directional Process Clearance.

Design Methodology (ISO 286 Hole/Shaft Basis adapted for Additive Manufacturing):
  1. Recover 1-decimal-place metric NOMINAL design intent from caliper measurements
     (discarding +/-0.05 mm hand-caliper / mold-draft noise).
  2. Keep positional datums (screw hole centers, window center, button offsets) at
     EXACT nominal values.
  3. Apply a single per-side process clearance `c` directionally:
       - External mating features (cradle outer walls) : `Nominal - 2*c`
       - Internal pockets & holes (OLED, switches, screws) : `Nominal + 2*c`
     where:
       - `c = 0.1 mm` for SLA Resin printers (e.g., Formlabs)
       - `c = 0.2 mm` for FDM Filament printers (e.g., Bambu / Prusa, default)
       (For comparison, injection molding uses `c ~ 0.05 mm`, which is too tight for 3D prints.)
"""

import argparse
import struct
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

Triangle = Tuple[
    Tuple[float, float, float],
    Tuple[float, float, float],
    Tuple[float, float, float],
    Tuple[float, float, float],
]

PROCESS_CLEARANCE_MM: Dict[str, float] = {
    "sla": 0.1,  # Resin stereolithography (+/- 0.05..0.08 mm machine accuracy)
    "fdm": 0.2,  # Filament extrusion (+/- 0.15 mm bead swell & corner bulge)
}

# ---- 1-Decimal Nominal Dimensions of Casio W-218H & Components (mm) ----
NOM_POCKET_W = 31.0
NOM_POCKET_H = 28.0
NOM_WINDOW_W = 20.0
NOM_WINDOW_H = 13.2

NOM_SCREW_SPAN_X = 22.0
NOM_SCREW_SPAN_Y = 33.0
NOM_SCREW_SHAFT_D = 1.6
NOM_SCREW_DRIVER_D = 3.6  # Clearance for #00 Phillips driver tip + 2.4 mm head
NOM_EAR_THICKNESS = 0.8

NOM_OLED_W = 27.0
NOM_OLED_H = 27.0
NOM_OLED_ACTIVE_W = 21.8
NOM_OLED_ACTIVE_H = 11.0

NOM_SWITCH_DEPTH = 3.0
NOM_SWITCH_WIDTH = 4.0
NOM_BTN_OFFSET_Y = 8.0

NOM_USBC_PLUG_W = 9.0
NOM_USBC_PLUG_H = 3.2


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


CRADLE_Z_PLANES = [0.0, 0.9, 1.8, 3.6, 4.8]
BACKPLATE_Z_PLANES = [0.0, NOM_EAR_THICKNESS, 1.3, 4.0, 5.2]


def make_cradle_solid(clearance_per_side: float) -> Callable[[float, float, float], bool]:
    c = clearance_per_side
    # External plug into Casio pocket: Nominal - 2*c (subtract `c` from each half-extent)
    hw = (NOM_POCKET_W * 0.5) - c
    hh = (NOM_POCKET_H * 0.5) - c

    # Internal pockets receiving components: Nominal + 2*c (add `c` to each half-extent)
    oled_hw = (NOM_OLED_W * 0.5) + c
    oled_hh = (NOM_OLED_H * 0.5) + c
    win_hw = (NOM_OLED_ACTIVE_W * 0.5) + c
    win_hh = (NOM_OLED_ACTIVE_H * 0.5) + c
    sw_depth = NOM_SWITCH_DEPTH + c
    sw_half_w = (NOM_SWITCH_WIDTH * 0.5) + c

    def solid(x: float, y: float, z: float) -> bool:
        if not _in_chamfered_rect(x, y, hw, hh, chamfer=3.8):
            return False

        # Relief cutouts on front face (z < 0.9) for Casio's 4 alignment tabs at 5.0 mm depth
        if z < 0.9 and (5.0 <= abs(x) <= 9.8) and abs(y) >= (hh - 3.0):
            return False

        # Front viewing aperture
        if z < 1.8 and abs(x) <= win_hw and abs(y) <= win_hh:
            return False

        # Internal seat cradling 27.0 x 27.0 mm OLED PCB
        if 0.9 <= z < 3.6 and abs(x) <= oled_hw and abs(y) <= oled_hh:
            in_tl = (x < -hw + 3.8) and (abs(y - NOM_BTN_OFFSET_Y) <= 3.6) and (z >= 1.8)
            in_bl = (x < -hw + 3.8) and (abs(y + NOM_BTN_OFFSET_Y) <= 3.6) and (z >= 1.8)
            in_br = (x > hw - 3.8) and (abs(y + NOM_BTN_OFFSET_Y) <= 3.6) and (z >= 1.8)
            if not (in_tl or in_bl or in_br):
                return False

        if z >= 3.6:
            in_tl = (x < -hw + 4.0) and (abs(y - NOM_BTN_OFFSET_Y) <= 3.6)
            in_bl = (x < -hw + 4.0) and (abs(y + NOM_BTN_OFFSET_Y) <= 3.6)
            in_br = (x > hw - 4.0) and (abs(y + NOM_BTN_OFFSET_Y) <= 3.6)
            if abs(x) <= (hw - 2.2) and abs(y) <= (hh - 2.2) and not (in_tl or in_bl or in_br):
                return False

        # 3 side-push micro-switch pockets positioned at exact nominal Y = +/- 8.0 mm
        if z >= 1.8:
            if x <= (-hw + sw_depth) and abs(y - NOM_BTN_OFFSET_Y) <= sw_half_w:
                return False
            if x <= (-hw + sw_depth + 1.2) and abs(y - NOM_BTN_OFFSET_Y) <= 1.1:
                return False
            if x <= (-hw + sw_depth) and abs(y + NOM_BTN_OFFSET_Y) <= sw_half_w:
                return False
            if x <= (-hw + sw_depth + 1.2) and abs(y + NOM_BTN_OFFSET_Y) <= 1.1:
                return False
            if x >= (hw - sw_depth) and abs(y + NOM_BTN_OFFSET_Y) <= sw_half_w:
                return False
            if x >= (hw - sw_depth - 1.2) and abs(y + NOM_BTN_OFFSET_Y) <= 1.1:
                return False

        return True

    return solid


def make_backplate_solid(clearance_per_side: float) -> Callable[[float, float, float], bool]:
    c = clearance_per_side
    # Positional screw datums stay at EXACT nominal (never add clearance to center spacing!)
    sx = NOM_SCREW_SPAN_X * 0.5  # 11.0 mm
    sy = NOM_SCREW_SPAN_Y * 0.5  # 16.5 mm

    # Internal holes expand by +c on radius (+2*c on diameter)
    screw_r = (NOM_SCREW_SHAFT_D * 0.5) + c
    cbore_r = (NOM_SCREW_DRIVER_D * 0.5) + c
    usbc_half_w = (NOM_USBC_PLUG_W * 0.5) + c

    def solid(x: float, y: float, z: float) -> bool:
        for cx in (-sx, sx):
            for cy in (-sy, sy):
                if _in_circle(x, y, cx, cy, screw_r):
                    return False
                if z >= NOM_EAR_THICKNESS and _in_circle(x, y, cx, cy, cbore_r):
                    return False

        in_flange = _in_chamfered_rect(x, y, 18.2, 16.4, chamfer=5.2)
        for cx in (-sx, sx):
            for cy in (-sy, sy):
                if _in_circle(x, y, cx, cy, 2.5):
                    in_flange = True
                if abs(x - cx) <= 2.5 and abs(y) <= sy:
                    in_flange = True

        in_dome = _in_chamfered_rect(x, y, 16.8, 14.8, chamfer=4.2)
        if z < 1.3:
            if not in_flange:
                return False
        else:
            if not in_dome:
                return False

        if z < 4.0 and _in_chamfered_rect(x, y, 15.1, 13.3, chamfer=3.4):
            return False

        if NOM_EAR_THICKNESS <= z < 4.0 and x > 14.0 and abs(y) <= usbc_half_w:
            return False

        return True

    return solid


def _greedy_quads_2d(mask: List[List[bool]], nx: int, ny: int) -> List[Tuple[int, int, int, int]]:
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
    xy_step: float = 0.1,
) -> List[Triangle]:
    """Compile a 2.5D Z-slab CSG solid on an exact symmetric `0.1 mm` grid."""
    nx = int(round((x_max - x_min) / xy_step))
    ny = int(round((y_max - y_min) / xy_step))
    nz = len(z_planes) - 1

    # Symmetric grid coordinates aligned to exact 0.1 mm boundaries
    xs = [round(x_min + i * xy_step, 4) for i in range(nx + 1)]
    ys = [round(y_min + j * xy_step, 4) for j in range(ny + 1)]

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

    for k in range(nz + 1):
        z = z_planes[k]
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
                if left_s and not right_s:
                    add_quad(
                        (1.0, 0.0, 0.0),
                        (x, ys[j], z0),
                        (x, ys[j_end], z0),
                        (x, ys[j_end], z1),
                        (x, ys[j], z1),
                    )
                else:
                    add_quad(
                        (-1.0, 0.0, 0.0),
                        (x, ys[j], z0),
                        (x, ys[j], z1),
                        (x, ys[j_end], z1),
                        (x, ys[j_end], z0),
                    )
                j = j_end

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
                if bot_s and not top_s:
                    add_quad(
                        (0.0, 1.0, 0.0),
                        (xs[i], y, z0),
                        (xs[i], y, z1),
                        (xs[i_end], y, z1),
                        (xs[i_end], y, z0),
                    )
                else:
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


def build_all_stl_files(
    output_dir: Path, process: str = "fdm", xy_step: float = 0.1
) -> Tuple[Path, Path]:
    c = PROCESS_CLEARANCE_MM[process]
    cradle_tris = compile_z_slab_stl(
        make_cradle_solid(c), -16.0, 16.0, -15.0, 15.0, CRADLE_Z_PLANES, xy_step=xy_step
    )
    backplate_tris = compile_z_slab_stl(
        make_backplate_solid(c), -20.0, 20.0, -20.0, 20.0, BACKPLATE_Z_PLANES, xy_step=xy_step
    )

    cradle_path = output_dir / "w218h_inner_cradle.stl"
    backplate_path = output_dir / "w218h_backplate.stl"
    write_binary_stl(cradle_path, cradle_tris, f"Gummybear W-218H Cradle ({process.upper()}, c={c}mm)")
    write_binary_stl(backplate_path, backplate_tris, f"Gummybear W-218H Backplate ({process.upper()}, c={c}mm)")
    return cradle_path, backplate_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate W-218H 3D-printable STL meshes.")
    parser.add_argument(
        "--process",
        choices=["fdm", "sla"],
        default="fdm",
        help="Printer process preset: 'sla' (c=0.1mm/side resin) or 'fdm' (c=0.2mm/side filament)",
    )
    args = parser.parse_args()
    out = Path(__file__).resolve().parent / "output"
    c_path, b_path = build_all_stl_files(out, process=args.process, xy_step=0.1)
    print(f"[{args.process.upper()} c={PROCESS_CLEARANCE_MM[args.process]}mm/side] Generated:")
    print(f"  {c_path} ({c_path.stat().st_size / 1024:.1f} KB)")
    print(f"  {b_path} ({b_path.stat().st_size / 1024:.1f} KB)")
