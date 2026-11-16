/*
 * Gummybear Sleeper Casio W-218H Firmware (Phase 2)
 * Target Board: Seeed Studio XIAO nRF52840 (Board Package: Seeed nRF52 Boards)
 * Libraries   : Bluefruit52Lib (built-in), InternalFileSytem (built-in),
 *               Adafruit_GFX + Adafruit_SharpMem (install via Library Manager)
 */

#include <Arduino.h>
#include <SPI.h>
#include <bluefruit.h>
#include <Adafruit_LittleFS.h>
#include <InternalFileSystem.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SharpMem.h>

extern "C" {
#include "../include/gummybear_protocol.h"
#include "../include/ble_hr_parser.h"
#include "../include/nmea_parser.h"
#include "../include/watch_state.h"
}

using namespace Adafruit_LittleFS_Namespace;

// ---- Pin Map (Matches PROJECT_PLAN.md) ----
static const uint8_t PIN_GPS_PWR_EN = D0; // P-Channel MOSFET gate: LOW = ON, HIGH = OFF (0 uA)
static const uint8_t PIN_DISP_CS    = D1; // nice!view Sharp Memory LCD CS (SCK=D8, MOSI=D10)
static const uint8_t PIN_BTN_START  = D2; // Active-LOW: Start / Pause
static const uint8_t PIN_BTN_STOP   = D3; // Active-LOW: Stop & Save
static const uint8_t PIN_BTN_MODE   = D4; // Active-LOW: Clock <-> Pre-Run Lock

// XIAO nRF52840 onboard battery ADC + charge current control
#ifndef PIN_VBAT
#define PIN_VBAT        P0_31
#define PIN_VBAT_ENABLE P0_14
#define PIN_CHG_CURR    P0_13
#endif

// ---- Display (nice!view 160x68 Sharp LS011B7DH03) ----
Adafruit_SharpMem display(&SPI, PIN_DISP_CS, 160, 68);
#define COLOR_BLACK 0
#define COLOR_WHITE 1

// ---- BLE Heart Rate Client (Garmin Chest Strap 0x180D / 0x2A37) ----
BLEClientService        hrService(UUID16_SVC_HEART_RATE);
BLEClientCharacteristic hrMeasChar(UUID16_CHR_HEART_RATE_MEASUREMENT);

static volatile BleHrReading g_hr = {false, 0, 0, 0, {0, 0, 0, 0}};
static volatile uint32_t     g_last_hr_ms = 0;

// ---- GPS & Run Session State ----
static NmeaGpsState g_gps;
static WatchSession g_session;
static File         g_run_file(InternalFS);
static char         g_active_filename[32] = {0};
static uint16_t     g_run_start_batt_mv = 4100;
static uint32_t     g_last_1hz_ms = 0;

// ---- Power & Battery Helpers ----
static uint16_t read_battery_mv() {
    pinMode(PIN_VBAT_ENABLE, OUTPUT);
    digitalWrite(PIN_VBAT_ENABLE, LOW); // Enable divider
    delayMicroseconds(500);
    analogReadResolution(12);
    uint32_t raw = analogRead(PIN_VBAT);
    digitalWrite(PIN_VBAT_ENABLE, HIGH); // Disable divider to save power
    // XIAO nRF52840 divider ratio ~ 1510/510 (~2.961x) with 3.6V internal ref -> ~2.64 mV/LSB
    return (uint16_t)((raw * 2640UL) / 1000UL);
}

static void set_gps_power(bool enable) {
    if (enable) {
        pinMode(PIN_GPS_PWR_EN, OUTPUT);
        digitalWrite(PIN_GPS_PWR_EN, LOW); // Pull P-MOSFET gate LOW -> GPS VCC ON
        Serial1.begin(9600);               // GM10 Nano V3.1 default UART baud (or 115200)
    } else {
        Serial1.end();
        // Pull TX/RX LOW before cutting VCC so GPS does not draw phantom power via ESD diodes
        pinMode(D6, OUTPUT);
        pinMode(D7, OUTPUT);
        digitalWrite(D6, LOW);
        digitalWrite(D7, LOW);
        pinMode(PIN_GPS_PWR_EN, OUTPUT);
        digitalWrite(PIN_GPS_PWR_EN, HIGH); // Pull P-MOSFET gate HIGH -> 0.000 mA
        g_gps.has_fix = false;
    }
}

