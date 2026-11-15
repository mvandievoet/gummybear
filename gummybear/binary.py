"""Binary codec for the 16-byte header + 20-byte sample `.gmy` watch log format.

Matches `firmware/include/gummybear_protocol.h` byte-for-byte (little-endian).
"""

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

from gummybear.models import RawSample

GMY_MAGIC = b"GMY1"
GMY_UNCLOSED_COUNT = 0xFFFFFFFF

GMY_FLAG_SAT_MASK = 0x3F
GMY_FLAG_PAUSED = 0x40
GMY_FLAG_HR_VALID = 0x80

# 16 bytes: magic[4], fw_major(u8), fw_minor(u8), start_batt_mv(u16), sample_count(u32), payload_crc32(u32)
HEADER_STRUCT = struct.Struct("<4sBBHII")

# 20 bytes: unix_ts(u32), lat_e7(i32), lon_e7(i32), alt_dm(i16), hdop_x10(u8), sat_flags(u8), hr_bpm(u8), rr_ms(u16), crc8(u8)
SAMPLE_STRUCT = struct.Struct("<IiihBBBHB")
SAMPLE_BODY_STRUCT = struct.Struct("<IiihBBBH")  # First 19 bytes (before crc8)


@dataclass(frozen=True)
class GmyHeader:
    fw_major: int
    fw_minor: int
    start_batt_mv: int
    sample_count: int
    payload_crc32: int

    @property
    def is_unclosed(self) -> bool:
        return self.sample_count == GMY_UNCLOSED_COUNT


