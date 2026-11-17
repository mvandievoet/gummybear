/*
 * Gummybear Casio W-218H Running Watch Firmware
 * Target Board: Seeed Studio XIAO nRF52840 (Board Package: Seeed nRF52 Boards)
 *
 * Display Toggle:
 *   - DISPLAY_USE_OLED = 1 (default): 0.96" 128x64 I2C OLED (SSD1306, 27x27mm, 4 wires).
 *     Auto-sleeps after 8s on everyday Clock screen (zero dark-room glow) and stays
 *     Always-On during PRE_RUN / RUNNING / PAUSED. Also boots cleanly if NO display is
 *     wired yet during Prototype Step #1!
 *   - DISPLAY_USE_OLED = 0: nice!view 160x68 SPI Sharp Memory LCD (LS011B7DH03, 5 wires).
 */

#define DISPLAY_USE_OLED 1

#include <Arduino.h>
#include <bluefruit.h>
#include <Adafruit_LittleFS.h>
#include <InternalFileSystem.h>
#include <Adafruit_GFX.h>

#if DISPLAY_USE_OLED
#include <Wire.h>
#include <Adafruit_SSD1306.h>
#else
#include <SPI.h>
#include <Adafruit_SharpMem.h>
#endif

extern "C" {
#include "../include/gummybear_protocol.h"
#include "../include/ble_hr_parser.h"
#include "../include/nmea_parser.h"
#include "../include/timezone_dst.h"
#include "../include/watch_state.h"
}

using namespace Adafruit_LittleFS_Namespace;

// ---- Pin Map (Seeed Studio XIAO nRF52840) ----
// Note: I2C OLED uses D4 (SDA) and D5 (SCL), so buttons use D1, D2, D3 on both setups!
static const uint8_t PIN_GPS_PWR_EN = D0; // P-Channel MOSFET gate: LOW = ON, HIGH = OFF (0 uA)
static const uint8_t PIN_BTN_MODE   = D1; // Bottom-Left : Clock <-> Pre-Run / Hold 2s Paused = Delete
static const uint8_t PIN_BTN_START  = D2; // Bottom-Right: Start / Pause / Resume / Wake Clock
static const uint8_t PIN_BTN_STOP   = D3; // Top-Left    : Save (Paused) / Hold 2s Clock = Cycle Zone
// D4 = I2C SDA (OLED)   |   D5 = I2C SCL (OLED)
// D6 = GPS UART TX      |   D7 = GPS UART RX
// D8 = SPI SCK (nice!view), D9 = nice!view CS, D10 = SPI MOSI (nice!view)
static const uint8_t PIN_NICEVIEW_CS = D9;

#ifndef PIN_VBAT
#define PIN_VBAT        P0_31
#define PIN_VBAT_ENABLE P0_14
#define PIN_CHG_CURR    P0_13
#endif

// ---- Display Driver Instance ----
#if DISPLAY_USE_OLED
static const uint16_t SCREEN_W = 128;
static const uint16_t SCREEN_H = 64;
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
#define FG_COLOR SSD1306_WHITE
static bool     g_display_ok = false;
static bool     g_oled_awake = true;
static uint32_t g_oled_wake_ms = 0;
static const uint32_t OLED_CLOCK_AWAKE_MS = 8000UL; // Sleep after 8s on Clock screen (zero night glow)
#else
static const uint16_t SCREEN_W = 160;
static const uint16_t SCREEN_H = 68;
Adafruit_SharpMem display(&SPI, PIN_NICEVIEW_CS, SCREEN_W, SCREEN_H);
#define FG_COLOR 0
static bool g_display_ok = true;
#endif

// ---- BLE Heart Rate Client (Standard 0x180D / 0x2A37 Chest Strap or Armband) ----
BLEClientService        hrService(UUID16_SVC_HEART_RATE);
BLEClientCharacteristic hrMeasChar(UUID16_CHR_HEART_RATE_MEASUREMENT);

static volatile BleHrReading g_hr = {false, 0, 0, 0, {0, 0, 0, 0}};
static volatile uint32_t     g_last_hr_ms = 0;

