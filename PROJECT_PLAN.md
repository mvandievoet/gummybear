# Project Gummybear: "Sleeper" Casio GPS + HR Running Watch & Telemetry Pipeline

## 1. Vision & Design Philosophy
Turn a compact, lightweight classic Casio digital watch (**Casio W-218H**) into an ultramarathon-capable **GPS + Live Bluetooth Heart Rate running watch** that syncs to a custom local analytics pipeline and auto-uploads to **Strava**.

### Core Principles
1. **True "Sleeper" Aesthetic & Compact Wrist Feel:** Keep the original Casio W-218H outer case, straps, clear printed front crystal, and metal side buttons completely uncut. Target ~`14.5 mm` total thickness and ~`42 g` total weight (lighter than a Garmin Forerunner 265).
2. **Novice-Friendly Hardware:** Zero custom PCBs or microscopic soldering required for V1. Use off-the-shelf mini-modules wired with flexible `30 AWG` silicone wire at Google's Makerspace.
3. **Dumb Watch, Smart Pipeline:** Keep watch firmware minimal (~300 lines, one crisp run screen, rock-solid binary logging) and push all signal processing, terrain elevation correction, HRV/pace math, local warehousing, and Strava syncing into a Python + DuckDB pipeline on macOS.
4. **Ultramarathon Ready:** Target **20+ hours** of continuous 1 Hz GPS + BLE HR battery life and **27–55+ hours** of onboard run storage without adding bulk.

---

## 2. Answering Key Hardware Constraints

### A. Why Casio's Stock Screen Comes Out (While Keeping the Front Window)
* **What stays:** Casio's clear acrylic outer window (with the retro printed borders, logos, and text) is bonded to the outer case and stays 100% intact.
* **What comes out:** Underneath that window sits a bare piece of liquid-crystal glass connected via a squishy conductive rubber strip ("zebra strip") with ~30 unlabelled AC-multiplexed tracks and fixed etched digit shapes. Wiring it directly to a hobby microcontroller isn't practical (the `XIAO` only has 11 pins total).
* **The swap:** A `nice!view` reflective **Sharp Memory LCD (`36 × 14 mm`)** sits right behind Casio's clear front window. It uses reflective silver/black liquid crystal (no glowing OLED look), is crystal-clear in bright sunlight, draws `< 10 µA`, and wires up with just 5 pins.

### B. How the Casio Side Buttons Work Internally
* Casio's exterior silver buttons are **purely mechanical sliding metal pins** sealed with tiny rubber O-rings—they are *not* electrical switches on their own.
* When you press an exterior Casio button, its metal pin pokes ~`1.5 mm` into the empty interior cavity.
* When we remove Casio's white plastic factory core, we replace it with a **3D-printed internal plastic cradle** holding tiny right-angle tactile micro-switches (`3 × 4 mm`, like mouse click switches) positioned `0.2 mm` behind Casio's metal pins. Pressing the original waterproof Casio button pushes the pin into our micro-switch with a crisp click.

### C. Ultramarathon Battery Without a Bulky Watch (~20–30 Hours)
* Instead of stuffing a huge, heavy battery into a giant watch shell, we cut GPS power draw by **65%** by using a **u-blox M10** mini-module (`Flywoo GM10 Nano V3`, `12 × 16 × 4.5 mm`, ~`15–18 mA`) instead of older `41 mA` GPS chips.
* Combined with BLE HR (`~3 mA`) and the Sharp Memory LCD (`0.01 mA`), total active run draw is **~`20–22 mA`** (or **~`13 mA`** in u-blox 1 Hz `PSMCT` power-save mode).
* A compact **`502530` (`450 mAh`, `5 × 25 × 30 mm`)** or **`602530` (`500 mAh`, `6 × 25 × 30 mm`)** LiPo pouch fits neatly inside the W-218H footprint and delivers **20–22 hours** of continuous full-power tracking (or **30+ hours** in Ultra power-save mode).

### D. Ultramarathon Storage Math
* Each 1-second sample (`timestamp, lat, lon, raw_alt, hdop, sats, bpm, rr_interval_ms`) packs into a **20-byte binary struct** (`72 KB / hour`).
* The `XIAO nRF52840` includes **`2 MB` of onboard QSPI Flash** out of the box:
  * **Raw 1 Hz logging:** `2,048 KB / 72 KB` = **~28 hours** of running before syncing.
  * **Delta-encoded 1 Hz logging** (storing 1-second changes in `int16`): `~34 KB / hour` = **~58 hours** on the built-in `2 MB`.
  * **Optional `\$2` Hardware Expansion:** Soldering a tiny `10 × 10 mm` `W25Q128` (`16 MB` SPI NOR Flash) breakout onto the shared SPI pins boosts raw uncompressed capacity to **~220+ hours** with near-zero battery impact.

