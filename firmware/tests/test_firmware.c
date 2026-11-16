#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#include "../include/ble_hr_parser.h"
#include "../include/gummybear_protocol.h"
#include "../include/nmea_parser.h"
#include "../include/timezone_dst.h"
#include "../include/watch_state.h"

static void feed_str(NmeaGpsState *gps, const char *s) {
    while (*s) {
        nmea_feed_char(gps, *s++);
    }
}

// Compute NMEA *XX checksum and format sentence into buffer
static void build_nmea(char *out, size_t cap, const char *body) {
    uint8_t x = 0;
    for (const char *p = body; *p; p++) x ^= (uint8_t)(*p);
    snprintf(out, cap, "$%s*%02X\r\n", body, x);
}

_Static_assert(sizeof(GmyFileHeader) == 16, "GmyFileHeader must be exactly 16 bytes");
_Static_assert(sizeof(GmyRunSample) == 20, "GmyRunSample must be exactly 20 bytes");

static void test_struct_packing(void) {
    assert(sizeof(GmyFileHeader) == 16);
    assert(sizeof(GmyRunSample) == 20);
}

static void test_garmin_ble_hr_parser(void) {
    // 1. Standard Garmin HRM packet: flags=0x10 (UINT8 BPM + RR present), BPM=158,
    //    two R-R intervals: 390 ticks (381 ms) and 400 ticks (391 ms)
    const uint8_t pkt1[] = {0x10, 158, 0x86, 0x01, 0x90, 0x01};
    BleHrReading r1;
    assert(parse_ble_hr_measurement(pkt1, sizeof(pkt1), &r1));
    assert(r1.valid);
    assert(r1.bpm == 158);
    assert(r1.rr_count == 2);
    assert(r1.rr_list_ms[0] == 381);
    assert(r1.latest_rr_ms == 391);

    // 2. Packet with 16-bit BPM + Energy Expended + 1 R-R interval (flags=0x19)
    //    BPM=172 (0x00AC), Energy=500 (0x01F4), RR=358 ticks -> 350 ms
    const uint8_t pkt2[] = {0x19, 0xAC, 0x00, 0xF4, 0x01, 0x66, 0x01};
    BleHrReading r2;
    assert(parse_ble_hr_measurement(pkt2, sizeof(pkt2), &r2));
    assert(r2.bpm == 172);
    assert(r2.rr_count == 1);
    assert(r2.latest_rr_ms == 350);
}

static void test_nmea_and_session_export(const char *dump_path) {
    NmeaGpsState gps;
    nmea_init(&gps);

    // Corrupt checksum must be rejected
    assert(!nmea_parse_line(&gps, "$GNRMC,150000.00,A,3747.32800,N,12226.04000,W,7.0,0.0,151126,,,A*00"));
    assert(!gps.has_fix);

    // Valid Pacific Heights coordinate: 37 deg 47.32800' N = 37.7888000, 122 deg 26.04000' W = -122.4340000
    // Date: 15 Nov 2026 15:00:00 UTC -> Unix epoch 1794754800
    char rmc[96], gga[96];
    build_nmea(rmc, sizeof(rmc), "GNRMC,150000.00,A,3747.32800,N,12226.04000,W,7.1,0.0,151126,,,A");
    build_nmea(gga, sizeof(gga), "GNGGA,150000.00,3747.32800,N,12226.04000,W,1,11,1.2,82.4,M,-30.0,M,,");

    feed_str(&gps, rmc);
    feed_str(&gps, gga);

    assert(gps.has_fix);
    assert(gps.unix_ts == 1794754800u);
    assert(gps.lat_e7 == 377888000);
    assert(gps.lon_e7 == -1224340000);
    assert(gps.alt_dm == 824);
    assert(gps.hdop_x10 == 12);
    assert(gps.sat_count == 11);

    // Simulate 5-second watch recording and write binary .gmy file for Python interop check
    WatchSession ws;
    watch_session_init(&ws);
    watch_start_run(&ws);

    BleHrReading hr = {true, 154, 390, 1, {390, 0, 0, 0}};
    GmyRunSample samples[5];
    for (int i = 0; i < 5; i++) {
        gps.unix_ts = 1794754800u + (uint32_t)i;
        gps.lat_e7 = 377888000 + i * 320; // ~3.5 m/s north
        assert(watch_tick_1hz(&ws, &gps, &hr, true, &samples[i]));
    }
    assert(ws.sample_count == 5);
    assert(ws.cum_dist_m > 12.0 && ws.cum_dist_m < 16.0);
    assert(ws.live_pace_sec_km > 250 && ws.live_pace_sec_km < 310);

    if (dump_path) {
        GmyFileHeader hdr;
        watch_build_header(&ws, 4135, true, &hdr);
        FILE *fp = fopen(dump_path, "wb");
        assert(fp != NULL);
        assert(fwrite(&hdr, sizeof(hdr), 1, fp) == 1);
        assert(fwrite(samples, sizeof(GmyRunSample), 5, fp) == 5);
        fclose(fp);
    }
}

static void test_dst_transitions(void) {
    LocalDateTime ldt;
    // SF in July (PDT = UTC-7): 2026-07-15 15:00 UTC -> 08:00 local, DST=true
    utc_to_local_datetime(utc_to_unix_ts(2026, 7, 15, 15, 0, 0), 0, &ldt);
    assert(ldt.is_dst == true);
    assert(ldt.hour == 8);

    // SF in November after Fall Back (PST = UTC-8): 2026-11-15 15:00 UTC -> 07:00 local, DST=false
    utc_to_local_datetime(utc_to_unix_ts(2026, 11, 15, 15, 0, 0), 0, &ldt);
    assert(ldt.is_dst == false);
    assert(ldt.hour == 7);

    // Brussels in June (CEST = UTC+2): 2027-06-10 12:00 UTC -> 14:00 local, DST=true
    utc_to_local_datetime(utc_to_unix_ts(2027, 6, 10, 12, 0, 0), 5, &ldt);
    assert(ldt.is_dst == true);
    assert(ldt.hour == 14);
}

int main(int argc, char **argv) {
    const char *dump_path = (argc > 1) ? argv[1] : NULL;
    test_struct_packing();
    test_garmin_ble_hr_parser();
    test_dst_transitions();
    test_nmea_and_session_export(dump_path);
    printf("All C firmware tests passed!\n");
    return 0;
}
