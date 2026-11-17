"""2D Rauch-Tung-Striebel (RTS) Kalman Smoother & elevation denoising.

Because watch tracks are processed post-run on macOS, we run a forward Kalman
filter weighted by per-sample GPS HDOP + satellite count followed by a backward
RTS fixed-interval smoother pass. This suppresses urban-canyon multipath bounce
(e.g. downtown SF / Marina street walls) with zero corner-cutting phase lag.
"""

import json
import math
import urllib.request
from typing import Callable, List, Optional, Sequence, Tuple

from gummybear.metrics import grade_adjusted_speed_mps, haversine_m
from gummybear.models import CleanSample, RawSample

EARTH_RADIUS_M = 6_371_000.0

# 2x2 Matrix alias: ((a00, a01), (a10, a11))
Mat2 = Tuple[Tuple[float, float], Tuple[float, float]]
Vec2 = Tuple[float, float]


def _mat2_mul(a: Mat2, b: Mat2) -> Mat2:
    return (
        (a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
        (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]),
    )


def _mat2_transpose(a: Mat2) -> Mat2:
    return ((a[0][0], a[1][0]), (a[0][1], a[1][1]))


def _mat2_add(a: Mat2, b: Mat2) -> Mat2:
    return (
        (a[0][0] + b[0][0], a[0][1] + b[0][1]),
        (a[1][0] + b[1][0], a[1][1] + b[1][1]),
    )


def _mat2_sub(a: Mat2, b: Mat2) -> Mat2:
    return (
        (a[0][0] - b[0][0], a[0][1] - b[0][1]),
        (a[1][0] - b[1][0], a[1][1] - b[1][1]),
    )


def _mat2_vec(a: Mat2, v: Vec2) -> Vec2:
    return (a[0][0] * v[0] + a[0][1] * v[1], a[1][0] * v[0] + a[1][1] * v[1])


def _mat2_inv(a: Mat2) -> Mat2:
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    if abs(det) < 1e-12:
        det = 1e-12
    inv_det = 1.0 / det
    return (
        (a[1][1] * inv_det, -a[0][1] * inv_det),
        (-a[1][0] * inv_det, a[0][0] * inv_det),
    )


