"""Physiological & kinematic run analytics: Minetti GAP, splits, Pa:Hr decoupling, and R-R HRV."""

import hashlib
import math
from typing import List, Optional, Sequence, Tuple

from gummybear.models import CleanSample, HrvMetrics, RunSummary, Split

EARTH_RADIUS_M = 6_371_000.0
FLAT_COST_J_PER_KG_M = 3.6  # Minetti et al. (2002) flat running metabolic cost


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two WGS84 coordinates."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def minetti_cost_ratio(grade: float) -> float:
    """Minetti et al. (2002) metabolic energy cost ratio relative to flat running.

    `grade` is fractional slope `i = rise / run` (clamped to [-0.45, +0.45]).
    """
    i = max(-0.45, min(0.45, grade))
    cost = (
        155.4 * (i ** 5)
        - 30.4 * (i ** 4)
        - 43.3 * (i ** 3)
        + 46.3 * (i ** 2)
        + 19.5 * i
        + FLAT_COST_J_PER_KG_M
    )
    return max(0.45, cost / FLAT_COST_J_PER_KG_M)


def grade_adjusted_speed_mps(speed_mps: float, grade: float) -> float:
    """Convert actual ground speed and fractional slope into flat-equivalent GAP speed."""
    if speed_mps <= 0.0:
        return 0.0
    return speed_mps * minetti_cost_ratio(grade)


def compute_elevation_gain_loss(
    altitudes_m: Sequence[float], hysteresis_m: float = 3.0
) -> Tuple[float, float]:
    """Compute cumulative ascent and descent using deadband hysteresis to ignore micro-ripple."""
    if not altitudes_m:
        return 0.0, 0.0
    gain = 0.0
    loss = 0.0
    anchor = altitudes_m[0]
    for alt in altitudes_m[1:]:
        diff = alt - anchor
        if diff >= hysteresis_m:
            gain += diff
            anchor = alt
        elif diff <= -hysteresis_m:
            loss += -diff
            anchor = alt
    return round(gain, 1), round(loss, 1)


def compute_hrv_from_rr(rr_values_ms: Sequence[Optional[int]]) -> HrvMetrics:
    """Filter ectopic/missed chest-strap beats (Malik 20% rule) and compute SDNN & RMSSD."""
    raw_rr = [r for r in rr_values_ms if r is not None and r > 0]
    if not raw_rr:
        return HrvMetrics(0, 0, None, None, None)

    # Deduplicate consecutive identical R-R values repeated across 1 Hz frames when HR < 60
    # or keep genuine beat transitions + physiologically plausible [260ms..2000ms] window.
    plausible: List[int] = []
    rejected = 0
    for r in raw_rr:
        if 260 <= r <= 2000:
            if not plausible or r != plausible[-1] or len(plausible) == 0:
                if plausible and abs(r - plausible[-1]) / plausible[-1] > 0.22:
                    rejected += 1
                    continue
                plausible.append(r)
        else:
            rejected += 1

    n = len(plausible)
    if n < 3:
        return HrvMetrics(n, rejected, None, None, None)

    mean_rr = sum(plausible) / n
    variance = sum((x - mean_rr) ** 2 for x in plausible) / (n - 1)
    sdnn = math.sqrt(variance)

    diffs_sq = [(plausible[i] - plausible[i - 1]) ** 2 for i in range(1, n)]
    rmssd = math.sqrt(sum(diffs_sq) / len(diffs_sq))

    return HrvMetrics(
        valid_rr_count=n,
        rejected_rr_count=rejected,
        mean_rr_ms=round(mean_rr, 1),
        sdnn_ms=round(sdnn, 2),
        rmssd_ms=round(rmssd, 2),
    )


def compute_aerobic_decoupling_pct(samples: Sequence[CleanSample]) -> Optional[float]:
    """Compute cardiac drift / aerobic decoupling (`Pa:Hr` %) between 1st and 2nd halves.

    Efficiency Factor `EF = gap_speed_mps / hr_bpm`. Positive % means HR drifted upward
    for the same grade-adjusted pace in the second half (key ultra endurance metric).
    """
    moving = [
        s
        for s in samples
        if not s.paused and s.gap_speed_mps > 1.2 and s.hr_bpm is not None and s.hr_bpm >= 80
    ]
    if len(moving) < 120:  # Require at least 2 minutes of moving HR data
        return None

    mid = len(moving) // 2
    first = moving[:mid]
    second = moving[mid:]

    ef1 = (sum(s.gap_speed_mps for s in first) / len(first)) / (
        sum(s.hr_bpm for s in first if s.hr_bpm) / len(first)
    )
    ef2 = (sum(s.gap_speed_mps for s in second) / len(second)) / (
        sum(s.hr_bpm for s in second if s.hr_bpm) / len(second)
    )
    if ef1 <= 0:
        return None
    return round(((ef1 - ef2) / ef1) * 100.0, 2)


