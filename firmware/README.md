# Watch Firmware (`Seeed Studio XIAO nRF52840`)

Embedded C/C++ firmware for the sleeper **Casio W-218H** GPS + BLE Heart Rate watch.

## Architecture
- `include/gummybear_protocol.h`: Shared 16-byte header + 20-byte packed 1 Hz sample layout (kept byte-identical with `gummybear/binary.py`).
- `include/ble_hr_parser.h`: Bluetooth SIG Heart Rate Measurement (`0x180D` / `0x2A37`) parser extracting live `BPM` and `1/1024 s` beat-to-beat `R-R` intervals from Garmin chest straps.
- `include/nmea_parser.h`: Zero-allocation fixed-point (`1e-7` deg, ~`1.1 cm` resolution) `$GNRMC` + `$GNGGA` parser for the `Flywoo GOKU GM10 Nano V3.1` (`u-blox M10050`).
- `include/watch_state.h`: Watch state machine (`CLOCK`, `PRE_RUN`, `RUNNING`, `PAUSED`), live distance/pace smoothing, and CRC-32/CRC-8 `.gmy` frame builder.
- `gummybear_watch/gummybear_watch.ino`: Complete hardware sketch (BLE Central + UART GPS + P-MOSFET zero-drain power cutoff + `nice!view` Sharp Memory LCD + LittleFS `.gmy` flash recorder + USB-C serial sync server).
- `tests/test_firmware.c`: Host-compiled C unit & Python-interop tests (`clang -Wall -Wextra -Werror firmware/tests/test_firmware.c -lm`).

## Flashing onto `Seeed XIAO nRF52840` (When Parts Arrive)

1. Install **Arduino IDE 2.x** (or `arduino-cli`).
2. Under **Preferences -> Additional Boards Manager URLs**, add:
   ```text
   https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
   ```
3. In **Boards Manager**, install **`Seeed nRF52 Boards`** (select board: **`Seeed XIAO nRF52840`** — *not* the `mbed` variant, so `Bluefruit52Lib` and `InternalFileSytem` are included).
4. In **Library Manager**, install **`Adafruit Sharp Memory Display`** (and its `Adafruit GFX` dependency).
5. Open `firmware/gummybear_watch/gummybear_watch.ino` and click **Upload** over USB-C.
6. After recording a test walk/run, sync straight to your Mac & Strava:
   ```bash
   pip install pyserial
   python3 -m gummybear sync --upload
   ```
