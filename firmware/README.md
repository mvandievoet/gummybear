# Watch Firmware (`Seeed Studio XIAO nRF52840`)

Embedded C/C++ firmware for the **Casio W-218H** GPS + Bluetooth Heart Rate running watch.

## Dual Display Support (`DISPLAY_USE_OLED`)
At the top of [`gummybear_watch/gummybear_watch.ino`](./gummybear_watch/gummybear_watch.ino):
- **`#define DISPLAY_USE_OLED 1` (Default):** Drives a **`0.96"` `128 × 64` `I2C` OLED (`SSD1306`)** on `D4 (SDA)` / `D5 (SCL)`. Automatically turns the OLED **completely OFF after 8 seconds on the everyday Clock screen** (zero glow in dark rooms/bedrooms, waking on any button tap) while keeping the display **Always-On during runs**. Also boots cleanly with **no screen attached** for Prototype Step #1!
- **`#define DISPLAY_USE_OLED 0`:** Drives the **`nice!view` (`160 × 68` `SPI` Sharp Memory LCD)** on `D8 (SCK)` / `D10 (MOSI)` / `D9 (CS)`.

## Flashing & Running Prototype Step #1 (No Soldering / No GPS Required!)
The minute your DigiKey `XIAO nRF52840` arrives—before wiring a screen, buttons, or GPS:
1. Install **Arduino IDE 2.x** and add the Seeed board URL in **Preferences -> Additional Boards Manager URLs**:
   ```text
   https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
   ```
2. In **Boards Manager**, install **`Seeed nRF52 Boards`** and select **`Seeed XIAO nRF52840`** *(non-mbed variant)*.
3. In **Library Manager**, install **`Adafruit SSD1306`** (plus **`Adafruit Sharp Memory Display`** if testing `nice!view`).
4. Plug `XIAO #1` into USB-C, open `firmware/gummybear_watch/gummybear_watch.ino`, and click **Upload**.
5. Put on your Bluetooth HR strap and run our automated Step #1 bench test from your Mac terminal:
   ```bash
   pip install pyserial
   python3 -m gummybear bench --seconds 30 --upload
   ```
   That syncs your Mac's clock to `XIAO #1`, locks onto your HR strap over Bluetooth, records 30 seconds of live `BPM` + `R-R` intervals onto `XIAO`'s `2 MB` flash, pulls the file back over USB-C, and uploads your live Heart Rate curve to Strava!