// ---- BLE Callbacks ----
static void hr_notify_callback(BLEClientCharacteristic *chr, uint8_t *data, uint16_t len) {
    (void)chr;
    BleHrReading parsed;
    if (parse_ble_hr_measurement(data, len, &parsed)) {
        g_hr.valid = parsed.valid;
        g_hr.bpm = parsed.bpm;
        if (parsed.latest_rr_ms > 0) {
            g_hr.latest_rr_ms = parsed.latest_rr_ms;
        }
        g_last_hr_ms = millis();
    }
}

static void scan_callback(ble_gap_evt_adv_report_t *report) {
    if (Bluefruit.Scanner.checkReportForService(report, hrService)) {
        Bluefruit.Central.connect(report);
    } else {
        Bluefruit.Scanner.resume();
    }
}

static void connect_callback(uint16_t conn_handle) {
    if (!hrService.discover(conn_handle)) {
        Bluefruit.disconnect(conn_handle);
        return;
    }
    if (!hrMeasChar.discover()) {
        Bluefruit.disconnect(conn_handle);
        return;
    }
    hrMeasChar.enableNotify();
}

static void disconnect_callback(uint16_t conn_handle, uint8_t reason) {
    (void)conn_handle;
    (void)reason;
    g_hr.valid = false;
}

static void set_ble_scanning(bool enable) {
    if (enable) {
        if (!Bluefruit.Central.connected()) {
            Bluefruit.Scanner.start(0);
        }
    } else {
        Bluefruit.Scanner.stop();
        if (Bluefruit.Central.connected()) {
            Bluefruit.disconnect(Bluefruit.connHandle());
        }
        g_hr.valid = false;
    }
}

// ---- LittleFS Run File Management ----
static bool open_new_run_file() {
    InternalFS.mkdir("/runs");
    for (uint16_t idx = 1; idx < 9999; idx++) {
        snprintf(g_active_filename, sizeof(g_active_filename), "/runs/run_%04u.gmy", idx);
        if (!InternalFS.exists(g_active_filename)) {
            if (!g_run_file.open(g_active_filename, FILE_O_WRITE)) return false;
            GmyFileHeader unclosed_hdr;
            g_run_start_batt_mv = read_battery_mv();
            watch_build_header(&g_session, g_run_start_batt_mv, false, &unclosed_hdr);
            g_run_file.write((const uint8_t *)&unclosed_hdr, sizeof(unclosed_hdr));
            g_run_file.flush();
            return true;
        }
    }
    return false;
}

static void finalize_run_file() {
    if (!g_run_file) return;
    GmyFileHeader final_hdr;
    watch_build_header(&g_session, g_run_start_batt_mv, true, &final_hdr);
    g_run_file.seek(0);
    g_run_file.write((const uint8_t *)&final_hdr, sizeof(final_hdr));
    g_run_file.flush();
    g_run_file.close();
}

// ---- USB Serial Sync Shell (`python3 -m gummybear sync`) ----
static void poll_usb_sync_commands() {
    if (!Serial.available()) return;
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line == "PING") {
        Serial.println("PONG GUMMYBEAR_0.1");
    } else if (line == "LIST") {
        File dir = InternalFS.open("/runs");
        if (dir) {
            File entry = dir.openNextFile();
            while (entry) {
                if (!entry.isDirectory()) {
                    Serial.print("FILE ");
                    Serial.print(entry.name());
                    Serial.print(" ");
                    Serial.println((uint32_t)entry.size());
                }
                entry.close();
                entry = dir.openNextFile();
            }
            dir.close();
        }
        Serial.println("END");
    } else if (line.startsWith("GET ")) {
        String fname = String("/runs/") + line.substring(4);
        File f = InternalFS.open(fname.c_str(), FILE_O_READ);
        if (!f) {
            Serial.println("ERR NOT_FOUND");
            return;
        }
        uint32_t sz = (uint32_t)f.size();
        Serial.print("DATA ");
        Serial.println(sz);
        uint8_t buf[64];
        while (f.available()) {
            int n = f.read(buf, sizeof(buf));
            if (n > 0) Serial.write(buf, (size_t)n);
        }
        f.close();
    } else if (line.startsWith("DEL ")) {
        String fname = String("/runs/") + line.substring(4);
        if (InternalFS.remove(fname.c_str())) {
            Serial.println("OK");
        } else {
            Serial.println("ERR REMOVE_FAILED");
        }
    }
}