def crc8(data: bytes) -> int:
    """SMBus CRC-8 (polynomial 0x07, init 0x00), identical to `gmy_crc8` in C."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def pack_sample(sample: RawSample) -> bytes:
    """Pack a single `RawSample` into a 20-byte CRC-protected binary frame."""
    lat_e7 = int(round(sample.lat * 1e7))
    lon_e7 = int(round(sample.lon * 1e7))
    alt_dm = max(-32768, min(32767, int(round(sample.alt_m * 10.0))))
    hdop_x10 = max(0, min(255, int(round(sample.hdop * 10.0))))

    sat_flags = min(63, max(0, sample.sat_count)) & GMY_FLAG_SAT_MASK
    if sample.paused:
        sat_flags |= GMY_FLAG_PAUSED
    hr_valid = bool(sample.hr_valid and sample.hr_bpm is not None and sample.hr_bpm > 0)
    if hr_valid:
        sat_flags |= GMY_FLAG_HR_VALID

    hr_bpm = max(0, min(255, int(sample.hr_bpm))) if hr_valid and sample.hr_bpm else 0
    rr_ms = max(0, min(65535, int(sample.rr_ms))) if sample.rr_ms else 0

    body = SAMPLE_BODY_STRUCT.pack(
        sample.unix_ts,
        lat_e7,
        lon_e7,
        alt_dm,
        hdop_x10,
        sat_flags,
        hr_bpm,
        rr_ms,
    )
    return body + bytes([crc8(body)])


def unpack_sample(frame: bytes) -> RawSample:
    """Unpack and verify a 20-byte binary sample frame."""
    if len(frame) != SAMPLE_STRUCT.size:
        raise ValueError(f"Expected {SAMPLE_STRUCT.size}-byte frame, got {len(frame)}")

    expected_crc = crc8(frame[:19])
    actual_crc = frame[19]
    if actual_crc != expected_crc:
        raise ValueError(
            f"Sample CRC-8 mismatch: expected 0x{expected_crc:02X}, got 0x{actual_crc:02X}"
        )

    (
        unix_ts,
        lat_e7,
        lon_e7,
        alt_dm,
        hdop_x10,
        sat_flags,
        hr_bpm,
        rr_ms,
        _,
    ) = SAMPLE_STRUCT.unpack(frame)

    sat_count = sat_flags & GMY_FLAG_SAT_MASK
    paused = bool(sat_flags & GMY_FLAG_PAUSED)
    hr_valid = bool(sat_flags & GMY_FLAG_HR_VALID) and hr_bpm > 0

    return RawSample(
        unix_ts=unix_ts,
        lat=lat_e7 / 1e7,
        lon=lon_e7 / 1e7,
        alt_m=alt_dm / 10.0,
        hdop=hdop_x10 / 10.0,
        sat_count=sat_count,
        paused=paused,
        hr_valid=hr_valid,
        hr_bpm=hr_bpm if hr_valid else None,
        rr_ms=rr_ms if (hr_valid and rr_ms > 0) else None,
    )


def encode_gmy(
    samples: Iterable[RawSample],
    start_batt_mv: int = 4150,
    fw_major: int = 0,
    fw_minor: int = 1,
    unclosed: bool = False,
) -> bytes:
    """Encode a complete `.gmy` binary stream (header + payload)."""
    payload_chunks = [pack_sample(s) for s in samples]
    payload = b"".join(payload_chunks)

    if unclosed:
        count = GMY_UNCLOSED_COUNT
        checksum = 0
    else:
        count = len(payload_chunks)
        checksum = zlib.crc32(payload) & 0xFFFFFFFF

    header = HEADER_STRUCT.pack(
        GMY_MAGIC, fw_major, fw_minor, start_batt_mv, count, checksum
    )
    return header + payload


def decode_gmy(
    data: bytes, salvage_corrupt_frames: bool = True
) -> Tuple[GmyHeader, List[RawSample], int]:
    """Decode a `.gmy` byte buffer, supporting crash-interrupted (unclosed) ultra logs.

    Returns `(header, valid_samples, dropped_corrupt_frame_count)`.
    """
    if len(data) < HEADER_STRUCT.size:
        raise ValueError("Buffer shorter than 16-byte GMY header")

    magic, fw_major, fw_minor, start_batt_mv, count, expected_crc32 = HEADER_STRUCT.unpack(
        data[: HEADER_STRUCT.size]
    )
    if magic != GMY_MAGIC:
        raise ValueError(f"Invalid magic header {magic!r}; expected {GMY_MAGIC!r}")

    header = GmyHeader(
        fw_major=fw_major,
        fw_minor=fw_minor,
        start_batt_mv=start_batt_mv,
        sample_count=count,
        payload_crc32=expected_crc32,
    )

    payload = data[HEADER_STRUCT.size :]
    if not header.is_unclosed and not salvage_corrupt_frames:
        expected_bytes = count * SAMPLE_STRUCT.size
        if len(payload) != expected_bytes:
            raise ValueError(
                f"Payload size mismatch: expected {expected_bytes} bytes, got {len(payload)}"
            )
        actual_crc32 = zlib.crc32(payload) & 0xFFFFFFFF
        if actual_crc32 != expected_crc32:
            raise ValueError(
                f"Payload CRC-32 mismatch: expected 0x{expected_crc32:08X}, got 0x{actual_crc32:08X}"
            )

    samples: List[RawSample] = []
    dropped = 0
    usable_len = (len(payload) // SAMPLE_STRUCT.size) * SAMPLE_STRUCT.size
    if len(payload) != usable_len:
        # Trailing partial frame written right as battery cut out
        dropped += 1

    max_frames = usable_len // SAMPLE_STRUCT.size
    if not header.is_unclosed:
        max_frames = min(max_frames, count)

    for i in range(max_frames):
        offset = i * SAMPLE_STRUCT.size
        frame = payload[offset : offset + SAMPLE_STRUCT.size]
        try:
            samples.append(unpack_sample(frame))
        except ValueError:
            if not salvage_corrupt_frames:
                raise
            dropped += 1

    return header, samples, dropped


def read_gmy_file(path: Path, salvage_corrupt_frames: bool = True) -> Tuple[GmyHeader, List[RawSample], int]:
    return decode_gmy(path.read_bytes(), salvage_corrupt_frames=salvage_corrupt_frames)
