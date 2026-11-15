# Watch Firmware (`Seeed XIAO nRF52840`)

Embedded C/C++ firmware for the sleeper **Casio W-218H** GPS + BLE Heart Rate watch:
- `include/gummybear_protocol.h`: Shared 16-byte header + 20-byte packed 1 Hz sample layout (kept byte-identical with `gummybear/binary.py`).
- Phase 2 target: BLE Central (`0x180D` Garmin chest strap BPM + `R-R` intervals), `GM10 Nano V3` u-blox M10 UART parser, `nice!view` Sharp Memory LCD SPI driver, and LittleFS `.gmy` binary logger.
