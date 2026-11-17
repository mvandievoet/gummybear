"""USB-Serial watch sync client for Seeed Studio XIAO nRF52840 (`/dev/cu.usbmodem*`).

Talks the lightweight `PING` / `LIST` / `GET <file>` / `DEL <file>` protocol implemented
in `firmware/gummybear_watch/gummybear_watch.ino`. Requires `pyserial` (`pip install pyserial`)
when syncing physical hardware.
"""

import glob
import time
from pathlib import Path
from typing import List, Optional, Tuple

from gummybear.binary import decode_gmy


def auto_detect_watch_port() -> Optional[str]:
    """Find a connected Seeed XIAO nRF52840 USB CDC serial device on macOS / Linux."""
    candidates = sorted(
        glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*")
    )
    return candidates[0] if candidates else None


def pull_runs_over_usb_serial(
    output_dir: Path,
    port: Optional[str] = None,
    baudrate: int = 115200,
    delete_after_verify: bool = True,
) -> List[Path]:
    """Download all `.gmy` run logs from the watch over USB-C and verify integrity."""
    try:
        import serial  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "USB watch sync requires `pyserial`. Install with: pip install pyserial"
        ) from exc

    resolved_port = port or auto_detect_watch_port()
    if not resolved_port:
        raise FileNotFoundError(
            "No Casio/XIAO watch detected on /dev/cu.usbmodem*. Is USB-C plugged in and watch on CLOCK screen?"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: List[Path] = []

    with serial.Serial(resolved_port, baudrate=baudrate, timeout=4.0) as ser:
        ser.reset_input_buffer()
        ser.write(b"PING\n")
        pong = ser.readline().decode("utf-8", errors="replace").strip()
        if not pong.startswith("PONG"):
            raise RuntimeError(f"Unexpected watch handshake on {resolved_port}: {pong!r}")

        ser.write(b"LIST\n")
        remote_files: List[Tuple[str, int]] = []
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line or line == "END":
                break
            if line.startswith("FILE "):
                parts = line.split()
                if len(parts) == 3:
                    remote_files.append((parts[1], int(parts[2])))

        for fname, expected_size in remote_files:
            ser.write(f"GET {fname}\n".encode("utf-8"))
            hdr_line = ser.readline().decode("utf-8", errors="replace").strip()
            if not hdr_line.startswith("DATA "):
                raise RuntimeError(f"Failed to read {fname}: {hdr_line}")
            byte_len = int(hdr_line.split()[1])
            blob = ser.read(byte_len)
            if len(blob) != byte_len or byte_len != expected_size:
                raise RuntimeError(
                    f"Incomplete transfer for {fname}: got {len(blob)}/{expected_size} bytes"
                )

            # Verify valid GMY header & frames before deleting from watch flash
            decode_gmy(blob, salvage_corrupt_frames=True)

            dest = output_dir / fname
            dest.write_bytes(blob)
            downloaded.append(dest)

            if delete_after_verify:
                ser.write(f"DEL {fname}\n".encode("utf-8"))
                ack = ser.readline().decode("utf-8", errors="replace").strip()
                if ack != "OK":
                    print(f"Warning: watch did not delete {fname}: {ack}")

    return downloaded


def run_step1_bench_hr_session(
    output_dir: Path,
    duration_s: int = 30,
    port: Optional[str] = None,
    baudrate: int = 115200,
) -> List[Path]:
    """Automated Prototype Step #1 helper: syncs Mac time to XIAO #1 over USB-C,
    pairs with your Bluetooth HR strap, records `duration_s` of live heartbeat data
    onto XIAO's 2 MB flash (no buttons/screen/GPS required), and pulls the `.gmy` file.
    """
    try:
        import serial  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Bench test requires `pyserial`. Install with: pip install pyserial"
        ) from exc

    resolved_port = port or auto_detect_watch_port()
    if not resolved_port:
        raise FileNotFoundError(
            "No XIAO nRF52840 detected on /dev/cu.usbmodem*. Plug XIAO #1 in via USB-C first."
        )

    with serial.Serial(resolved_port, baudrate=baudrate, timeout=3.0) as ser:
        ser.reset_input_buffer()
        now_ts = int(time.time())
        ser.write(f"TIME {now_ts}\n".encode("utf-8"))
        ser.readline()

        print(f"Connected to {resolved_port}. Scanning Bluetooth for your HR strap...")
        ser.write(b"MODE\n")
        ser.readline()

        locked_bpm = 0
        wait_deadline = time.time() + 25.0
        while time.time() < wait_deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if "hr=" in line:
                for tok in line.split():
                    if tok.startswith("hr="):
                        val = int(tok.split("=")[1])
                        if val > 0:
                            locked_bpm = val
                            break
            if locked_bpm > 0:
                print(f"Locked onto HR strap! Live HR = {locked_bpm} bpm.")
                break

        if locked_bpm == 0:
            ser.write(b"MODE\n")
            raise RuntimeError(
                "Timed out waiting for Bluetooth HR strap (make sure strap pads are moistened and worn)."
            )

        print(f"Recording {duration_s}s indoor HR session onto XIAO flash...")
        ser.write(b"START\n")
        ser.readline()

        rec_end = time.time() + duration_s
        while time.time() < rec_end:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line.startswith("[TICK]"):
                print(f"  {line}")

        ser.write(b"PAUSE\n")
        ser.readline()
        ser.write(b"SAVE\n")
        ser.readline()
        print("Saved on XIAO flash. Pulling `.gmy` log over USB-C...")

    return pull_runs_over_usb_serial(
        output_dir=output_dir, port=resolved_port, baudrate=baudrate
    )