// ---- GPS, Timekeeping & Run Session State ----
static NmeaGpsState g_gps;
static WatchSession g_session;
static File         g_run_file(InternalFS);
static char         g_active_filename[32] = {0};
static uint16_t     g_run_start_batt_mv = 4100;
static uint32_t     g_last_1hz_ms = 0;

static uint8_t      g_zone_idx = 0; // Default 0 = Pacific Time (auto US DST)
static uint32_t     g_rtc_base_unix_ts = 1794873600UL;
static uint32_t     g_rtc_sync_millis = 0;
static uint16_t     g_unsynced_runs = 0;

static const char *kDowNames[7] = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};

static void set_oled_power(bool awake) {
#if DISPLAY_USE_OLED
    if (!g_display_ok) return;
    if (awake && !g_oled_awake) {
        display.ssd1306_command(SSD1306_DISPLAYON);
        g_oled_awake = true;
    } else if (!awake && g_oled_awake) {
        display.clearDisplay();
        display.display();
        display.ssd1306_command(SSD1306_DISPLAYOFF);
        g_oled_awake = false;
    }
    if (awake) {
        g_oled_wake_ms = millis();
    }
#else
    (void)awake;
#endif
}

static void flush_display() {
    if (!g_display_ok) return;
#if DISPLAY_USE_OLED
    if (g_oled_awake) display.display();
#else
    display.refresh();
#endif
}

// ---- Time & Config Persistence ----
static uint32_t current_utc_ts() {
    if (g_gps.unix_ts > 1700000000UL) {
        g_rtc_base_unix_ts = g_gps.unix_ts;
        g_rtc_sync_millis = millis();
    }
    return g_rtc_base_unix_ts + ((millis() - g_rtc_sync_millis) / 1000UL);
}

static void save_zone_config() {
    File f = InternalFS.open("/tz.cfg", FILE_O_WRITE);
    if (f) {
        f.seek(0);
        f.write(&g_zone_idx, 1);
        f.close();
    }
}

static void load_zone_config() {
    File f = InternalFS.open("/tz.cfg", FILE_O_READ);
    if (f) {
        uint8_t z = 0;
        if (f.read(&z, 1) == 1 && z < NUM_TRAVEL_ZONES) {
            g_zone_idx = z;
        }
        f.close();
    }
}

static uint16_t count_unsynced_runs() {
    uint16_t count = 0;
    File dir = InternalFS.open("/runs");
    if (dir) {
        File entry = dir.openNextFile();
        while (entry) {
            if (!entry.isDirectory()) count++;
            entry.close();
            entry = dir.openNextFile();
        }
        dir.close();
    }
    return count;
}

// ---- Power & Battery Helpers ----
static uint16_t read_battery_mv() {
    pinMode(PIN_VBAT_ENABLE, OUTPUT);
    digitalWrite(PIN_VBAT_ENABLE, LOW);
    delayMicroseconds(500);
    analogReadResolution(12);
    uint32_t raw = analogRead(PIN_VBAT);
    digitalWrite(PIN_VBAT_ENABLE, HIGH);
    return (uint16_t)((raw * 2640UL) / 1000UL);
}

