"""Zero-dependency Garmin `.FIT` binary activity encoder (Protocol v1.0 / Profile 21.32).

Produces compact binary `.fit` files (~10x smaller than XML `.gpx` on 20-hour ultras)
with full GPS coordinates, altitude, distance, speed, heart rate, lap/session summaries,
and Garmin CRC-16 checksums ready for Strava's `/api/v3/uploads` endpoint.
"""

import struct
from pathlib import Path
from typing import List, Sequence, Tuple

from gummybear.models import CleanSample, RunSummary

# Seconds between Unix epoch (1970-01-01) and Garmin FIT epoch (1989-12-31 00:00:00 UTC)
FIT_EPOCH_OFFSET = 631_065_600

# FIT Base Type constants
BT_ENUM = 0x00
BT_UINT8 = 0x02
BT_UINT16 = 0x84
BT_SINT32 = 0x85
BT_UINT32 = 0x86
BT_UINT32Z = 0x8C

CRC_TABLE = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)


def fit_crc16(data: bytes, crc: int = 0) -> int:
    """Official Garmin FIT SDK nibble-driven CRC-16."""
    for byte in data:
        tmp = CRC_TABLE[crc & 0x0F]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ CRC_TABLE[byte & 0x0F]
        tmp = CRC_TABLE[crc & 0x0F]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ CRC_TABLE[(byte >> 4) & 0x0F]
    return crc & 0xFFFF


def deg_to_semicircles(deg: float) -> int:
    return max(-2147483648, min(2147483647, int(round(deg * (2147483648.0 / 180.0)))))


def _def_mesg(
    local_num: int, global_mesg_num: int, fields: Sequence[Tuple[int, int, int]]
) -> bytes:
    header = struct.pack("<BBHB", 0x40 | (local_num & 0x0F), 0, global_mesg_num, len(fields))
    body = b"".join(struct.pack("<BBB", f_num, f_size, f_type) for f_num, f_size, f_type in fields)
    return header + body


