"""Local relational telemetry warehouse (SQLite stdlib default, optional DuckDB export)."""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from gummybear.models import CleanSample, RawSample, RunSummary

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sha256 TEXT NOT NULL UNIQUE,
    raw_file_path TEXT,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    elapsed_time_s INTEGER NOT NULL,
    moving_time_s INTEGER NOT NULL,
    total_distance_m REAL NOT NULL,
    elev_gain_m REAL NOT NULL,
    elev_loss_m REAL NOT NULL,
    avg_pace_sec_per_km REAL NOT NULL,
    avg_gap_sec_per_km REAL NOT NULL,
    avg_hr_bpm REAL,
    max_hr_bpm INTEGER,
    aerobic_decoupling_pct REAL,
    hrv_valid_rr_count INTEGER NOT NULL,
    hrv_rmssd_ms REAL,
    hrv_sdnn_ms REAL,
    start_batt_mv INTEGER NOT NULL,
    splits_json TEXT NOT NULL,
    fit_path TEXT,
    gpx_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS samples_raw (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    unix_ts INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    alt_m REAL NOT NULL,
    hdop REAL NOT NULL,
    sat_count INTEGER NOT NULL,
    paused INTEGER NOT NULL,
    hr_bpm INTEGER,
    rr_ms INTEGER,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS samples_clean (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    unix_ts INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    alt_m REAL NOT NULL,
    cum_dist_m REAL NOT NULL,
    speed_mps REAL NOT NULL,
    grade REAL NOT NULL,
    gap_speed_mps REAL NOT NULL,
    paused INTEGER NOT NULL,
    hr_bpm INTEGER,
    rr_ms INTEGER,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS strava_uploads (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    upload_id INTEGER NOT NULL,
    activity_id INTEGER,
    status TEXT NOT NULL,
    uploaded_at TEXT DEFAULT (datetime('now'))
);
"""


class RunWarehouse:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def find_run_by_sha256(self, sha256: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM runs WHERE source_sha256 = ?", (sha256,)
            ).fetchone()
            return int(row["id"]) if row else None

    def store_run(
        self,
        summary: RunSummary,
        raw_samples: Sequence[RawSample],
        clean_samples: Sequence[CleanSample],
        raw_file_path: Optional[str] = None,
        fit_path: Optional[str] = None,
        gpx_path: Optional[str] = None,
    ) -> Tuple[int, bool]:
        """Persist run and telemetry streams idempotently.

        Returns `(run_id, created_new)` where `created_new=False` if already ingested.
        """
        existing = self.find_run_by_sha256(summary.source_sha256)
        if existing is not None:
            return existing, False

        splits_payload = [
            {
                "km_index": sp.km_index,
                "distance_m": sp.distance_m,
                "duration_s": sp.duration_s,
                "pace_sec_per_km": sp.pace_sec_per_km,
                "gap_sec_per_km": sp.gap_sec_per_km,
                "elev_gain_m": sp.elev_gain_m,
                "elev_loss_m": sp.elev_loss_m,
                "avg_hr_bpm": sp.avg_hr_bpm,
            }
            for sp in summary.splits
        ]

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (
                    source_sha256, raw_file_path, start_ts, end_ts,
                    elapsed_time_s, moving_time_s, total_distance_m,
                    elev_gain_m, elev_loss_m, avg_pace_sec_per_km, avg_gap_sec_per_km,
                    avg_hr_bpm, max_hr_bpm, aerobic_decoupling_pct,
                    hrv_valid_rr_count, hrv_rmssd_ms, hrv_sdnn_ms,
                    start_batt_mv, splits_json, fit_path, gpx_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.source_sha256,
                    raw_file_path,
                    summary.start_ts,
                    summary.end_ts,
                    summary.elapsed_time_s,
                    summary.moving_time_s,
                    summary.total_distance_m,
                    summary.elev_gain_m,
                    summary.elev_loss_m,
                    summary.avg_pace_sec_per_km,
                    summary.avg_gap_sec_per_km,
                    summary.avg_hr_bpm,
                    summary.max_hr_bpm,
                    summary.aerobic_decoupling_pct,
                    summary.hrv.valid_rr_count,
                    summary.hrv.rmssd_ms,
                    summary.hrv.sdnn_ms,
                    summary.start_batt_mv,
                    json.dumps(splits_payload),
                    fit_path,
                    gpx_path,
                ),
            )
            run_id = int(cur.lastrowid)

            conn.executemany(
                """
                INSERT INTO samples_raw (
                    run_id, seq, unix_ts, lat, lon, alt_m, hdop, sat_count, paused, hr_bpm, rr_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        idx,
                        s.unix_ts,
                        s.lat,
                        s.lon,
                        s.alt_m,
                        s.hdop,
                        s.sat_count,
                        1 if s.paused else 0,
                        s.hr_bpm,
                        s.rr_ms,
                    )
                    for idx, s in enumerate(raw_samples)
                ],
            )

            conn.executemany(
                """
                INSERT INTO samples_clean (
                    run_id, seq, unix_ts, lat, lon, alt_m, cum_dist_m,
                    speed_mps, grade, gap_speed_mps, paused, hr_bpm, rr_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        idx,
                        s.unix_ts,
                        s.lat,
                        s.lon,
                        s.alt_m,
                        s.cum_dist_m,
                        s.speed_mps,
                        s.grade,
                        s.gap_speed_mps,
                        1 if s.paused else 0,
                        s.hr_bpm,
                        s.rr_ms,
                    )
                    for idx, s in enumerate(clean_samples)
                ],
            )

        return run_id, True

    def update_export_paths(
        self, run_id: int, fit_path: Optional[str], gpx_path: Optional[str]
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET fit_path = ?, gpx_path = ? WHERE id = ?",
                (fit_path, gpx_path, run_id),
            )

    def record_strava_upload(
        self, run_id: int, upload_id: int, activity_id: Optional[int], status: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO strava_uploads (run_id, upload_id, activity_id, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    upload_id = excluded.upload_id,
                    activity_id = excluded.activity_id,
                    status = excluded.status
                """,
                (run_id, upload_id, activity_id, status),
            )

    def list_runs(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*, u.activity_id AS strava_activity_id, u.status AS strava_status
                FROM runs r
                LEFT JOIN strava_uploads u ON u.run_id = r.id
                ORDER BY r.start_ts DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: int) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT r.*, u.activity_id AS strava_activity_id, u.status AS strava_status
                FROM runs r
                LEFT JOIN strava_uploads u ON u.run_id = r.id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row else None