def compute_km_splits(samples: Sequence[CleanSample]) -> List[Split]:
    """Slice a cleaned trajectory into 1,000-meter splits (plus final partial split >= 100m)."""
    if len(samples) < 2:
        return []

    splits: List[Split] = []
    split_idx = 1
    next_boundary_m = 1000.0
    seg_start_idx = 0

    for i in range(1, len(samples)):
        is_last = i == len(samples) - 1
        reached_km = samples[i].cum_dist_m >= next_boundary_m
        if not reached_km and not is_last:
            continue

        seg = samples[seg_start_idx : i + 1]
        dist_m = seg[-1].cum_dist_m - seg[0].cum_dist_m
        if is_last and not reached_km and dist_m < 100.0:
            break

        moving_dt = 0.0
        gap_equiv_dist = 0.0
        hrs: List[int] = []
        for j in range(1, len(seg)):
            if not seg[j].paused and not seg[j - 1].paused:
                dt = max(1, seg[j].unix_ts - seg[j - 1].unix_ts)
                moving_dt += dt
                gap_equiv_dist += seg[j].gap_speed_mps * dt
            if seg[j].hr_bpm is not None:
                hrs.append(seg[j].hr_bpm)

        if dist_m > 0 and moving_dt > 0:
            pace_s_km = (moving_dt / dist_m) * 1000.0
            gap_s_km = (moving_dt / max(1.0, gap_equiv_dist)) * 1000.0
            gain_m, loss_m = compute_elevation_gain_loss(
                [p.alt_m for p in seg], hysteresis_m=2.5
            )
            avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None
            splits.append(
                Split(
                    km_index=split_idx,
                    distance_m=round(dist_m, 1),
                    duration_s=round(moving_dt, 1),
                    pace_sec_per_km=round(pace_s_km, 1),
                    gap_sec_per_km=round(gap_s_km, 1),
                    elev_gain_m=gain_m,
                    elev_loss_m=loss_m,
                    avg_hr_bpm=avg_hr,
                )
            )

        if reached_km:
            split_idx += 1
            next_boundary_m += 1000.0
            seg_start_idx = i

    return splits


def summarize_run(
    samples: Sequence[CleanSample],
    raw_bytes: bytes,
    start_batt_mv: int = 4150,
) -> RunSummary:
    """Compute complete `RunSummary` from cleaned samples and original raw bytes."""
    if not samples:
        raise ValueError("Cannot summarize empty sample list")

    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    start_ts = samples[0].unix_ts
    end_ts = samples[-1].unix_ts
    elapsed_s = max(1, end_ts - start_ts)

    moving_s = 0
    gap_dist_m = 0.0
    for i in range(1, len(samples)):
        if not samples[i].paused and not samples[i - 1].paused and samples[i].speed_mps > 0:
            dt = max(1, samples[i].unix_ts - samples[i - 1].unix_ts)
            moving_s += dt
            gap_dist_m += samples[i].gap_speed_mps * dt

    moving_s = max(1, moving_s)
    total_dist_m = samples[-1].cum_dist_m
    elev_gain, elev_loss = compute_elevation_gain_loss([s.alt_m for s in samples])

    avg_pace = (moving_s / total_dist_m) * 1000.0 if total_dist_m > 0 else 0.0
    avg_gap = (moving_s / gap_dist_m) * 1000.0 if gap_dist_m > 0 else 0.0

    hrs = [s.hr_bpm for s in samples if s.hr_bpm is not None and s.hr_bpm > 0]
    avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None
    max_hr = max(hrs) if hrs else None

    hrv = compute_hrv_from_rr([s.rr_ms for s in samples])
    decoupling = compute_aerobic_decoupling_pct(samples)
    splits = compute_km_splits(samples)

    return RunSummary(
        source_sha256=sha256,
        start_ts=start_ts,
        end_ts=end_ts,
        elapsed_time_s=elapsed_s,
        moving_time_s=moving_s,
        total_distance_m=round(total_dist_m, 1),
        elev_gain_m=elev_gain,
        elev_loss_m=elev_loss,
        avg_pace_sec_per_km=round(avg_pace, 1),
        avg_gap_sec_per_km=round(avg_gap, 1),
        avg_hr_bpm=avg_hr,
        max_hr_bpm=max_hr,
        aerobic_decoupling_pct=decoupling,
        hrv=hrv,
        start_batt_mv=start_batt_mv,
        splits=splits,
    )


def format_pace(sec_per_km: float) -> str:
    """Format seconds/km as `M:SS /km`."""
    if sec_per_km <= 0 or math.isinf(sec_per_km) or math.isnan(sec_per_km):
        return "--:-- /km"
    total = int(round(sec_per_km))
    mins, secs = divmod(total, 60)
    return f"{mins}:{secs:02d} /km"