def encode_fit(samples: Sequence[CleanSample], summary: RunSummary) -> bytes:
    """Encode cleaned trajectory and run summary into a binary Garmin `.FIT` activity file."""
    if not samples:
        raise ValueError("Cannot encode empty sample sequence to FIT")

    chunks: List[bytes] = []
    start_fit_ts = max(0, summary.start_ts - FIT_EPOCH_OFFSET)
    end_fit_ts = max(start_fit_ts, summary.end_ts - FIT_EPOCH_OFFSET)

    # 1. FileId message (Global 0, Local 0)
    chunks.append(
        _def_mesg(
            0,
            0,
            [
                (3, 4, BT_UINT32Z),  # serial_number
                (4, 4, BT_UINT32),   # time_created
                (1, 2, BT_UINT16),   # manufacturer (255 = development)
                (2, 2, BT_UINT16),   # product (218 = Casio W-218H)
                (0, 1, BT_ENUM),     # type (4 = activity)
            ],
        )
    )
    chunks.append(struct.pack("<BIIHHB", 0, 20260218, start_fit_ts, 255, 218, 4))

    # 2. Record definition (Global 20, Local 1)
    chunks.append(
        _def_mesg(
            1,
            20,
            [
                (253, 4, BT_UINT32),  # timestamp
                (0, 4, BT_SINT32),    # position_lat (semicircles)
                (1, 4, BT_SINT32),    # position_long (semicircles)
                (5, 4, BT_UINT32),    # distance (scale 100 -> cm)
                (2, 2, BT_UINT16),    # altitude (scale 5, offset +500m)
                (6, 2, BT_UINT16),    # speed (scale 1000 -> mm/s)
                (3, 1, BT_UINT8),     # heart_rate (bpm, 0xFF invalid)
            ],
        )
    )
    rec_packer = struct.Struct("<BIIIiHHB")  # Wait: lat & lon are both signed i! Fixed below.
    rec_packer = struct.Struct("<BIiiIHHB")

    for s in samples:
        if s.paused:
            continue
        fit_ts = max(0, s.unix_ts - FIT_EPOCH_OFFSET)
        lat_sc = deg_to_semicircles(s.lat)
        lon_sc = deg_to_semicircles(s.lon)
        dist_cm = max(0, int(round(s.cum_dist_m * 100.0)))
        alt_scaled = max(0, min(65534, int(round((s.alt_m + 500.0) * 5.0))))
        spd_mms = max(0, min(65534, int(round(s.speed_mps * 1000.0))))
        hr = max(1, min(254, s.hr_bpm)) if (s.hr_bpm is not None and s.hr_bpm > 0) else 0xFF
        chunks.append(
            rec_packer.pack(1, fit_ts, lat_sc, lon_sc, dist_cm, alt_scaled, spd_mms, hr)
        )

    elapsed_ms = max(1000, int(round(summary.elapsed_time_s * 1000)))
    moving_ms = max(1000, int(round(summary.moving_time_s * 1000)))
    total_dist_cm = max(0, int(round(summary.total_distance_m * 100.0)))
    ascent_m = max(0, min(65534, int(round(summary.elev_gain_m))))
    descent_m = max(0, min(65534, int(round(summary.elev_loss_m))))
    avg_hr = int(round(summary.avg_hr_bpm)) if summary.avg_hr_bpm else 0xFF
    max_hr = int(summary.max_hr_bpm) if summary.max_hr_bpm else 0xFF

    # 3. Lap message (Global 19, Local 2)
    chunks.append(
        _def_mesg(
            2,
            19,
            [
                (253, 4, BT_UINT32),  # timestamp
                (2, 4, BT_UINT32),    # start_time
                (7, 4, BT_UINT32),    # total_elapsed_time (ms)
                (8, 4, BT_UINT32),    # total_timer_time (ms)
                (9, 4, BT_UINT32),    # total_distance (cm)
                (21, 2, BT_UINT16),   # total_ascent (m)
                (22, 2, BT_UINT16),   # total_descent (m)
                (15, 1, BT_UINT8),    # avg_heart_rate
                (16, 1, BT_UINT8),    # max_heart_rate
                (25, 1, BT_ENUM),     # sport (1 = running)
                (0, 1, BT_ENUM),      # event (9 = lap)
                (1, 1, BT_ENUM),      # event_type (1 = stop)
            ],
        )
    )
    chunks.append(
        struct.pack(
            "<BIIIIIHHBBBBB",
            2,
            end_fit_ts,
            start_fit_ts,
            elapsed_ms,
            moving_ms,
            total_dist_cm,
            ascent_m,
            descent_m,
            avg_hr,
            max_hr,
            1,
            9,
            1,
        )
    )

    # 4. Session message (Global 18, Local 3)
    chunks.append(
        _def_mesg(
            3,
            18,
            [
                (253, 4, BT_UINT32),  # timestamp
                (2, 4, BT_UINT32),    # start_time
                (7, 4, BT_UINT32),    # total_elapsed_time (ms)
                (8, 4, BT_UINT32),    # total_timer_time (ms)
                (9, 4, BT_UINT32),    # total_distance (cm)
                (22, 2, BT_UINT16),   # total_ascent (m)
                (23, 2, BT_UINT16),   # total_descent (m)
                (16, 1, BT_UINT8),    # avg_heart_rate
                (17, 1, BT_UINT8),    # max_heart_rate
                (5, 1, BT_ENUM),      # sport (1 = running)
                (6, 1, BT_ENUM),      # sub_sport (0 = generic)
                (0, 1, BT_ENUM),      # event (8 = session)
                (1, 1, BT_ENUM),      # event_type (1 = stop)
            ],
        )
    )
    chunks.append(
        struct.pack(
            "<BIIIIIHHBBBBBB",
            3,
            end_fit_ts,
            start_fit_ts,
            elapsed_ms,
            moving_ms,
            total_dist_cm,
            ascent_m,
            descent_m,
            avg_hr,
            max_hr,
            1,
            0,
            8,
            1,
        )
    )

    # 5. Activity message (Global 34, Local 4)
    chunks.append(
        _def_mesg(
            4,
            34,
            [
                (253, 4, BT_UINT32),  # timestamp
                (0, 4, BT_UINT32),    # total_timer_time (ms)
                (1, 2, BT_UINT16),    # num_sessions (1)
                (2, 1, BT_ENUM),      # type (0 = manual)
                (3, 1, BT_ENUM),      # event (26 = activity)
                (4, 1, BT_ENUM),      # event_type (1 = stop)
            ],
        )
    )
    chunks.append(struct.pack("<BIIHBBB", 4, end_fit_ts, moving_ms, 1, 0, 26, 1))

    data_bytes = b"".join(chunks)
    header_12 = struct.pack("<BBHI4s", 14, 0x10, 2132, len(data_bytes), b".FIT")
    header_crc = struct.pack("<H", fit_crc16(header_12))
    full_header = header_12 + header_crc
    file_crc = struct.pack("<H", fit_crc16(data_bytes, fit_crc16(full_header)))
    return full_header + data_bytes + file_crc


def write_fit_file(
    path: Path, samples: Sequence[CleanSample], summary: RunSummary
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_fit(samples, summary))