// ---- Minimal Sunlight Casio Screen Renderer (160x68) ----
static void render_screen() {
    display.clearDisplay();
    display.setTextColor(COLOR_BLACK);

    bool hr_fresh = (millis() - g_last_hr_ms) < 5000UL && g_hr.valid;

    if (g_session.mode == WATCH_STATE_CLOCK) {
        display.setTextSize(3);
        display.setCursor(14, 12);
        char clk[16];
        snprintf(clk, sizeof(clk), "%02u:%02u", g_gps.utc_hour, g_gps.utc_min);
        display.print(clk);

        display.setTextSize(1);
        display.setCursor(14, 48);
        uint16_t mv = read_battery_mv();
        display.print("CASIO W-218H  ");
        display.print(mv / 1000.0f, 2);
        display.print("V");
    } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
        display.setTextSize(1);
        display.setCursor(6, 6);
        display.print("READY - ACQUIRING");

        display.setTextSize(2);
        display.setCursor(6, 24);
        display.print(g_gps.has_fix ? "GPS: OK " : "GPS: ...");
        display.setTextSize(1);
        display.print(g_gps.sat_count);

        display.setTextSize(2);
        display.setCursor(6, 46);
        display.print("HR : ");
        if (hr_fresh) display.print(g_hr.bpm);
        else display.print("---");
    } else {
        // RUNNING or PAUSED: Single glanceable split layout
        // Top row: Pace (left) | Distance km (right)
        display.setTextSize(2);
        display.setCursor(4, 6);
        char pace_buf[12];
        if (g_session.live_pace_sec_km > 0) {
            snprintf(
                pace_buf,
                sizeof(pace_buf),
                "%u:%02u",
                g_session.live_pace_sec_km / 60,
                g_session.live_pace_sec_km % 60
            );
        } else {
            snprintf(pace_buf, sizeof(pace_buf), "--:--");
        }
        display.print(pace_buf);

        display.setCursor(82, 6);
        display.print(g_session.cum_dist_m / 1000.0, 2);
        display.setTextSize(1);
        display.print("k");

        display.drawFastHLine(0, 32, 160, COLOR_BLACK);

        // Bottom row: Live HR (left) | Timer (right)
        display.setTextSize(2);
        display.setCursor(4, 42);
        if (hr_fresh) display.print(g_hr.bpm);
        else display.print("---");
        display.setTextSize(1);
        display.print("bpm");

        display.setTextSize(2);
        display.setCursor(74, 42);
        if (g_session.mode == WATCH_STATE_PAUSED) {
            display.print("PAUS");
        } else {
            char t_buf[12];
            uint32_t m = g_session.timer_s / 60;
            uint32_t s = g_session.timer_s % 60;
            snprintf(t_buf, sizeof(t_buf), "%02lu:%02lu", (unsigned long)m, (unsigned long)s);
            display.print(t_buf);
        }
    }

    display.refresh();
}

// ---- Debounced Button Polling ----
static bool button_pressed_edge(uint8_t pin, uint8_t idx) {
    static bool     prev_state[3] = {true, true, true};
    static uint32_t last_ms[3] = {0, 0, 0};
    bool curr = digitalRead(pin);
    uint32_t now = millis();
    if (!curr && prev_state[idx] && (now - last_ms[idx] > 180UL)) {
        prev_state[idx] = curr;
        last_ms[idx] = now;
        return true;
    }
    prev_state[idx] = curr;
    return false;
}