def _rts_smooth_1d(
    timestamps: Sequence[int],
    obs: Sequence[float],
    meas_variances: Sequence[float],
    accel_sigma: float = 1.1,
    outlier_speed_mps: float = 14.0,
) -> Tuple[List[float], List[float]]:
    """Forward-backward 1D constant-velocity RTS Kalman smoother.

    Returns `(smoothed_positions, smoothed_velocities)`.
    """
    n = len(obs)
    if n == 0:
        return [], []
    if n == 1:
        return [obs[0]], [0.0]

    x_filt: List[Vec2] = []
    p_filt: List[Mat2] = []
    x_pred_list: List[Vec2] = []
    p_pred_list: List[Mat2] = []
    f_list: List[Mat2] = []

    # Initialize state [pos, vel]
    dt0 = max(1.0, float(timestamps[1] - timestamps[0]))
    v0 = max(-8.0, min(8.0, (obs[1] - obs[0]) / dt0))
    s_curr: Vec2 = (obs[0], v0)
    p_curr: Mat2 = ((meas_variances[0], 0.0), (0.0, 9.0))

    x_filt.append(s_curr)
    p_filt.append(p_curr)
    x_pred_list.append(s_curr)
    p_pred_list.append(p_curr)
    f_list.append(((1.0, 0.0), (0.0, 1.0)))

    q_var = accel_sigma * accel_sigma

    for k in range(1, n):
        dt = max(0.2, float(timestamps[k] - timestamps[k - 1]))
        # Cap dt for process noise stability across long pauses
        dt_eff = min(dt, 30.0)
        f_k: Mat2 = ((1.0, dt), (0.0, 1.0))
        dt2 = dt_eff * dt_eff
        dt3 = dt2 * dt_eff
        dt4 = dt2 * dt2
        q_k: Mat2 = (
            (0.25 * dt4 * q_var, 0.5 * dt3 * q_var),
            (0.5 * dt3 * q_var, dt2 * q_var),
        )

        s_pred = _mat2_vec(f_k, s_curr)
        p_pred = _mat2_add(_mat2_mul(_mat2_mul(f_k, p_curr), _mat2_transpose(f_k)), q_k)

        innovation = obs[k] - s_pred[0]
        r_k = meas_variances[k]

        # Multipath spike gate: downweight impossible 1-step jumps (>14 m/s & >20 m)
        if abs(innovation) > 20.0 and (abs(innovation) / dt) > outlier_speed_mps:
            r_k *= 150.0

        s_innov = p_pred[0][0] + r_k
        k0 = p_pred[0][0] / s_innov
        k1 = p_pred[1][0] / s_innov

        s_curr = (s_pred[0] + k0 * innovation, s_pred[1] + k1 * innovation)
        # Joseph / standard covariance update for H = [1, 0]
        i_kh: Mat2 = ((1.0 - k0, 0.0), (-k1, 1.0))
        p_curr = _mat2_mul(i_kh, p_pred)

        f_list.append(f_k)
        x_pred_list.append(s_pred)
        p_pred_list.append(p_pred)
        x_filt.append(s_curr)
        p_filt.append(p_curr)

    # Backward Rauch-Tung-Striebel smoothing pass
    x_smooth: List[Vec2] = [ (0.0, 0.0) ] * n
    x_smooth[n - 1] = x_filt[n - 1]

    for k in range(n - 2, -1, -1):
        f_next = f_list[k + 1]
        c_gain = _mat2_mul(
            _mat2_mul(p_filt[k], _mat2_transpose(f_next)),
            _mat2_inv(p_pred_list[k + 1]),
        )
        diff: Vec2 = (
            x_smooth[k + 1][0] - x_pred_list[k + 1][0],
            x_smooth[k + 1][1] - x_pred_list[k + 1][1],
        )
        corr = _mat2_vec(c_gain, diff)
        x_smooth[k] = (x_filt[k][0] + corr[0], x_filt[k][1] + corr[1])

    return [s[0] for s in x_smooth], [s[1] for s in x_smooth]


def gaussian_smooth_1d(values: Sequence[float], sigma_samples: float = 5.0) -> List[float]:
    """Zero-phase symmetric Gaussian smoothing for noisy consumer GPS altitude."""
    n = len(values)
    if n <= 2 or sigma_samples <= 0:
        return list(values)
    radius = max(1, int(math.ceil(3.0 * sigma_samples)))
    weights = [
        math.exp(-0.5 * (offset / sigma_samples) ** 2)
        for offset in range(-radius, radius + 1)
    ]
    out: List[float] = []
    for i in range(n):
        w_sum = 0.0
        v_sum = 0.0
        for idx, offset in enumerate(range(-radius, radius + 1)):
            j = min(n - 1, max(0, i + offset))
            w = weights[idx]
            w_sum += w
            v_sum += w * values[j]
        out.append(v_sum / w_sum)
    return out