### E. Charging & Sweat Sealing Without Cutting the Casio Case
* Because we add a **3D-printed `+3.5 to 4 mm` deeper backplate** (using Casio's 4 original corner screws and a rubber O-ring gasket), **we never cut or drill the Casio W-218H case**.
* **V1 Charging (Simplest):** Expose the `XIAO`'s USB-C port through a snug cutout in the side wall of the *3D-printed backplate* and seal it during runs with a tight silicone USB-C dust/water plug. Gives 1-cable charging, data dump, and firmware flashing.
* **V2 Charging Upgrade (Sweatproof Garmin-Style):** Epoxied, flush **2-pin magnetic pogo target pad** on the underside of the 3D-printed backplate wired to `VUSB (5V)` and `GND`. Runs sync wirelessly to your Mac over Bluetooth (`BLE`), and firmware updates run Over-The-Air (`BLE OTA DFU`).

---

## 3. Bill of Materials (BOM) — ~`\$58` Total

| Component | Part / Model | Dimensions | Est. Cost | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Donor Shell** | Casio `W-218H` | `44.4 × 43.2 × 10.8 mm` | Owned (`\$0`) | Optional roomier backup: Casio `AE-1200WH` or `W-735H` (~`\$22`) |
| **MCU + BLE + Charger** | Seeed Studio `XIAO nRF52840` | `21.0 × 17.8 × 3.5 mm` | `\$10` | BLE 5.0, `2 MB` QSPI flash, `BQ25101` LiPo charger, USB-C |
| **Mini GPS + Antenna** | Flywoo `GOKU GM10 Nano V3` (u-blox M10) | `12.0 × 16.0 × 4.5 mm` | `\$15` | Runs on `3.3V`, built-in patch antenna, ~`15–18 mA` draw |
| **Sunlight Screen** | `nice!view` (`Sharp LS011B7DH03` LCD) | `36.0 × 14.0 × 2.9 mm` | `\$20` | `160 × 68` px reflective LCD, `<10 µA`, 5-pin SPI |
| **Battery** | `502530` or `602530` Protected LiPo (`450–500 mAh`) | `25.0 × 30.0 × 5.0 mm` | `\$7` | Includes built-in overcharge/short protection PCM |
| **Buttons** | `3×` Right-Angle Tactile Switches (`EVQ-P7` / `3×4×2 mm`) | `3.0 × 4.0 × 2.0 mm` | `\$2` | Mounted in 3D-printed inner cradle behind Casio pushers |
| **Power Switch** | `1×` P-Channel MOSFET (`AO3401` / mini high-side load switch) + `10kΩ` resistor | `3.0 × 3.0 mm` | `\$1` | Physically cuts GPS `VCC` to `0.000 mA` when not running (usually free in Makerspace bins) |
| **Consumables** | `30 AWG` Silicone Wire + Kapton Tape + USB-C Silicone Plug + `1.5 mm` O-Ring | — | `\$4` | Silicone wire won't melt when soldering; Kapton tape insulates LiPo pouch from solder joints |
| *(Optional)* | Side-firing warm-white/green SMD LED + `1kΩ` resistor | `2.0 × 1.2 mm` | `\$0.50` | Edge-lights Casio's acrylic window for pitch-dark winter runs (`nice!view` has no built-in backlight) |
| *(Optional)* | `W25Q128` `16 MB` SPI Flash Breakout | `10.0 × 10.0 × 2.0 mm` | `\$2` | Only if >55 hours of offline storage is desired |

---

## 4. Wiring & Pinout Map (`Seeed XIAO nRF52840`)

Total wires to solder: **13 short flexible `30 AWG` silicone wires** (14 if using 3 buttons).

| Subsystem | Module Pin | `XIAO nRF52840` Pad | Purpose |
| :--- | :--- | :--- | :--- |
| **GPS (`GM10 Nano V3`)** | `VCC` | `3V3` *(or switched GPIO / MOSFET)* | `3.3V` power |
| | `GND` | `GND` | Common ground |
| | `TX` | `D7` (`RX`) | NMEA / UBX binary coordinates from GPS → MCU |
| | `RX` | `D6` (`TX`) | Config commands (1 Hz / Ultra PSMCT) MCU → GPS |
| **Screen (`nice!view`)** | `VCC` | `3V3` | `3.3V` power (`<10 µA`) |
| | `GND` | `GND` | Common ground |
| | `SCK` | `D8` (`SCK`) | SPI Clock |
| | `MOSI` (`SDA`) | `D10` (`MOSI`) | SPI Pixel Data |
| | `CS` | `D1` | Display Chip Select |
| **Buttons (Active-Low)** | `BTN_START` | `D2` (internal `INPUT_PULLUP`) | Start / Pause run (other leg wired to `GND`) |
| | `BTN_STOP` | `D3` (internal `INPUT_PULLUP`) | Stop & Save run / Hold to enter BLE Sync |
| | `BTN_MODE` | `D4` (internal `INPUT_PULLUP`) | Toggle Clock ↔ Pre-Run Lock screen |
| **Battery (`450 mAh` LiPo)** | `Red (+)` | Underside `BAT+` pad | Powers system & charges at safe `50/100 mA` via USB-C |
| | `Black (-)` | Underside `BAT-` pad | Battery ground |

> **Power-Off Trick for Zero Idle GPS Drain:** Wire a tiny MOSFET (or pick a GPS breakout with an `EN` pin, or send the u-blox `UBX-RXM-PMREQ` software backup command over `TX`) so the GPS chip drops from `16 mA` to `< 20 µA` whenever you aren't recording a run. That gives the watch **weeks of standby battery life** between runs without turning off the clock.

---

## 5. Mechanical Z-Stackup Inside Casio W-218H

```text
  [ Original Casio Clear Front Window & Resin Bezel ]   ~2.0 mm (existing shell)
  ---------------------------------------------------
  [ nice!view LCD (top half) | GM10 GPS Antenna (top edge, sky-facing) ]  ~3.0–4.5 mm
  [ 3D-Printed Inner Cradle + 3× Side Micro-Switches ]
  [ Seeed XIAO nRF52840 (flat, components facing up) ]  ~3.5 mm (sits beside GPS)
  [ 502530 450mAh LiPo Battery Pouch (25 × 30 × 5 mm) ] ~5.0 mm (bottom layer)
  ---------------------------------------------------
  [ 3D-Printed Custom Backplate (+3.8 mm spacer + O-ring groove) ]
```
* **Total wrist thickness:** ~`14.3–14.8 mm` (stock W-218H is `10.8 mm`; Garmin Forerunner 965 is `13.2 mm`, Fenix 8 is `14.7 mm`).
* **Critical antenna rule:** Do **not** place the battery or copper `XIAO` board *above* the `GM10` ceramic patch antenna—keep the `12 × 16 mm` GPS patch right beneath Casio's plastic bezel/window facing the sky.

---

## 6. Firmware & Binary Telemetry Spec

### Watch State Machine
1. **`CLOCK_IDLE`:** GPS in deep backup sleep (`<20 µA`), BLE off, screen updates once per minute showing `HH:MM`, date, and battery `%`.
2. **`PRE_RUN_LOCK`:** Triggered by `BTN_MODE`. Wakes GPS (`UBX-NAV-PVT` binary mode) and scans BLE for Garmin Heart Rate Service (`0x180D`). Displays `GPS: WAIT/OK` and `HR: --- / 62 BPM`.
3. **`RUNNING`:** Triggered by `BTN_START`. Writes 1 record/sec into a circular file on the `2 MB` LittleFS QSPI flash partition. Screen updates 1×/sec:
   ```text
   +------------------------+
   |  4:42 /km     12.45 km |
   |  ♥ 158 BPM    00:58:31 |
   +------------------------+
   ```
4. **`BLE_SYNC` / `USB_DUMP`:** Triggered after saving a run (or plugging into USB-C). Streams saved binary `.gmy` run files to macOS and marks them synced upon CRC32 acknowledgment.

### Binary Record Layout (`20 bytes / second`)
```c
struct __attribute__((packed)) RunSample {
    uint32_t unix_ts;       // 4B: UTC epoch seconds from GPS
    int32_t  lat_e7;        // 4B: Latitude * 1e7 (~1.1 cm resolution)
    int32_t  lon_e7;        // 4B: Longitude * 1e7
    int16_t  alt_dm;        // 2B: Altitude in decimeters (-3276.8m to +3276.7m)
    uint8_t  hdop_x10;      // 1B: Horizontal dilution of precision * 10
    uint8_t  sat_flags;     // 1B: [bits 0..5: satellite count] [bit 6: paused] [bit 7: hr_valid]
    uint8_t  hr_bpm;        // 1B: Live Heart Rate from Garmin strap (0-255)
    uint16_t rr_ms;         // 2B: Latest raw beat-to-beat R-R interval in ms (for HRV)
    uint8_t  crc8;          // 1B: Frame integrity check
}; // Total = 20 bytes
```

---

## 7. Mac Data Pipeline Architecture (`gummybear`)

```text
[ Sleeper Casio Watch ]
       │  (USB-C Serial in V1  /  macOS `bleak` BLE Sync in V2)
       ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. `gummybear/ingest`                                        │
│    • Pulls raw `.gmy` binary logs, validates CRC, archives   │
│      immutable raw files under `data/raw/`                   │
├──────────────────────────────────────────────────────────────┤
│ 2. `gummybear/processing`                                    │
│    • Outlier rejection + HDOP-weighted 2D Kalman Filter      │
│      (cleans urban canyon bounce in SF / tree cover)         │
│    • Elevation DEM Snapping (USGS 3DEP high-res tiles)       │
│    • Derives splits, Grade-Adjusted Pace (GAP), cardiac      │
│      drift (Pa:Hr), and R-R interval HRV / DFA-alpha1        │
├──────────────────────────────────────────────────────────────┤
│ 3. `gummybear/storage` (DuckDB: `data/gummybear.duckdb`)     │
│    • Tables: `runs`, `samples_raw`, `samples_clean`,         │
│      `rr_intervals`, `strava_uploads`                        │
├──────────────────────────────────────────────────────────────┤
│ 4. `gummybear/export`                                        │
│    • Encodes Garmin `.FIT` (or `.GPX` + HR TrackPointExt)    │
│    • OAuth2 auto-upload via `POST strava.com/api/v3/uploads` │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Phased Execution Roadmap

### Phase 1: Build & Test the Mac Pipeline First (No Hardware Required) — COMPLETED
- [x] Set up Python package (`pyproject.toml`, zero-dependency stdlib core) in `gummybear` + shared C header `firmware/include/gummybear_protocol.h`.
- [x] Implement the 20-byte `.gmy` binary parser/generator (with crash-safe unclosed ultra salvage) + synthetic noisy SF run generator (`gummybear/simulator.py`).
- [x] Build the 2D `HDOP`-weighted Rauch-Tung-Striebel (`RTS`) Kalman smoother + elevation denoising/USGS 3DEP hook (`gummybear/kalman.py`) + SQLite/DuckDB warehouse (`gummybear/storage.py`).
- [x] Build the binary Garmin `.FIT` encoder (`gummybear/export_fit.py`), `.GPX` + HR encoder (`gummybear/export_gpx.py`), and Strava OAuth2 CLI uploader (`gummybear/strava.py`).

### Phase 2: Breadboard / Desk Prototype (Order Parts ~`\$58`, Zero Case Fitting Yet)
- [ ] Flash Arduino / CircuitPython / Zephyr test sketch onto `Seeed XIAO nRF52840` over USB-C.
- [ ] Pair with your Garmin HR chest strap (`0x180D`) and print live BPM + `R-R` intervals to laptop terminal.
- [ ] Connect `GM10 Nano V3` GPS + `nice!view` display using temporary jumper wires/breadboard; step outside to confirm satellite lock and sunlight screen readability.
- [ ] Carry the desk prototype in a pocket/ziplock on a 2 km test jog, dump the `.gmy` file over USB-C, and watch it land on Strava through your Phase 1 pipeline.

### Phase 3: Makerspace Soldering
- [ ] At Google's Makerspace soldering station, wire the `XIAO`, `GM10 Nano`, `nice!view`, 3 micro-switches, and `450 mAh` LiPo using short `30 AWG` silicone wires.
- [ ] Verify battery charging (`100 mA` mode), GPS software sleep current (`<50 µA` idle), and continuous run battery endurance test on a windowsill.

### Phase 4: CAD Cradle, Custom Backplate & Casio W-218H Transplant
- [ ] Unscrew the W-218H backplate, remove the stock Casio module (keep in a bag so it's reversible!), and measure internal cavity + button pin positions with digital calipers at the Makerspace.
- [ ] 3D-print the snap-in internal switch/screen cradle + `+3.8 mm` custom backplate (with O-ring groove and plugged USB-C port for V1).
- [ ] Assemble, grease O-ring for sweat resistance, and take it out for a real SF run.

### Phase 5: Optional V2 Upgrades
- [ ] Swap plugged USB-C backplate for flush 2-pin magnetic pogo charging + automatic wireless `bleak` BLE sync when walking in the door.
- [ ] Add `\$2` `W25Q128` `16 MB` flash chip if multi-day backcountry / 100-mile stage logging is needed.
