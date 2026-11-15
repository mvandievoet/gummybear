# Gummybear

DIY "Sleeper" **Casio W-218H** standalone GPS + Bluetooth Heart Rate running watch firmware & macOS telemetry pipeline.

See [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) for the complete hardware bill of materials, wiring map, mechanical Z-stackup, and phased roadmap.

## Quickstart (Zero Dependencies — Python 3.9+ Stdlib)

```bash
# 1. Generate a noisy 1 Hz binary watch log (.gmy) simulating a hilly SF loop
#    (Pacific Heights -> Marina Green -> Crissy Field & back, with urban multipath + Garmin HR/R-R)
python3 -m gummybear simulate -o data/raw/sf_marina_sim.gmy

# 2. Ingest, run 2D HDOP-weighted RTS Kalman smoother, store in SQLite, & export .FIT + .GPX
python3 -m gummybear ingest data/raw/sf_marina_sim.gmy --name "Morning Marina Loop"

# 3. View stored runs in local warehouse
python3 -m gummybear runs

# 4. Run the test suite
python3 -m unittest discover -s tests -v
```

## Uploading to Strava

1. Create a personal API application at https://www.strava.com/settings/api (set **Authorization Callback Domain** to `localhost`).
2. Run one-time browser authorization:
   ```bash
   python3 -m gummybear strava-auth --client-id YOUR_ID --client-secret YOUR_SECRET
   ```
3. Push any ingested run (uploads compact binary `.fit` by default):
   ```bash
   python3 -m gummybear upload 1 --name "Morning Run (Casio W-218H)"
   ```
