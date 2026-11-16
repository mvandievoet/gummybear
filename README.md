# Gummybear

A personal hardware + data side project turning an everyday **$20 Casio W-218H** digital watch into a standalone **GPS + Heart Rate running watch** that syncs directly to **Strava**—for a fraction of the cost of a dedicated GPS sportswatch.

## Why Build This?

Most GPS running watches ($250–$500+) look and feel like bulky smartwatches, while classic digital Casios are light, simple, and comfortable to wear all day. Even across Casio's own connected G-Shock fitness lineup, none of the classic square models include built-in GPS (requiring you to run with your phone), and none of Casio's watches at any price allow pairing an external Bluetooth/ANT+ chest heart-rate strap.

More importantly, building one from scratch—from wiring the sensors inside the Casio shell to writing the GPS/heart-rate smoothing pipeline—sounded like a really fun side project.

**Gummybear** keeps the compact outer case, side buttons, and sunlight-readable digital look of a **Casio W-218H** (~`42 g`, ~`$65` in parts), while replacing its internals with a tiny Bluetooth microcontroller, a low-power GPS receiver, and a rechargeable battery.

### What It Does
* **Everyday Watch Mode:** Displays local time and date with **automatic Daylight Saving Time**, quick travel timezone switching, battery status, and multi-week standby battery life.
* **Standalone Run Tracking (Up to Ultramarathon Distances):**
  * Locks onto GPS satellites directly on the watch (no phone needed).
  * Pairs over Bluetooth (`BLE`) with **any standard Bluetooth heart-rate strap or armband** to show live BPM on your wrist and log raw millisecond beat-to-beat (`R-R`) intervals.
  * Shows a single, distraction-free run screen (`Pace`, `Distance`, `Live HR`, `Elapsed Time`) with Start, Pause/Resume, Save, and Hold-to-Delete controls.
  * Stores **~28+ hours** of 1-second GPS + HR data across dozens of separate runs in onboard flash memory (~20+ hours of continuous GPS battery life per charge).
* **Clean Strava Uploads + Private Local Analytics:**
  * Pulls compact raw binary run logs off the watch over USB-C, smooths urban-canyon GPS bounce with a 2-pass **Kalman filter**, and uploads a clean, native **Garmin `.FIT`** activity straight to **Strava**.
  * Simultaneously saves advanced metrics that free Strava hides or doesn't track—**Grade-Adjusted Pace (`GAP`)**, **cardiac drift (`Pa:Hr`)**, and **beat-to-beat HRV (`RMSSD` / `SDNN`)**—into a local SQLite database (`data/gummybear.db`) that you own and can query anytime.

---

## Repository Structure

| Folder | Purpose |
| :--- | :--- |
| [`gummybear/`](./gummybear) | Python telemetry pipeline: binary log decoder, Kalman smoother, GAP/HRV metrics, SQLite warehouse, `.FIT`/`.GPX` exporters, USB watch sync, and Strava uploader |
| [`firmware/`](./firmware) | Embedded C/C++ watch firmware for the `Seeed Studio XIAO nRF52840` (GPS parser, `0x180D` BLE heart-rate client, `nice!view` screen, and flash logger) |
| [`cad/`](./cad) | 3D-printable inner switch/screen cradle and custom backplate models for the Casio W-218H |
| [`tests/`](./tests) | End-to-end Python & C firmware verification suite |
| [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) | Human-readable build guide, parts list, wiring table, and step-by-step roadmap |

---

## Quickstart (Zero Dependencies — Python 3.9+ Stdlib)

You can test the entire data pipeline locally using a simulated hilly run before touching any hardware:

```bash
# 1. Generate a noisy 1 Hz binary watch log simulating a hilly loop
python3 -m gummybear simulate -o data/raw/sf_marina_sim.gmy

# 2. Ingest, smooth GPS track, store in SQLite, & export .FIT + .GPX
python3 -m gummybear ingest data/raw/sf_marina_sim.gmy

# 3. List all runs or pull up full local GAP / cardiac drift / HRV details for a run
python3 -m gummybear runs
python3 -m gummybear show 1

# 4. Run the test suite
python3 -m unittest discover -s tests -v
```

## Syncing & Uploading to Strava

1. Create an API application at https://www.strava.com/settings/api (set **Authorization Callback Domain** to `localhost`).
2. Run the one-time browser login:
   ```bash
   python3 -m gummybear strava-auth --client-id YOUR_ID --client-secret YOUR_SECRET
   ```
3. Upload any stored run (uses Strava's native time-of-day title with a clean blank description by default):
   ```bash
   python3 -m gummybear upload 1
   ```
4. Once the watch hardware is flashed, pull all new runs over USB-C, save local analytics, and upload to Strava in one step:
   ```bash
   pip install pyserial
   python3 -m gummybear sync --upload
   ```
