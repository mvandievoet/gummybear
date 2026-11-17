# Project Plan: Casio W-218H Running Watch

This guide walks through how we are turning a regular **Casio W-218H** casual digital watch into a lightweight, ultramarathon-capable **GPS + Heart Rate running watch** that syncs to **Strava**.

---

## 1. The Big Idea

We want a watch that feels and looks like a simple everyday Casio on the wrist (~`42 g`, no touchscreen menus or phone notifications), while doing the three things that actually matter on a run:
1. **Track GPS route, distance, and live pace** without carrying a phone.
2. **Connect directly to a Bluetooth heart-rate strap** so live BPM shows on the wrist and syncs alongside the GPS track.
3. **Upload cleanly to Strava** after the run, while saving rich raw data locally.

### Keeping Watch Code Simple & Putting the Brains on the Computer
Instead of making the tiny watch processor do heavy math or complicated menus, we split the work cleanly:
* **The Watch stays minimal:** One everyday Clock screen and one clean Run screen. During a run, it simply writes one tiny 20-byte snapshot every second (time, GPS position, GPS signal quality, heart rate, and heartbeat interval) onto its built-in memory.
* **The Mac pipeline does the heavy lifting:** When you sync after a run, Python cleans up city-building GPS bounce with a Kalman filter, calculates splits and hill-adjusted pace (`GAP`), archives everything locally, packs a standard Garmin `.FIT` file, and uploads it straight to Strava.

---

## 2. How the Hardware Fits Together (Plain-English Q&A)

### How do we fit GPS and a rechargeable battery into a small watch?
Older hobby GPS chips draw ~`40+ mA` of power, which would require a bulky battery to survive a long trail run. Instead, we use a fingernail-sized 10th-generation **u-blox M10 GPS module (`Flywoo GM10 Nano V3.1`)** that draws ~`65%` less power (`~16–20 mA`) and already has its antenna built right on top. Paired with a slim `450 mAh` pouch battery, we get **~20+ hours of continuous GPS + Heart Rate tracking** (plenty for an ultramarathon) while keeping the watch compact.

### Why do we swap the inner screen (while keeping Casio's front window)?
* **What stays:** Casio's clear outer front window (`20.0 × 13.5 mm` viewing area)—with all the classic printed borders and logos—is glued into the outer shell and stays untouched.
* **What changes underneath:** Casio's inner pocket measures **`31.0 × 28.0 mm`**, and Casio's bare liquid-crystal glass uses ~30 unlabelled rubber contacts that can't connect to a small hobby chip. We drop a **`0.96"` `I2C` OLED module (`27 × 27 mm` board, `21.7 × 10.9 mm` screen)** right behind Casio's clear window—it fits the `31 × 28 mm` pocket with zero case cutting, fills the `20 mm` window cleanly, is readable day or night without an extra backlight LED, and wires up with just 4 pins (`VCC, GND, SCL, SDA`). *(Our firmware also supports the `36 mm` `nice!view` reflective LCD for desk testing or wider Casio shells.)*

### How do the original Casio side buttons keep working?
The 3 silver buttons on the outside of a Casio aren't electrical switches—they are just sliding metal pins sealed with tiny rubber O-rings. When we remove Casio's original plastic core, those pins poke into empty space. At the Makerspace, we 3D-print a thin **internal plastic cradle** that holds 3 tiny clicky micro-switches (like mouse buttons) right behind Casio's sliding pins, so the original exterior buttons click naturally.

### How do we close the watch, charge it, and keep sweat out?
Stacking a rechargeable battery under the electronics adds ~`3.8 mm` of center depth compared to a thin coin battery. Instead of cutting or drilling the Casio case (keeping the whole mod 100% reversible!), we **3D-print a raised-belly custom backplate**:
* **0.8 mm counterbored corner ears** reuse Casio's **4 original factory screws** (`22.0 × 33.0 mm` spacing) and press directly onto Casio's original rubber O-ring gasket, keeping the outer bezel looking stock-thin while only the center dome steps out `+3.8 mm` over the battery.
* **V1 Charging:** The USB-C port sits flush in the side of that raised center dome, sealed during runs with a snug silicone waterproof plug. One cable charges the battery and syncs runs.
* **Future Upgrade:** Flush Garmin-style magnetic charging pads on the backplate + wireless sync.

### How many runs can it hold before syncing?
Each 1-second data point takes just **20 bytes** (`72 KB` per hour of running). The `XIAO` main board already has **`2 MB` of flash storage built in**, which holds **~28 hours of running** across as many separate runs as you want (`run_0001.gmy`, `run_0002.gmy`, etc.) before needing to sync.

