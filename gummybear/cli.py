"""Command-line interface for the Gummybear Casio W-218H pipeline."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from gummybear.binary import encode_gmy, read_gmy_file
from gummybear.export_fit import write_fit_file
from gummybear.export_gpx import write_gpx_file
from gummybear.kalman import clean_trajectory
from gummybear.metrics import format_pace, summarize_run
from gummybear.models import HrvMetrics, RunSummary, Split
from gummybear.simulator import generate_synthetic_sf_run
from gummybear.storage import RunWarehouse
from gummybear.sync import pull_runs_over_usb_serial, run_step1_bench_hr_session
from gummybear.strava import (
    DEFAULT_TOKEN_PATH,
    authorize_interactive,
    upload_activity_to_strava,
)

DEFAULT_DATA_DIR = Path("data")
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "gummybear.db"


def _fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"


def _print_summary(run_id: int, summary: RunSummary, created_new: bool, fit_path: Path, gpx_path: Path) -> None:
    dt_str = datetime.fromtimestamp(summary.start_ts).strftime("%Y-%m-%d %H:%M")
    status_tag = "NEW" if created_new else "DEDUPLICATED (already in DB)"
    print(f"\n=== Run #{run_id} [{status_tag}] — {dt_str} ===")
    print(f"  Distance      : {summary.total_distance_m / 1000.0:.2f} km")
    print(f"  Moving Time   : {_fmt_duration(summary.moving_time_s)} (Elapsed {_fmt_duration(summary.elapsed_time_s)})")
    print(f"  Avg Pace      : {format_pace(summary.avg_pace_sec_per_km)}")
    print(f"  Grade-Adj GAP : {format_pace(summary.avg_gap_sec_per_km)}")
    print(f"  Elevation     : +{summary.elev_gain_m:.0f} m / -{summary.elev_loss_m:.0f} m")
    if summary.avg_hr_bpm is not None:
        print(f"  Heart Rate    : {summary.avg_hr_bpm:.0f} bpm avg / {summary.max_hr_bpm} bpm max")
    if summary.aerobic_decoupling_pct is not None:
        print(f"  Pa:Hr Drift   : {summary.aerobic_decoupling_pct:+.2f}% (1st vs 2nd half)")
    if summary.hrv.rmssd_ms is not None:
        print(
            f"  Strap R-R HRV : RMSSD {summary.hrv.rmssd_ms:.1f} ms | "
            f"SDNN {summary.hrv.sdnn_ms:.1f} ms ({summary.hrv.valid_rr_count} beats)"
        )
    print(f"  Watch Battery : {summary.start_batt_mv / 1000.0:.2f} V at start")
    print(f"  Exports       : {fit_path}  |  {gpx_path}")

    if summary.splits:
        print("\n  KM Splits:")
        print("  KM   Dist     Pace        GAP         Elev        Avg HR")
        print("  --------------------------------------------------------")
        for sp in summary.splits:
            hr_col = f"{sp.avg_hr_bpm:.0f} bpm" if sp.avg_hr_bpm else "---"
            print(
                f"  {sp.km_index:>2d}   {sp.distance_m / 1000.0:>4.2f}km   "
                f"{format_pace(sp.pace_sec_per_km):<10s}  "
                f"{format_pace(sp.gap_sec_per_km):<10s}  "
                f"+{sp.elev_gain_m:>3.0f}/-{sp.elev_loss_m:<3.0f}m  {hr_col}"
            )


def cmd_simulate(args: argparse.Namespace) -> int:
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    samples, _ = generate_synthetic_sf_run(seed=args.seed)
    blob = encode_gmy(samples, start_batt_mv=4120)
    out_path.write_bytes(blob)
    print(
        f"Wrote synthetic SF run ({len(samples)} 1Hz samples, {len(blob) / 1024:.1f} KB) -> {out_path}"
    )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    gmy_path = Path(args.file)
    raw_bytes = gmy_path.read_bytes()
    header, raw_samples, dropped = read_gmy_file(gmy_path)
    if dropped:
        print(f"Note: salvaged stream after dropping {dropped} corrupt/partial frame(s).")

    cleaned = clean_trajectory(raw_samples)
    summary = summarize_run(cleaned, raw_bytes=raw_bytes, start_batt_mv=header.start_batt_mv)

    db = RunWarehouse(Path(args.db))
    exports_dir = Path(args.db).parent / "exports"
    stem = f"run_{summary.start_ts}_{summary.source_sha256[:8]}"
    fit_path = exports_dir / f"{stem}.fit"
    gpx_path = exports_dir / f"{stem}.gpx"

    write_fit_file(fit_path, cleaned, summary)
    write_gpx_file(gpx_path, cleaned, name=args.name)

    run_id, created_new = db.store_run(
        summary=summary,
        raw_samples=raw_samples,
        clean_samples=cleaned,
        raw_file_path=str(gmy_path),
        fit_path=str(fit_path),
        gpx_path=str(gpx_path),
    )
    _print_summary(run_id, summary, created_new, fit_path, gpx_path)
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    db = RunWarehouse(Path(args.db))
    rows = db.list_runs()
    if not rows:
        print("No runs stored yet. Try `python3 -m gummybear simulate` then `ingest`!")
        return 0

    print("ID   Date              Dist     Moving    Pace        GAP         AvgHR  Strava")
    print("-------------------------------------------------------------------------------")
    for r in rows:
        dt = datetime.fromtimestamp(int(r["start_ts"])).strftime("%Y-%m-%d %H:%M")
        dist_km = float(r["total_distance_m"]) / 1000.0
        mov = _fmt_duration(float(r["moving_time_s"]))
        pace = format_pace(float(r["avg_pace_sec_per_km"]))
        gap = format_pace(float(r["avg_gap_sec_per_km"]))
        hr = f"{float(r['avg_hr_bpm']):.0f}" if r["avg_hr_bpm"] is not None else "---"
        strava = (
            f"https://www.strava.com/activities/{r['strava_activity_id']}"
            if r["strava_activity_id"]
            else (str(r["strava_status"]) if r["strava_status"] else "local")
        )
        print(
            f"{int(r['id']):>2d}   {dt}  {dist_km:>5.2f}km  {mov:>8s}  {pace:<10s}  {gap:<10s}  {hr:>5s}  {strava}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    db = RunWarehouse(Path(args.db))
    row = db.get_run(args.run_id)
    if not row:
        print(f"Run #{args.run_id} not found in {args.db}")
        return 1

    splits_raw = json.loads(str(row["splits_json"]))
    splits = [Split(**sp) for sp in splits_raw]
    hrv = HrvMetrics(
        valid_rr_count=int(row["hrv_valid_rr_count"]),
        rejected_rr_count=0,
        mean_rr_ms=None,
        sdnn_ms=float(row["hrv_sdnn_ms"]) if row["hrv_sdnn_ms"] is not None else None,
        rmssd_ms=float(row["hrv_rmssd_ms"]) if row["hrv_rmssd_ms"] is not None else None,
    )
    summary = RunSummary(
        source_sha256=str(row["source_sha256"]),
        start_ts=int(row["start_ts"]),
        end_ts=int(row["end_ts"]),
        elapsed_time_s=int(row["elapsed_time_s"]),
        moving_time_s=int(row["moving_time_s"]),
        total_distance_m=float(row["total_distance_m"]),
        elev_gain_m=float(row["elev_gain_m"]),
        elev_loss_m=float(row["elev_loss_m"]),
        avg_pace_sec_per_km=float(row["avg_pace_sec_per_km"]),
        avg_gap_sec_per_km=float(row["avg_gap_sec_per_km"]),
        avg_hr_bpm=float(row["avg_hr_bpm"]) if row["avg_hr_bpm"] is not None else None,
        max_hr_bpm=int(row["max_hr_bpm"]) if row["max_hr_bpm"] is not None else None,
        aerobic_decoupling_pct=(
            float(row["aerobic_decoupling_pct"])
            if row["aerobic_decoupling_pct"] is not None
            else None
        ),
        hrv=hrv,
        start_batt_mv=int(row["start_batt_mv"]),
        splits=splits,
    )
    _print_summary(
        int(row["id"]),
        summary,
        created_new=True,
        fit_path=Path(str(row["fit_path"] or "")),
        gpx_path=Path(str(row["gpx_path"] or "")),
    )
    return 0


def cmd_strava_auth(args: argparse.Namespace) -> int:
    saved = authorize_interactive(
        client_id=args.client_id,
        client_secret=args.client_secret,
        port=args.port,
        token_path=Path(args.token_file),
    )
    print(f"Saved Strava OAuth2 credentials to {saved}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    db = RunWarehouse(Path(args.db))
    row = db.get_run(args.run_id)
    if not row:
        print(f"Run #{args.run_id} not found in {args.db}")
        return 1

    upload_file = Path(str(row["fit_path"] if args.format == "fit" else row["gpx_path"]))
    if not upload_file.exists():
        print(f"Export file missing at {upload_file}")
        return 1

    res = upload_activity_to_strava(
        activity_file=upload_file,
        name=args.name,
        description=args.description,
        external_id=f"gummybear_{str(row['source_sha256'])[:16]}",
        token_path=Path(args.token_file),
    )
    db.record_strava_upload(
        run_id=args.run_id,
        upload_id=res.upload_id,
        activity_id=res.activity_id,
        status=res.error or res.status,
    )
    if res.error:
        print(f"Strava upload error: {res.error}")
        return 1
    if res.activity_id:
        print(f"Uploaded to Strava: https://www.strava.com/activities/{res.activity_id}")
    else:
        print(f"Queued on Strava (upload_id={res.upload_id}, status={res.status})")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    raw_dir = Path(args.db).parent / "raw"
    pulled = pull_runs_over_usb_serial(
        output_dir=raw_dir,
        port=args.port,
        delete_after_verify=not args.keep_on_watch,
    )
    if not pulled:
        print("Watch connected — no new runs on flash.")
        return 0

    for gmy_path in pulled:
        ingest_ns = argparse.Namespace(
            db=args.db, file=str(gmy_path), name="Casio W-218H Run"
        )
        cmd_ingest(ingest_ns)
        if args.upload:
            db = RunWarehouse(Path(args.db))
            runs = db.list_runs()
            if runs:
                latest_id = int(runs[0]["id"])
                up_ns = argparse.Namespace(
                    db=args.db,
                    run_id=latest_id,
                    name=None,
                    description=None,
                    format="fit",
                    token_file=args.token_file,
                )
                cmd_upload(up_ns)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    raw_dir = Path(args.db).parent / "raw"
    pulled = run_step1_bench_hr_session(
        output_dir=raw_dir,
        duration_s=args.seconds,
        port=args.port,
    )
    for gmy_path in pulled:
        ingest_ns = argparse.Namespace(
            db=args.db, file=str(gmy_path), name="Indoor HR Bench Test"
        )
        cmd_ingest(ingest_ns)
        if args.upload:
            db = RunWarehouse(Path(args.db))
            runs = db.list_runs()
            if runs:
                latest_id = int(runs[0]["id"])
                up_ns = argparse.Namespace(
                    db=args.db,
                    run_id=latest_id,
                    name=None,
                    description=None,
                    format="fit",
                    token_file=args.token_file,
                )
                cmd_upload(up_ns)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gummybear",
        description="Sleeper Casio W-218H GPS + BLE HR telemetry pipeline & Strava uploader",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to local SQLite warehouse")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sim = sub.add_parser("simulate", help="Generate a synthetic noisy SF hill + waterfront `.gmy` run")
    p_sim.add_argument("-o", "--output", default="data/raw/sf_marina_sim.gmy")
    p_sim.add_argument("--seed", type=int, default=42)
    p_sim.set_defaults(func=cmd_simulate)

    p_ing = sub.add_parser("ingest", help="Unpack `.gmy`, run RTS Kalman smoother, store in DB & export .fit/.gpx")
    p_ing.add_argument("file", help="Path to binary `.gmy` watch log")
    p_ing.add_argument("--name", default="Casio W-218H Run", help="Activity title for GPX/Strava")
    p_ing.set_defaults(func=cmd_ingest)

    p_runs = sub.add_parser("runs", help="List ingested runs in the local warehouse")
    p_runs.set_defaults(func=cmd_runs)

    p_show = sub.add_parser("show", help="Show full local splits, GAP, Pa:Hr drift, and HRV for a run")
    p_show.add_argument("run_id", type=int)
    p_show.set_defaults(func=cmd_show)

    p_auth = sub.add_parser("strava-auth", help="One-time OAuth2 setup with your Strava API app")
    p_auth.add_argument("--client-id", required=True)
    p_auth.add_argument("--client-secret", required=True)
    p_auth.add_argument("--port", type=int, default=8765)
    p_auth.add_argument("--token-file", default=str(DEFAULT_TOKEN_PATH))
    p_auth.set_defaults(func=cmd_strava_auth)

    p_up = sub.add_parser("upload", help="Upload a stored run to Strava (.fit default)")
    p_up.add_argument("run_id", type=int)
    p_up.add_argument("--name", default=None, help="Optional title (if omitted, Strava uses Morning/Afternoon/Evening Run)")
    p_up.add_argument("--description", default=None, help="Optional Strava description (blank by default)")
    p_up.add_argument("--format", choices=["fit", "gpx"], default="fit")
    p_up.add_argument("--token-file", default=str(DEFAULT_TOKEN_PATH))
    p_up.set_defaults(func=cmd_upload)

    p_sync = sub.add_parser("sync", help="Pull `.gmy` runs from USB-connected watch, ingest, and optionally upload")
    p_sync.add_argument("--port", default=None, help="Serial port (auto-detects /dev/cu.usbmodem* if omitted)")
    p_sync.add_argument("--keep-on-watch", action="store_true", help="Do not delete synced files from watch flash")
    p_sync.add_argument("--upload", action="store_true", help="Automatically upload newly synced runs to Strava")
    p_sync.add_argument("--token-file", default=str(DEFAULT_TOKEN_PATH))
    p_sync.set_defaults(func=cmd_sync)

    p_bench = sub.add_parser(
        "bench",
        help="Prototype Step #1: record live Bluetooth HR onto USB-connected XIAO #1 (no buttons/GPS needed)",
    )
    p_bench.add_argument("--seconds", type=int, default=30, help="Recording duration in seconds")
    p_bench.add_argument("--port", default=None, help="Serial port (auto-detects /dev/cu.usbmodem* if omitted)")
    p_bench.add_argument("--upload", action="store_true", help="Automatically upload the recorded HR test to Strava")
    p_bench.add_argument("--token-file", default=str(DEFAULT_TOKEN_PATH))
    p_bench.set_defaults(func=cmd_bench)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