def query_usgs_3dep_elevation_m(lat: float, lon: float, timeout_s: float = 3.0) -> Optional[float]:
    """Optional online elevation lookup against USGS 3DEP Elevation Point Query Service."""
    url = (
        f"https://epqs.nationalmap.gov/v1/json?x={lon:.6f}&y={lat:.6f}"
        "&units=Meters&wkid=4326&includeDate=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "gummybear/0.1"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        val = payload.get("value")
        return float(val) if val is not None else None


ElevationResolver = Callable[[Sequence[Tuple[float, float]]], Sequence[float]]


def clean_trajectory(
    raw_samples: Sequence[RawSample],
    base_gps_sigma_m: float = 2.4,
    accel_sigma_mps2: float = 1.1,
    alt_smooth_sigma_s: float = 14.0,
    elevation_resolver: Optional[ElevationResolver] = None,
) -> List[CleanSample]:
    """Run 2D HDOP-weighted RTS Kalman smoothing, elevation cleaning, and GAP kinematics."""
    if not raw_samples:
        return []

    ordered = sorted(raw_samples, key=lambda s: s.unix_ts)
    gps_points = [s for s in ordered if s.sat_count > 0 and not (s.lat == 0.0 and s.lon == 0.0)]

    # Indoor / Prototype Step #1 HR-only recording (no GPS connected yet)
    if not gps_points:
        return [
            CleanSample(
                unix_ts=raw.unix_ts,
                lat=0.0,
                lon=0.0,
                alt_m=0.0,
                cum_dist_m=0.0,
                speed_mps=0.0,
                grade=0.0,
                gap_speed_mps=0.0,
                paused=raw.paused,
                hr_bpm=raw.hr_bpm if raw.hr_valid else None,
                rr_ms=raw.rr_ms if raw.hr_valid else None,
                has_gps=False,
            )
            for raw in ordered
        ]

    lat0 = gps_points[0].lat
    lon0 = gps_points[0].lon
    cos_lat0 = math.cos(math.radians(lat0))

    ts_list: List[int] = []
    east_obs: List[float] = []
    north_obs: List[float] = []
    meas_vars: List[float] = []

    for s in ordered:
        ts_list.append(s.unix_ts)
        east_m = math.radians(s.lon - lon0) * EARTH_RADIUS_M * cos_lat0
        north_m = math.radians(s.lat - lat0) * EARTH_RADIUS_M
        east_obs.append(east_m)
        north_obs.append(north_m)

        hdop_eff = max(0.8, s.hdop)
        sat_penalty = 2.5 if s.sat_count < 5 else (1.4 if s.sat_count < 7 else 1.0)
        sigma = base_gps_sigma_m * hdop_eff * sat_penalty
        meas_vars.append(sigma * sigma)

    east_smooth, vx_smooth = _rts_smooth_1d(
        ts_list, east_obs, meas_vars, accel_sigma=accel_sigma_mps2
    )
    north_smooth, vy_smooth = _rts_smooth_1d(
        ts_list, north_obs, meas_vars, accel_sigma=accel_sigma_mps2
    )

    lats = [lat0 + math.degrees(y / EARTH_RADIUS_M) for y in north_smooth]
    lons = [
        lon0 + math.degrees(x / (EARTH_RADIUS_M * max(1e-6, cos_lat0)))
        for x in east_smooth
    ]

    if elevation_resolver is not None:
        alts = list(elevation_resolver(list(zip(lats, lons))))
    else:
        alts = gaussian_smooth_1d([s.alt_m for s in ordered], sigma_samples=alt_smooth_sigma_s)

    cleaned: List[CleanSample] = []
    cum_dist = 0.0

    for i, raw in enumerate(ordered):
        if i == 0 or raw.paused or ordered[i - 1].paused:
            step_dist = 0.0
        else:
            dt = max(1, raw.unix_ts - ordered[i - 1].unix_ts)
            d_step = haversine_m(lats[i - 1], lons[i - 1], lats[i], lons[i])
            # Standing-still jitter clamp (<0.35 m/s)
            step_dist = 0.0 if (d_step / dt) < 0.35 else d_step
        cum_dist += step_dist

        # Compute smoothed grade over a ~20-meter / ~6-sample lookaround window
        w_lo = max(0, i - 3)
        w_hi = min(len(ordered) - 1, i + 3)
        horiz_span = haversine_m(lats[w_lo], lons[w_lo], lats[w_hi], lons[w_hi])
        if horiz_span >= 8.0:
            grade = max(-0.45, min(0.45, (alts[w_hi] - alts[w_lo]) / horiz_span))
        else:
            grade = 0.0

        if raw.paused:
            speed_mps = 0.0
        else:
            kf_speed = math.hypot(vx_smooth[i], vy_smooth[i])
            speed_mps = 0.0 if kf_speed < 0.35 else kf_speed

        gap_mps = grade_adjusted_speed_mps(speed_mps, grade)

        cleaned.append(
            CleanSample(
                unix_ts=raw.unix_ts,
                lat=lats[i],
                lon=lons[i],
                alt_m=round(alts[i], 2),
                cum_dist_m=round(cum_dist, 2),
                speed_mps=round(speed_mps, 3),
                grade=round(grade, 4),
                gap_speed_mps=round(gap_mps, 3),
                paused=raw.paused,
                hr_bpm=raw.hr_bpm if raw.hr_valid else None,
                rr_ms=raw.rr_ms if raw.hr_valid else None,
            )
        )

    return cleaned