---

## 3. Parts List

| Role | Part | Size | Approx. Cost | Why This Part |
| :--- | :--- | :--- | :--- | :--- |
| **Watch Shell** | Casio `W-218H` | `31.0 × 28.0 mm` inner pocket | Owned | Lightweight (`37 g`) resin shell; plastic lets GPS signals pass through |
| **Brain + Bluetooth** | Seeed Studio `XIAO nRF52840` (unpinned) | `21 × 18 × 3.5 mm` | `$10` (×2) | Ordered (DigiKey) — BLE HR, `2 MB` storage, LiPo charger + USB-C |
| **GPS + Antenna** | Flywoo `GOKU GM10 Nano V3.1` (4-pin, no compass) | `12 × 16 × 4.5 mm` | `$25` | Ordered (GetFPV) — M10 GPS with built-in antenna + plug cable |
| **Watch Screen** | `0.96"` `I2C` OLED (`SSD1306`, `128 × 64`, 4-pin) | `27 × 27 × 2.5 mm` | `$5` | Drops straight into `31 × 28 mm` pocket with zero case cutting (`nice!view` also on hand for desk/wider case) |
| **GPS Power Switch** | `LP0701N3-G` P-Channel MOSFET + `10 kΩ` resistor | Legged `TO-92` | `$2` | Ordered (DigiKey) — cuts GPS power to `0.000 mA` when idle |
| **Battery** | `602525` (`400 mAh`) or `502025` (`250 mAh`) Protected LiPo | `≤ 25 × 25 × 6 mm` | `$8` | Fits cleanly inside `31.0 × 28.0 mm` pocket with room for wire bend |
| **Watch Switches** | `3×` Right-angle side-push micro-switches (`3 × 4 × 2 mm`) | `3 × 4 × 2 mm` | `$5` | Click sideways when Casio's exterior buttons push inward |
| **Bench & Wiring** | Mini solderless breadboard + Dupont jumper wires + `30 AWG` silicone wire + USB-C silicone plug | — | `$18` | Desk prototyping + flexible final watch wiring |

---

## 4. Simple Wiring Map

Everything connects to the **`Seeed XIAO nRF52840`**. When not running, pin `D0` switches off the MOSFET so the GPS module draws zero battery while the watch sits on your wrist or nightstand.

| Component | Wire / Pin | Connects to `XIAO` | What It Does |
| :--- | :--- | :--- | :--- |
| **GPS Power Switch (`LP0701N3-G`)** | Source / Gate / Drain (+ `10 kΩ` pull-up) | `3V3`, `D0`, and GPS `VCC` | Turns GPS power completely ON (`D0 = LOW`) or OFF (`D0 = HIGH`) |
| **GPS (`GM10 Nano V3.1`)** | `VCC` / `GND` / `TX` / `RX` | Switched `3V3`, `GND`, `D7`, `D6` | Sends live satellite position & atomic UTC time to the watch |
| **Screen (`0.96"` OLED)** | `VCC` / `GND` / `SDA` / `SCL` | `3V3`, `GND`, `D4`, `D5` | Draws Clock (auto-sleeps after 8s so zero night glow) & Always-On Run screen *(or flip `DISPLAY_USE_OLED 0` for `nice!view` on `D8/D10/D9`)* |
| **3 Side Buttons** | Top-Left / Bottom-Left / Bottom-Right | `D3`, `D1`, `D2` (other leg to `GND`) | Controls watch modes, Start/Pause, Save, and Delete |
| **LiPo Battery** | `Red (+)` and `Black (-)` | Underside `BAT+` and `BAT-` pads | Powers the watch and recharges automatically over USB-C |