static void set_gps_power(bool enable) {
    if (enable) {
        pinMode(PIN_GPS_PWR_EN, OUTPUT);
        digitalWrite(PIN_GPS_PWR_EN, LOW); // Pull P-MOSFET gate LOW -> GPS VCC ON
        Serial1.begin(9600);
    } else {
        Serial1.end();
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
    g_unsynced_runs = count_unsynced_runs();
}

static void discard_run_file() {
    if (g_run_file) {
        g_run_file.close();
    }
    if (g_active_filename[0] != '\0') {
        InternalFS.remove(g_active_filename);
        g_active_filename[0] = '\0';
    }
    g_unsynced_runs = count_unsynced_runs();
}

static void render_screen();

// ---- Shared Action Triggers (Callable from Physical Buttons OR USB Serial Bench Test!) ----
static void action_enter_prerun() {
    g_session.mode = WATCH_STATE_PRE_RUN;
    set_oled_power(true);
    set_gps_power(true);
    set_ble_scanning(true);
    render_screen();
}

static void action_return_clock() {
    g_session.mode = WATCH_STATE_CLOCK;
    set_gps_power(false);
    set_ble_scanning(false);
    set_oled_power(true);
    render_screen();
}

static void action_start_run() {
    watch_start_run(&g_session);
    open_new_run_file();
    set_oled_power(true);
    render_screen();
}

// ---- USB Serial Sync & Step #1 Bench-Test Shell ----
static void poll_usb_commands() {
    if (!Serial.available()) return;
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;

    if (line == "PING") {
        Serial.println("PONG GUMMYBEAR_0.2");
    } else if (line == "STATUS") {
        bool hr_fresh = (millis() - g_last_hr_ms) < 5000UL && g_hr.valid;
        Serial.print("MODE=");
        Serial.print((int)g_session.mode);
        Serial.print(" GPS_FIX=");
        Serial.print(g_gps.has_fix ? 1 : 0);
        Serial.print(" SATS=");
        Serial.print(g_gps.sat_count);
        Serial.print(" HR_BPM=");
        Serial.print(hr_fresh ? g_hr.bpm : 0);
        Serial.print(" RR_MS=");
        Serial.print(hr_fresh ? g_hr.latest_rr_ms : 0);
        Serial.print(" SAMPLES=");
        Serial.print(g_session.sample_count);
        Serial.print(" UNSYNCED=");
        Serial.println(g_unsynced_runs);
    } else if (line.startsWith("TIME ")) {
        uint32_t ts = (uint32_t)strtoul(line.substring(5).c_str(), NULL, 10);
        if (ts > 1700000000UL) {
            g_rtc_base_unix_ts = ts;
            g_rtc_sync_millis = millis();
            Serial.println("OK TIME_SET");
        }
    } else if (line == "MODE") {
        if (g_session.mode == WATCH_STATE_CLOCK) action_enter_prerun();
        else if (g_session.mode == WATCH_STATE_PRE_RUN) action_return_clock();
        Serial.println("OK MODE");
    } else if (line == "START") {
        if (g_session.mode == WATCH_STATE_CLOCK) action_enter_prerun();
        if (g_session.mode == WATCH_STATE_PRE_RUN) action_start_run();
        else if (g_session.mode == WATCH_STATE_PAUSED) {
            g_session.mode = WATCH_STATE_RUNNING;
            render_screen();
        }
        Serial.println("OK START");
    } else if (line == "PAUSE") {
        if (g_session.mode == WATCH_STATE_RUNNING) {
            g_session.mode = WATCH_STATE_PAUSED;
            render_screen();
        }
        Serial.println("OK PAUSE");
    } else if (line == "SAVE") {
        if (g_session.mode == WATCH_STATE_RUNNING || g_session.mode == WATCH_STATE_PAUSED) {
            finalize_run_file();
            action_return_clock();
        }
        Serial.println("OK SAVED");
    } else if (line == "DISCARD") {
        if (g_session.mode == WATCH_STATE_RUNNING || g_session.mode == WATCH_STATE_PAUSED) {
            discard_run_file();
            action_return_clock();
        }
        Serial.println("OK DISCARDED");
    } else if (line == "LIST" && g_session.mode == WATCH_STATE_CLOCK) {
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
    } else if (line.startsWith("GET ") && g_session.mode == WATCH_STATE_CLOCK) {
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
    } else if (line.startsWith("DEL ") && g_session.mode == WATCH_STATE_CLOCK) {
        String fname = String("/runs/") + line.substring(4);
        if (InternalFS.remove(fname.c_str())) {
            g_unsynced_runs = count_unsynced_runs();
            Serial.println("OK");
        } else {
            Serial.println("ERR REMOVE_FAILED");
        }
    }
}

// ---- Screen Renderer (Sized cleanly for 128x64 OLED and 160x68 nice!view) ----
static void render_screen() {
    if (!g_display_ok) return;
#if DISPLAY_USE_OLED
    if (!g_oled_awake) return;
#endif

    display.clearDisplay();
    display.setTextColor(FG_COLOR);

    bool hr_fresh = (millis() - g_last_hr_ms) < 5000UL && g_hr.valid;

    if (g_session.mode == WATCH_STATE_CLOCK) {
        LocalDateTime ldt;
        utc_to_local_datetime(current_utc_ts(), g_zone_idx, &ldt);

        display.setTextSize(1);
        display.setCursor(2, 2);
        char top_bar[24];
        snprintf(
            top_bar,
            sizeof(top_bar),
            "%s %02u/%02u  %s%s",
            kDowNames[ldt.dow % 7],
            ldt.month,
            ldt.day,
            kTravelZones[g_zone_idx].label,
            ldt.is_dst ? "+" : ""
        );
        display.print(top_bar);

        display.setTextSize(3);
        display.setCursor(8, 18);
        char clk[12];
        snprintf(clk, sizeof(clk), "%02u:%02u", ldt.hour, ldt.min);
        display.print(clk);

        display.setTextSize(1);
        display.setCursor(2, 52);
        uint16_t mv = read_battery_mv();
        char bot_bar[24];
        snprintf(
            bot_bar,
            sizeof(bot_bar),
            "%.2fV    %u RUN%s",
            mv / 1000.0f,
            g_unsynced_runs,
            (g_unsynced_runs == 1) ? "" : "S"
        );
        display.print(bot_bar);
    } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
        display.setTextSize(1);
        display.setCursor(2, 2);
        display.print("READY - LOCKING");

        display.setTextSize(2);
        display.setCursor(2, 18);
        display.print(g_gps.has_fix ? "GPS:OK " : "GPS:..");
        display.setTextSize(1);
        display.print(g_gps.sat_count);

        display.setTextSize(2);
        display.setCursor(2, 42);
        display.print("HR :");
        if (hr_fresh) display.print(g_hr.bpm);
        else display.print("---");
    } else {
        // RUNNING or PAUSED (128x64 compact layout)
        display.setTextSize(2);
        display.setCursor(2, 4);
        char pace_buf[10];
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

        display.setCursor(68, 4);
        display.print(g_session.cum_dist_m / 1000.0, 2);

        display.drawFastHLine(0, 28, SCREEN_W, FG_COLOR);

        if (g_session.mode == WATCH_STATE_PAUSED) {
            display.setTextSize(1);
            display.setCursor(2, 34);
            display.print("PAUSED: [TL]=SAVE");
            display.setCursor(2, 48);
            display.print("[BR]=GO HOLD[BL]=DEL");
        } else {
            display.setTextSize(2);
            display.setCursor(2, 38);
            if (hr_fresh) display.print(g_hr.bpm);
            else display.print("---");

            display.setCursor(54, 38);
            char t_buf[12];
            uint32_t m = g_session.timer_s / 60;
            uint32_t s = g_session.timer_s % 60;
            snprintf(t_buf, sizeof(t_buf), "%02lu:%02lu", (unsigned long)m, (unsigned long)s);
            display.print(t_buf);
        }
    }

    flush_display();
}

