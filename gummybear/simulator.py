"""Synthetic SF run generator (Pacific Heights -> Marina Green -> Crissy Field loop).

Simulates realistic running kinematics, steep SF hill grades, urban-canyon GPS multipath
glitches, consumer GPS vertical wander, physiological heart-rate lag + cardiac drift,
and Garmin chest-strap R-R intervals.
"""

import math
import random
from typing import List, Tuple

from gummybear.models import RawSample

# Waypoints: California & Fillmore (Pac Heights) -> Marina Green -> Crissy Field -> Pac Heights
SF_LOOP_WAYPOINTS: List[Tuple[float, float, float]] = [
    (37.7888, -122.4340, 82.0),  # California & Fillmore (Pacific Heights crest)
    (37.7960, -122.4358, 38.0),  # Descending Fillmore St
    (37.8042, -122.4375, 4.5),   # Marina Blvd & Fillmore
    (37.8058, -122.4485, 3.0),   # Marina Green West / Yacht Harbor
    (37.8048, -122.4645, 3.5),   # Crissy Field East Beach / Marsh
    (37.8058, -122.4485, 3.0),   # Return along waterfront
    (37.8042, -122.4375, 4.5),   # Base of Fillmore climb
    (37.7960, -122.4358, 38.0),  # Climbing back up Fillmore
    (37.7888, -122.4340, 82.0),  # Finish back on California St
]


def generate_synthetic_sf_run(
    start_ts: int = 1794754800,  # Sun Nov 15 2026 07:00:00 PT
    base_flat_speed_mps: float = 3.65,  # ~4:34 /km flat cruise pace
    seed: int = 42,
) -> Tuple[List[RawSample], List[Tuple[float, float, float]]]:
    """Generate a realistic noisy `.gmy`-ready `RawSample` trace + ground-truth `(lat, lon, alt)`.

    Returns `(noisy_raw_samples, ground_truth_positions)`.
    """
    rng = random.Random(seed)
    earth_r = 6_371_000.0

    noisy: List[RawSample] = []
    truth: List[Tuple[float, float, float]] = []

    curr_ts = start_ts
    hr_float = 118.0  # Starting warmup HR

    for seg_idx in range(len(SF_LOOP_WAYPOINTS) - 1):
        lat1, lon1, alt1 = SF_LOOP_WAYPOINTS[seg_idx]
        lat2, lon2, alt2 = SF_LOOP_WAYPOINTS[seg_idx + 1]

        cos_lat = math.cos(math.radians((lat1 + lat2) * 0.5))
        dx = math.radians(lon2 - lon1) * earth_r * cos_lat
        dy = math.radians(lat2 - lat1) * earth_r
        seg_dist = math.hypot(dx, dy)
        seg_grade = (alt2 - alt1) / max(1.0, seg_dist)

        # Slow down realistically on climbs and speed up slightly on descents
        hill_factor = max(0.62, min(1.12, 1.0 - 3.2 * seg_grade))
        seg_speed = base_flat_speed_mps * hill_factor
        steps = max(2, int(round(seg_dist / seg_speed)))

        for step in range(steps):
            frac = step / steps
            t_lat = lat1 + frac * (lat2 - lat1)
            t_lon = lon1 + frac * (lon2 - lon1)
            t_alt = alt1 + frac * (alt2 - alt1)
            truth.append((t_lat, t_lon, t_alt))

            # Urban canyon multipath zone on Fillmore St segments
            in_canyon = seg_idx in (0, 1, 6, 7)
            hdop = rng.uniform(1.8, 3.4) if in_canyon else rng.uniform(0.9, 1.4)
            sats = rng.randint(5, 8) if in_canyon else rng.randint(9, 14)

            sigma_m = 2.1 * hdop
            err_east = rng.gauss(0.0, sigma_m)
            err_north = rng.gauss(0.0, sigma_m)

            # Inject occasional 35m building-reflection multipath spike (~0.7% of canyon points)
            if in_canyon and rng.random() < 0.007:
                err_east += rng.choice([-38.0, 38.0])
                hdop = 4.5

            n_lat = t_lat + math.degrees(err_north / earth_r)
            n_lon = t_lon + math.degrees(err_east / (earth_r * cos_lat))
            n_alt = t_alt + rng.gauss(0.0, 6.5) + 4.0 * math.sin(curr_ts / 45.0)

            # First-order physiological HR kinetics + gradual 3.5% cardiac drift over run
            elapsed_frac = min(1.0, (curr_ts - start_ts) / 2400.0)
            effort_hr = 148.0 + 185.0 * max(0.0, seg_grade) - 45.0 * max(0.0, -seg_grade)
            target_hr = effort_hr * (1.0 + 0.035 * elapsed_frac)
            hr_float += (target_hr - hr_float) / 18.0 + rng.gauss(0.0, 0.35)
            bpm = max(95, min(198, int(round(hr_float))))

            mean_rr = 60_000.0 / max(40.0, hr_float)
            rr_ms = int(round(mean_rr + rng.gauss(0.0, 14.0)))

            noisy.append(
                RawSample(
                    unix_ts=curr_ts,
                    lat=n_lat,
                    lon=n_lon,
                    alt_m=n_alt,
                    hdop=round(hdop, 1),
                    sat_count=sats,
                    paused=False,
                    hr_valid=True,
                    hr_bpm=bpm,
                    rr_ms=rr_ms,
                )
            )
            curr_ts += 1

    return noisy, truth