### Physical Layering Inside the Watch (Top to Bottom)
1. **Original Casio Clear Front Window** *(untouched)*
2. **`nice!view` Screen** + **`GM10` GPS Antenna** *(kept right under the plastic top bezel facing the sky—never buried under metal or the battery)*
3. **3D-Printed Inner Cradle** *(holds screen centered + holds the 3 tiny clicky switches behind Casio's side buttons)*
4. **`XIAO nRF52840` Board** *(sits flat)*
5. **LiPo Battery Pouch** *(insulated with Kapton tape)*
6. **3D-Printed `+3.8 mm` Custom Backplate** *(reuses Casio's 4 original screws + rubber gasket)*

---

## 5. Everyday Watch & Running Controls

The `W-218H` has 3 side buttons—**Bottom-Left**, **Bottom-Right**, and **Top-Left**:

| Watch Screen | **Bottom-Left** | **Bottom-Right** | **Top-Left** |
| :--- | :--- | :--- | :--- |
| **1. Everyday Clock** *(Time, Date, Zone, Battery, `#` Saved Runs)* | **Pre-Run Mode** *(turns on GPS + pairs HR strap)* | — | **Hold 2 sec:** Cycle travel timezone (Daylight Saving adjusts automatically!) |
| **2. Pre-Run Ready** *(Shows `GPS: OK` + live `HR`)* | **Cancel** back to Clock *(turns GPS/BLE off)* | **START** recording new run | — |
| **3. Running** *(`Pace`, `Distance`, `Live HR`, `Timer`)* | — | **PAUSE** *(e.g. at a red light)* | *(Locked while moving so a jacket sleeve can never end your run)* |
| **4. Paused** *(Shows `PAUSED`)* | **Hold 2 sec:** **DELETE** *(discards accidental run)* | **RESUME** running | **SAVE** *(saves file & returns to Clock)* |

---

## 6. Step-by-Step Build Roadmap

### Step 1: Data Pipeline & Strava Upload (Mac) — Done!
- [x] Binary `.gmy` run log format with crash-safe recovery (even if the battery dies mid-ultra, every recorded second up to that point is saved).
- [x] 2-pass Kalman GPS smoother + elevation smoothing + kilometer splits, Grade-Adjusted Pace (`GAP`), cardiac drift, and chest-strap HRV (`RMSSD` / `SDNN`).
- [x] Local SQLite run database + binary Garmin `.FIT` and `.GPX` exporters.
- [x] Strava OAuth2 connection verified and tested live on Strava.

### Step 2: Watch Firmware (`firmware/`) — Written & Ready to Flash!
- [x] Garmin `0x180D` Bluetooth Heart Rate + `R-R` interval parser.
- [x] Fixed-point u-blox GPS parser + automatic US/Canada & EU/UK Daylight Saving Time clock.
- [x] `nice!view` screen layout, multi-run file storage (`/runs/run_0001.gmy`, ...), Pause/Save/Delete safety, and USB-C sync command (`python3 -m gummybear sync --upload`).

### Step 3: Makerspace Measurement & Desk Prototype *(Current Step)*
- [ ] Open the `W-218H` at Google's Makerspace, measure the internal cavity & button positions with calipers (plus 2 overhead photos next to a ruler), and pick up freebies (breadboard, jumper wires, silicone wire, Kapton tape, micro-switches).
- [ ] Order the matching protected LiPo battery (`502530` or `502030`).
- [ ] When DigiKey / GetFPV / Typeractive parts arrive: wire everything up on a breadboard on your desk (no soldering on the screen thanks to the spring headers!), flash the `XIAO`, pair your Garmin chest strap, lock GPS outside, and log a first test walk/run to Strava.

### Step 4: 3D-Print the Inner Cradle & Backplate (`cad/`)
- [ ] Plug your Makerspace caliper numbers into a Python `.STL` generator in `cad/` to output the snap-in switch cradle and `+3.8 mm` backplate.
- [ ] Print on a Makerspace 3D printer (ideally Formlabs SLA resin for watertightness and crisp switch slots) and test-fit inside the empty `W-218H` shell before soldering.

### Step 5: Makerspace Soldering & Final Watch Assembly
- [ ] Solder short flexible `30 AWG` silicone wires between the `XIAO`, MOSFET, GPS plug harness, `nice!view`, 3 micro-switches, and LiPo battery (with Kapton tape between board and battery).
- [ ] Seat everything into the 3D-printed cradle inside the `W-218H`, screw down the custom backplate over Casio's rubber gasket, pop in the silicone USB-C plug, and take it out for a real run!

### Step 6: Optional Future Conveniences
- [ ] **Auto-upload on USB plug-in:** Add a macOS `launchd` rule matching the `XIAO` USB ID (`0x2886:0x8045`) so runs upload automatically the moment you plug in to charge—ignoring all other USB-C devices.
- [ ] **Laptop-free wireless sync:** Either a 1-tap phone bookmark backed by a free Cloudflare Worker, or an `$8` Wi-Fi/BLE plug by the front door that grabs runs automatically when you walk home.
- [ ] **Multi-sport modes (`RIDE` / `HIKE` / `SKI` / `WORKOUT`):** Add a quick sport toggle on the Pre-Run screen—switching `RIDE` to live `km/h` (+ optional `0x1818` BLE power meter pairing), `WORKOUT` to GPS-off Heart Rate tracking for court/indoor sports, and setting the matching `.FIT` sport byte + Kalman speed cap for Strava.