// ---- Debounced Button Helpers ----
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

static bool button_held_2s(uint8_t pin, uint8_t idx) {
    static uint32_t down_since[2] = {0, 0};
    static bool     fired[2] = {false, false};
    bool down = !digitalRead(pin);
    uint32_t now = millis();
    if (!down) {
        down_since[idx] = 0;
        fired[idx] = false;
        return false;
    }
    if (down_since[idx] == 0) {
        down_since[idx] = now;
        return false;
    }
    if (!fired[idx] && (now - down_since[idx] >= 2000UL)) {
        fired[idx] = true;
        return true;
    }
    return false;
}

void setup() {
    pinMode(PIN_CHG_CURR, OUTPUT);
    digitalWrite(PIN_CHG_CURR, LOW); // 100 mA charge current

    pinMode(PIN_BTN_START, INPUT_PULLUP);
    pinMode(PIN_BTN_STOP, INPUT_PULLUP);
    pinMode(PIN_BTN_MODE, INPUT_PULLUP);

    Serial.begin(115200);
    InternalFS.begin();
    load_zone_config();
    g_unsynced_runs = count_unsynced_runs();

#if DISPLAY_USE_OLED
    Wire.begin();
    g_display_ok = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
    g_oled_wake_ms = millis();
#else
    display.begin();
    g_display_ok = true;
#endif

    nmea_init(&g_gps);
    watch_session_init(&g_session);
    set_gps_power(false);

    Bluefruit.begin(0, 1);
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
    if (g_session.mode != WATCH_STATE_CLOCK) {
        while (Serial1.available()) {
            nmea_feed_char(&g_gps, (char)Serial1.read());
        }
    }
    poll_usb_commands();

#if DISPLAY_USE_OLED
    // Auto-sleep OLED after 8 seconds on Clock screen so watch never glows in dark rooms
    if (g_session.mode == WATCH_STATE_CLOCK && g_oled_awake &&
        (millis() - g_oled_wake_ms >= OLED_CLOCK_AWAKE_MS)) {
        set_oled_power(false);
    }
#endif

    // Hold Top-Left 2s on CLOCK -> Cycle travel timezone
    if (g_session.mode == WATCH_STATE_CLOCK && button_held_2s(PIN_BTN_STOP, 0)) {
        set_oled_power(true);
        g_zone_idx = (g_zone_idx + 1) % NUM_TRAVEL_ZONES;
        save_zone_config();
        render_screen();
    }

    // Hold Bottom-Left 2s when PAUSED -> DELETE / Discard junk run
    if (g_session.mode == WATCH_STATE_PAUSED && button_held_2s(PIN_BTN_MODE, 1)) {
        discard_run_file();
        action_return_clock();
    }

    // Bottom-Left short press: Wake Clock or Toggle Clock <-> Pre-Run
    if (button_pressed_edge(PIN_BTN_MODE, 0)) {
        if (g_session.mode == WATCH_STATE_CLOCK) {
#if DISPLAY_USE_OLED
            if (!g_oled_awake) {
                set_oled_power(true);
                render_screen();
            } else
#endif
            {
                action_enter_prerun();
            }
        } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
            action_return_clock();
        }
    }

    // Bottom-Right short press: Wake Clock (in Clock mode) or Start / Pause / Resume
    if (button_pressed_edge(PIN_BTN_START, 1)) {
        if (g_session.mode == WATCH_STATE_CLOCK) {
            set_oled_power(true);
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
            action_start_run();
        } else if (g_session.mode == WATCH_STATE_RUNNING) {
            g_session.mode = WATCH_STATE_PAUSED;
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PAUSED) {
            g_session.mode = WATCH_STATE_RUNNING;
            render_screen();
        }
    }

    // Top-Left short press: Wake Clock or SAVE run (only unlocked while PAUSED)
    if (button_pressed_edge(PIN_BTN_STOP, 2)) {
        if (g_session.mode == WATCH_STATE_CLOCK) {
            set_oled_power(true);
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PAUSED) {
            finalize_run_file();
            action_return_clock();
        }
    }

    // 1 Hz telemetry tick
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
            if (watch_tick_1hz_ex(&g_session, &g_gps, &hr_snap, hr_fresh, current_utc_ts(), &sample) &&
                g_run_file) {
                g_run_file.write((const uint8_t *)&sample, sizeof(sample));
                if ((g_session.sample_count % 5u) == 0u) {
                    g_run_file.flush();
                }
            }
            // Print live heartbeat + GPS status to laptop terminal if USB-C connected during bench testing!
            if (Serial) {
                Serial.print("[TICK] t=");
                Serial.print(g_session.timer_s);
                Serial.print("s hr=");
                Serial.print(hr_fresh ? g_hr.bpm : 0);
                Serial.print(" rr=");
                Serial.print(hr_fresh ? g_hr.latest_rr_ms : 0);
                Serial.print("ms sats=");
                Serial.println(g_gps.sat_count);
            }
            render_screen();
        } else if (g_session.mode == WATCH_STATE_PRE_RUN) {
            if (Serial) {
                bool hr_fresh = (now - g_last_hr_ms) < 5000UL;
                Serial.print("[READY] gps_fix=");
                Serial.print(g_gps.has_fix ? 1 : 0);
                Serial.print(" sats=");
                Serial.print(g_gps.sat_count);
                Serial.print(" hr=");
                Serial.println(hr_fresh ? g_hr.bpm : 0);
            }
            render_screen();
        } else if ((now / 1000UL) % 30UL == 0UL) {
            render_screen();
        }
    }

    delay(15);
}
