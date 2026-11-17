from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class RawSample:
    """Unpacked 1 Hz telemetry sample directly from the Casio W-218H binary log."""

    unix_ts: int
    lat: float
    lon: float
    alt_m: float
    hdop: float
    sat_count: int
    paused: bool
    hr_valid: bool
    hr_bpm: Optional[int]
    rr_ms: Optional[int]


@dataclass(frozen=True)
class CleanSample:
    """Kalman-smoothed & terrain-corrected sample with derived kinematics."""

    unix_ts: int
    lat: float
    lon: float
    alt_m: float
    cum_dist_m: float
    speed_mps: float
    grade: float  # fractional slope, e.g. 0.05 = +5%
    gap_speed_mps: float  # Minetti Grade-Adjusted flat-equivalent speed
    paused: bool
    hr_bpm: Optional[int]
    rr_ms: Optional[int]
    has_gps: bool = True


@dataclass(frozen=True)
class Split:
    """1-kilometer split summary."""

    km_index: int
    distance_m: float
    duration_s: float
    pace_sec_per_km: float
    gap_sec_per_km: float
    elev_gain_m: float
    elev_loss_m: float
    avg_hr_bpm: Optional[float]


@dataclass
class HrvMetrics:
    """Heart Rate Variability metrics computed from Garmin chest-strap R-R intervals."""

    valid_rr_count: int
    rejected_rr_count: int
    mean_rr_ms: Optional[float]
    sdnn_ms: Optional[float]
    rmssd_ms: Optional[float]


@dataclass
class RunSummary:
    """Complete processed run summary and derived physiological analytics."""

    source_sha256: str
    start_ts: int
    end_ts: int
    elapsed_time_s: int
    moving_time_s: int
    total_distance_m: float
    elev_gain_m: float
    elev_loss_m: float
    avg_pace_sec_per_km: float
    avg_gap_sec_per_km: float
    avg_hr_bpm: Optional[float]
    max_hr_bpm: Optional[int]
    aerobic_decoupling_pct: Optional[float]
    hrv: HrvMetrics
    start_batt_mv: int
    splits: List[Split] = field(default_factory=list)
