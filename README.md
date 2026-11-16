# Gummybear

Turning a lightweight, everyday casual digital watch (**Casio W-218H**) into a standalone **GPS + Bluetooth Heart Rate running watch** that uploads runs straight to **Strava**.

## Goal

Most GPS running watches look and feel like bulky mini-smartwatches, while classic digital Casios are light, simple, and comfortable to wear all day—yet even Casio's connected fitness models either require carrying your phone for GPS or refuse to pair with external chest heart-rate straps.

**Gummybear** keeps the compact outer case, buttons, and sunlight-readable digital look of a **Casio W-218H** (~`42 g`), while replacing its internals with a tiny Bluetooth microcontroller, a low-power GPS receiver, and a rechargeable battery—paired with a custom post-run data pipeline on macOS.

### What It Does
* **Everyday Watch Mode:** Shows local time and date with **automatic Daylight Saving Time** (US/Canada and EU/UK rules), quick travel timezone switching (`SFO`, `TOR`, `LIS`, `BRU`, etc.), battery status, and multi-week standby battery life.
* **Standalone Run Tracking (Up to Ultramarathon Distances):**
  * Locks onto GPS satellites directly on the watch (no phone needed).
  * Pairs over Bluetooth (`BLE`) with a **Garmin chest heart-rate strap** to display live BPM on your wrist and record raw millisecond beat-to-beat (`R-R`) intervals.
  * Shows a single, distraction-free run screen (`Pace`, `Distance`, `Live HR`, `Elapsed Time`) with Start, Pause/Resume, Save, and Hold-to-Delete controls.
  * Stores **~28+ hours** of 1-second GPS + HR data across dozens of separate runs in onboard flash memory (~20+ hours of continuous GPS battery life per charge).
* **Post-Run Telemetry Pipeline:**
  * Pulls saved binary `.gmy` run logs off the watch over USB-C.
  * Cleans urban-canyon and tree-cover GPS bounce using a 2-pass **Kalman smoother** and smooths noisy GPS elevation.
  * Computes kilometer splits, **Grade-Adjusted Pace (`GAP`)**, cardiac drift (`Pa:Hr`), and chest-strap **HRV (`RMSSD` / `SDNN`)** into a local SQLite database.
  * Exports standard binary **Garmin `.FIT`** and **`.GPX`** files and uploads directly to **Strava**.

---

## Repository Structure

| Folder | Purpose |
| :--- | :--- |
| [`gummybear/`](./gummybear) | Python telemetry pipeline: binary decoder, Kalman smoother, GAP/HRV metrics, SQLite storage, `.FIT`/`.GPX` exporters, USB watch sync, and Strava uploader |
| [`firmware/`](./firmware) | Embedded C/C++ watch firmware for the `Seeed Studio XIAO nRF52840` (`GM10` GPS parser, Garmin `0x180D` BLE HR client, `nice!view` screen, and flash logger) |
| [`cad/`](./cad) | 3D-printable inner switch/screen cradle and custom backplate models for the Casio W-218H |
| [`tests/`](./tests) | End-to-end Python & C firmware header verification suite |
| [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) | Human-readable build guide, parts list, wiring table, and step-by-step roadmap |

---

## Quickstart (Zero Dependencies — Python 3.9+ Stdlib)

You can test the entire data pipeline locally using a simulated hilly San Francisco run before touching any hardware:

```bash
# 1. Generate a noisy 1 Hz binary watch log (.gmy) simulating a hilly SF loop
#    (Pacific Heights -> Marina Green -> Crissy Field & back, with urban GPS noise + Garmin HR)
python3 -m gummybear simulate -o data/raw/sf_marina_sim.gmy

# 2. Ingest, smooth GPS track, store in SQLite, & export .FIT + .GPX
python3 -m gummybear ingest data/raw/sf_marina_sim.gmy

# 3. View stored runs in the local database
python3 -m gummybear runs

# 4. Run the test suite
python3 -m unittest discover -s tests -v
```

## Syncing & Uploading to Strava

1. Create an API application at https://www.strava.com/settings/api (set **Authorization Callback Domain** to `localhost`).
2. Run the one-time browser login:
   ```bash
   python3 -m gummybear strava-auth --client-id YOUR_ID --client-secret YOUR_SECRET
   ```
3. Upload any stored run (uses Strava's native time-of-day title by default):
   ```bash
   python3 -m gummybear upload 1
   ```
4. Once the watch hardware is flashed, pull all new runs over USB-C and upload in one step:
   ```bash
   pip install pyserial
   python3 -m gummybear sync --upload
   ```
