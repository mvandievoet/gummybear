import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from gummybear.binary import (
    HEADER_STRUCT,
    SAMPLE_STRUCT,
    decode_gmy,
    encode_gmy,
    pack_sample,
    unpack_sample,
)
from gummybear.cli import main as cli_main
from gummybear.export_fit import encode_fit, fit_crc16
from gummybear.export_gpx import encode_gpx
from gummybear.kalman import clean_trajectory
from gummybear.metrics import (
    compute_hrv_from_rr,
    grade_adjusted_speed_mps,
    haversine_m,
    summarize_run,
)
from gummybear.models import RawSample
from gummybear.simulator import generate_synthetic_sf_run


class TestBinaryProtocol(unittest.TestCase):
    def test_exact_struct_sizes_match_c_header(self) -> None:
        self.assertEqual(HEADER_STRUCT.size, 16)
        self.assertEqual(SAMPLE_STRUCT.size, 20)

    def test_sample_roundtrip_including_negative_altitude(self) -> None:
        s = RawSample(
            unix_ts=1763218800,
            lat=37.7888123,
            lon=-122.4340456,
            alt_m=-12.4,
            hdop=1.3,
            sat_count=11,
            paused=True,
            hr_valid=True,
            hr_bpm=164,
            rr_ms=366,
        )
        packed = pack_sample(s)
        self.assertEqual(len(packed), 20)
        unpacked = unpack_sample(packed)
        self.assertEqual(unpacked.unix_ts, s.unix_ts)
        self.assertAlmostEqual(unpacked.lat, s.lat, places=6)
        self.assertAlmostEqual(unpacked.lon, s.lon, places=6)
        self.assertAlmostEqual(unpacked.alt_m, -12.4, places=1)
        self.assertAlmostEqual(unpacked.hdop, 1.3, places=1)
        self.assertEqual(unpacked.sat_count, 11)
        self.assertTrue(unpacked.paused)
        self.assertEqual(unpacked.hr_bpm, 164)
        self.assertEqual(unpacked.rr_ms, 366)

    def test_crc8_detects_single_bit_flip(self) -> None:
        s = RawSample(1763218800, 37.8, -122.4, 25.0, 1.1, 9, False, True, 150, 400)
        corrupted = bytearray(pack_sample(s))
        corrupted[7] ^= 0x04
        with self.assertRaises(ValueError):
            unpack_sample(bytes(corrupted))

    def test_unclosed_ultra_stream_salvages_valid_frames(self) -> None:
        samples = [
            RawSample(1763218800 + i, 37.8 + i * 1e-5, -122.4, 10.0, 1.2, 10, False, True, 145, 410)
            for i in range(10)
        ]
        # Simulate battery dying mid-write on sample #11 during an ultra
        stream = encode_gmy(samples, unclosed=True) + b"\xde\xad\xbe\xef\x01"
        header, recovered, dropped = decode_gmy(stream, salvage_corrupt_frames=True)
        self.assertTrue(header.is_unclosed)
        self.assertEqual(len(recovered), 10)
        self.assertEqual(dropped, 1)


class TestKalmanAndMetrics(unittest.TestCase):
    def test_rts_kalman_smoother_reduces_urban_canyon_rmse(self) -> None:
        noisy, truth = generate_synthetic_sf_run(seed=7)
        cleaned = clean_trajectory(noisy)
        self.assertEqual(len(cleaned), len(truth))

        raw_sq_err = sum(
            haversine_m(r.lat, r.lon, t[0], t[1]) ** 2 for r, t in zip(noisy, truth)
        ) / len(truth)
        clean_sq_err = sum(
            haversine_m(c.lat, c.lon, t[0], t[1]) ** 2 for c, t in zip(cleaned, truth)
        ) / len(truth)

        raw_rmse = raw_sq_err ** 0.5
        clean_rmse = clean_sq_err ** 0.5
        # RTS smoother should cut horizontal position RMSE substantially (>35% reduction)
        self.assertLess(clean_rmse, raw_rmse * 0.65)

    def test_minetti_gap_physics(self) -> None:
        flat = grade_adjusted_speed_mps(3.5, 0.0)
        uphill_10pct = grade_adjusted_speed_mps(3.5, 0.10)
        gentle_downhill = grade_adjusted_speed_mps(3.5, -0.08)
        self.assertAlmostEqual(flat, 3.5, places=4)
        self.assertGreater(uphill_10pct, flat * 1.35)
        self.assertLess(gentle_downhill, flat)

    def test_hrv_ectopic_spike_rejection(self) -> None:
        rr = [410, 415, 408, 412, 980, 409, 414, 411]  # 980ms missed-beat artifact
        hrv = compute_hrv_from_rr(rr)
        self.assertEqual(hrv.rejected_rr_count, 1)
        self.assertIsNotNone(hrv.rmssd_ms)
        self.assertLess(hrv.rmssd_ms or 999.0, 15.0)


class TestExportsAndCliEndToEnd(unittest.TestCase):
    def test_fit_and_gpx_integrity_and_cli_dedup(self) -> None:
        noisy, _ = generate_synthetic_sf_run(seed=99)
        raw_blob = encode_gmy(noisy)
        cleaned = clean_trajectory(noisy)
        # Inject one paused point to test GPX <trkseg> splitting
        summary = summarize_run(cleaned, raw_bytes=raw_blob)

        fit_bytes = encode_fit(cleaned, summary)
        self.assertEqual(fit_bytes[0], 14)
        self.assertEqual(fit_bytes[8:12], b".FIT")
        # Full FIT buffer CRC check over [0:-2] must equal trailing 2-byte little-endian CRC
        expected_crc = int.from_bytes(fit_bytes[-2:], "little")
        self.assertEqual(fit_crc16(fit_bytes[:-2]), expected_crc)

        gpx_xml = encode_gpx(cleaned[:50], name="Pac Heights Test")
        root = ET.fromstring(gpx_xml)
        self.assertTrue(root.tag.endswith("gpx"))
        hr_nodes = list(root.iter("{http://www.garmin.com/xmlschemas/TrackPointExtension/v1}hr"))
        self.assertEqual(len(hr_nodes), 50)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            gmy_file = tmp_dir / "sim.gmy"
            db_file = tmp_dir / "warehouse.db"

            rc1 = cli_main(["--db", str(db_file), "simulate", "-o", str(gmy_file), "--seed", "11"])
            self.assertEqual(rc1, 0)
            self.assertTrue(gmy_file.exists())

            rc2 = cli_main(["--db", str(db_file), "ingest", str(gmy_file), "--name", "Test Run"])
            self.assertEqual(rc2, 0)

            # Second ingest of exact same binary file must deduplicate cleanly
            rc3 = cli_main(["--db", str(db_file), "ingest", str(gmy_file), "--name", "Test Run"])
            self.assertEqual(rc3, 0)

            rc4 = cli_main(["--db", str(db_file), "runs"])
            self.assertEqual(rc4, 0)


if __name__ == "__main__":
    unittest.main()