void setup() {
    // Enable 100 mA LiPo fast-charge on XIAO nRF52840
    pinMode(PIN_CHG_CURR, OUTPUT);
    digitalWrite(PIN_CHG_CURR, LOW);

    pinMode(PIN_BTN_START, INPUT_PULLUP);
    pinMode(PIN_BTN_STOP, INPUT_PULLUP);
    pinMode(PIN_BTN_MODE, INPUT_PULLUP);

    Serial.begin(115200);
    InternalFS.begin();
    display.begin();

    nmea_init(&g_gps);
    watch_session_init(&g_session);
    set_gps_power(false);

    // Initialize BLE Central for Garmin 0x180D Heart Rate Strap
    Bluefruit.begin(0, 1); // 0 peripheral, 1 central
    Bluefruit.setName("Gummybear-W218H");
    hrService.begin();
    hrMeasChar.setNotifyCallback(hr_notify_callback);
    hrMeasChar.begin();

    Bluefruit.Scanner.setRxCallback(scan_callback);
    Bluefruit.Scanner.restartOnDisconnect(true);
    Bluefruit.Scanner.setInterval(160, 80);
    Bluefruit.Scanner.filterUuid(hrService.uuid);
    Bluefruit.Scanner.useActiveScan(false);
    Bluefruit.Central.setConnectCallback(connect_callback);
    Bluefruit.Central.setDisconnectCallback(disconnect_callback);

    render_screen();
}

void loop() {
    // 1. Drain incoming GPS UART bytes
    if (g_session.mode != WATCH_STATE_CLOCK) {
        while (Serial1.available()) {
            nmea_feed_char(&g_gps, (char)Serial1.read());
        }
    }

    // 2. Handle USB-C sync commands when idle
    if (g_session.mode == WATCH_STATE_CLOCK) {
        poll_usb_sync_commands();
    }

    // 3. Button transitions
    if (button_pressed_edge(PIN_BTN_MODE, 0)) {
        if (g_session.mode == WATCH_STATE_CLOCK) {
            g_session.mode = WATCH_STATE_PRE_RUN;
            set_gps_power(true);
            set_ble_scanning(true);
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
            g_session.mode = WATCH_STATE_CLOCK;
            set_gps_power(false);
            set_ble_scanning(false);
            render_screen();
        }
    }

    if (button_pressed_edge(PIN_BTN_START, 1)) {
        if (g_session.mode == WATCH_STATE_PRE_RUN) {
            watch_start_run(&g_session);
            open_new_run_file();
            render_screen();
        } else if (g_session.mode == WATCH_STATE_RUNNING) {
            g_session.mode = WATCH_STATE_PAUSED;
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PAUSED) {
            g_session.mode = WATCH_STATE_RUNNING;
            render_screen();
        }
    }

    if (button_pressed_edge(PIN_BTN_STOP, 2)) {
        if (g_session.mode == WATCH_STATE_PAUSED || g_session.mode == WATCH_STATE_RUNNING) {
            finalize_run_file();
            g_session.mode = WATCH_STATE_CLOCK;
            set_gps_power(false);
            set_ble_scanning(false);
            render_screen();
        }
    }

    // 4. 1 Hz Run Telemetry Tick
    uint32_t now = millis();
    if (now - g_last_1hz_ms >= 1000UL) {
        g_last_1hz_ms = now;
        if (g_session.mode == WATCH_STATE_RUNNING || g_session.mode == WATCH_STATE_PAUSED) {
            bool hr_fresh = (now - g_last_hr_ms) < 5000UL;
            BleHrReading hr_snap;
            hr_snap.valid = g_hr.valid;
            hr_snap.bpm = g_hr.bpm;
            hr_snap.latest_rr_ms = g_hr.latest_rr_ms;

            GmyRunSample sample;
            if (watch_tick_1hz(&g_session, &g_gps, &hr_snap, hr_fresh, &sample) && g_run_file) {
                g_run_file.write((const uint8_t *)&sample, sizeof(sample));
                if ((g_session.sample_count % 5u) == 0u) {
                    g_run_file.flush(); // Crash-safe checkpoint every 5 seconds
                }
            }
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
            render_screen();
        }
    }

    delay(15); // Allow nRF52 SoftDevice idle sleep between events
}
