# Mechanical CAD (`Casio W-218H` Mod)

Ready-to-print `.STL` files calibrated from caliper measurements and overhead ruler photos of the **Casio W-218H (Module 3224)**:
- **Inner Pocket:** `31.07 × 28.05 mm` (`5.7 mm` to inner bezel frame, `5.0 mm` to 4 alignment tabs)
- **Clear Window:** `19.96 × 13.2 mm`
- **Screw Grid:** `22.0 × 33.0 mm` center-to-center, `0.85 mm` recessed corner tabs so **Casio's 4 original factory screws fit directly**
- **Button Pins:** `±8.0 mm` vertically from centerline (Top-Left, Bottom-Left, Bottom-Right)

## Generated Files (`cad/output/`)
1. **`w218h_inner_cradle.stl`** (`30.6 × 27.6 × 4.8 mm`):
   - Slip-fits into the `31.07 × 28.05 mm` pocket with relief notches for Casio's 4 inner tabs.
   - Seats the `27.0 × 27.0 mm` `0.96"` `I2C` OLED centered behind the `19.96 mm` window.
   - Houses `3×` right-angle tactile micro-switches (`3 × 4 × 2 mm`) directly behind Casio's sliding exterior pusher pins.
2. **`w218h_backplate.stl`** (`36.4 × 37.4 × 5.2 mm`):
   - Flat base flange presses evenly across Casio's original rubber O-ring gasket.
   - `0.85 mm`-thin counterbored corner ears reuse Casio's 4 original stainless screws.
   - `+4.0 mm` raised center dome houses the `3.7V` LiPo pouch + `XIAO` with a snug USB-C port slot on the `+X` wall (sealed during runs with a silicone dust/sweat plug).

## Regenerating `.STL` Files
If you ever want to tweak a clearance or switch pocket size in [`generate_stl.py`](./generate_stl.py):
```bash
python3 cad/generate_stl.py
```
*(Tip: Press **Spacebar** on either `.stl` file in macOS Finder to spin it in 3D before taking it to the Makerspace printer!)*
