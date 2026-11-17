# Mechanical CAD (`Casio W-218H` Mod)

3D-printable `.STL` parts modeled using **1-decimal-place Nominal Geometry + Directional Process Clearance (`±c`)**.

## Nominal Design Intent vs. Fit Clearance (`ISO 286` / DfAM)

Rather than carrying `0.01 mm` hand-caliper noise into the model, all features are defined at clean `0.1 mm` metric nominals, and a single per-side fabrication clearance `c` is applied directionally:

- **Positional datums stay exact (`±0`):** Screw grid (`22.0 × 33.0 mm`), button centers (`±8.0 mm`), window center.
- **External inserts (`Nominal - 2c`):** Cradle outer body (`31.0 - 2c` × `28.0 - 2c`) so it slides into Casio's `31.0 × 28.0 mm` pocket without binding.
- **Internal pockets & holes (`Nominal + 2c`):** OLED bay (`27.0 + 2c`), switch slots (`3.0 × 4.0 + 2c`), screw holes (`1.6 + 2c`), and USB-C port (`9.0 × 3.2 + 2c`).

| Printer Process | Flag | Clearance `c` (per side) | Cradle Outer Fit | OLED Inner Pocket |
| :--- | :--- | :--- | :--- | :--- |
| **SLA Resin** *(Formlabs)* | `--process sla` | `0.1 mm` | `30.8 × 27.8 mm` | `27.2 × 27.2 mm` |
| **FDM Filament** *(Bambu / Prusa)* | `--process fdm` *(default)* | `0.2 mm` | `30.6 × 27.6 mm` | `27.4 × 27.4 mm` |

*(For reference, Casio's factory injection-molded module uses `c ≈ 0.05 mm`—ideal for steel molds, too tight for 3D prints due to resin cure / filament bead swell.)*

## Generated Files (`cad/output/`)
1. **`w218h_inner_cradle.stl`** (`4.8 mm` tall): Slip-fits into the Casio pocket (with reliefs for Casio's 4 front tabs), seats the `0.96"` `I2C` OLED behind the `20.0 mm` window, and holds `3×` side-push switches (`3 × 4 × 2 mm`) behind Casio's pusher pins.
2. **`w218h_backplate.stl`** (`5.2 mm` tall): Presses flat over Casio's rubber O-ring, uses `0.8 mm` recessed corner tabs (`22.0 × 33.0 mm` grid) so **Casio's 4 original screws thread right in**, and adds `+4.0 mm` internal height + a USB-C port slot.

## Regenerating for SLA vs. FDM
```bash
# Filament printer (Bambu / Prusa — 0.2 mm/side clearance):
python3 cad/generate_stl.py --process fdm

# Resin printer (Formlabs SLA — 0.1 mm/side clearance):
python3 cad/generate_stl.py --process sla
```
