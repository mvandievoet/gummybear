#ifndef GUMMYBEAR_WATCH_STATE_H
#define GUMMYBEAR_WATCH_STATE_H

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "ble_hr_parser.h"
#include "gummybear_protocol.h"
#include "nmea_parser.h"

/*
 * Watch UI / Recording State Machine & Live Run Kinematics.
 *
 * Buttons:
 *   - BTN_MODE  : CLOCK_IDLE <-> PRE_RUN_LOCK
 *   - BTN_START : Start recording (from PRE_RUN_LOCK) or Toggle RUNNING <-> PAUSED
 *   - BTN_STOP  : Stop & finalize `.gmy` run file (when PAUSED or held during RUNNING)
 */

typedef enum {
    WATCH_STATE_CLOCK = 0,
    WATCH_STATE_PRE_RUN = 1,
    WATCH_STATE_RUNNING = 2,
    WATCH_STATE_PAUSED = 3
} WatchMode;

typedef struct {
    WatchMode mode;
    uint32_t  timer_s;
    uint32_t  sample_count;
    uint32_t  payload_crc32;
    double    cum_dist_m;
    uint16_t  live_pace_sec_km; // 5-second smoothed live pace for MIP screen

    bool      has_prev_pos;
    int32_t   prev_lat_e7;
    int32_t   prev_lon_e7;
    float     ema_speed_mps;
} WatchSession;

static inline uint32_t gmy_crc32_update(uint32_t crc_inv, const uint8_t *buf, uint32_t len) {
    uint32_t c = crc_inv;
    for (uint32_t i = 0; i < len; i++) {
        c ^= buf[i];
        for (uint8_t k = 0; k < 8; k++) {
            c = (c & 1u) ? ((c >> 1) ^ 0xEDB88320u) : (c >> 1);
        }
    }
    return c;
}

static inline void watch_session_init(WatchSession *ws) {
    memset(ws, 0, sizeof(*ws));
    ws->mode = WATCH_STATE_CLOCK;
    ws->payload_crc32 = 0xFFFFFFFFu;
}

static inline void watch_start_run(WatchSession *ws) {
    ws->mode = WATCH_STATE_RUNNING;
    ws->timer_s = 0;
    ws->sample_count = 0;
    ws->payload_crc32 = 0xFFFFFFFFu;
    ws->cum_dist_m = 0.0;
    ws->live_pace_sec_km = 0;
    ws->has_prev_pos = false;
    ws->ema_speed_mps = 0.0f;
}

// Fast equirectangular step distance in meters between consecutive 1 Hz points
static inline float _step_dist_m(
    int32_t lat1_e7, int32_t lon1_e7, int32_t lat2_e7, int32_t lon2_e7
) {
    const double deg_to_rad = 0.017453292519943295;
    const double earth_r = 6371000.0;
    double dlat = (double)(lat2_e7 - lat1_e7) * 1e-7 * deg_to_rad;
    double dlon = (double)(lon2_e7 - lon1_e7) * 1e-7 * deg_to_rad;
    double mid_lat = (double)(lat1_e7 + lat2_e7) * 0.5e-7 * deg_to_rad;
    double dx = dlon * cos(mid_lat) * earth_r;
    double dy = dlat * earth_r;
    return (float)sqrt(dx * dx + dy * dy);
}

// Build a 20-byte CRC-protected GmyRunSample and update live watch display metrics
static inline bool watch_tick_1hz(
    WatchSession *ws,
    const NmeaGpsState *gps,
    const BleHrReading *hr,
    bool hr_fresh,
    GmyRunSample *out_sample
) {
    if (ws->mode != WATCH_STATE_RUNNING && ws->mode != WATCH_STATE_PAUSED) {
        return false;
    }

    bool paused = (ws->mode == WATCH_STATE_PAUSED);
    if (!paused) {
        ws->timer_s++;
    }

    if (gps->has_fix) {
        if (!paused && ws->has_prev_pos) {
            float d = _step_dist_m(ws->prev_lat_e7, ws->prev_lon_e7, gps->lat_e7, gps->lon_e7);
            // Ignore standing GPS jitter (<0.4 m/s) and teleport spikes (>15 m/s) on live screen
            if (d >= 0.4f && d <= 15.0f) {
                ws->cum_dist_m += d;
                ws->ema_speed_mps = (ws->ema_speed_mps <= 0.1f)
                                        ? d
                                        : (0.25f * d + 0.75f * ws->ema_speed_mps);
            } else if (d < 0.4f) {
                ws->ema_speed_mps *= 0.7f;
            }
            ws->live_pace_sec_km = (ws->ema_speed_mps >= 0.5f)
                                       ? (uint16_t)(1000.0f / ws->ema_speed_mps + 0.5f)
                                       : 0;
        }
        ws->prev_lat_e7 = gps->lat_e7;
        ws->prev_lon_e7 = gps->lon_e7;
        ws->has_prev_pos = true;
    }

    if (!gps->has_fix || gps->unix_ts == 0) {
        return false; // Wait for valid GPS fix before writing flash frame
    }

    uint8_t flags = (gps->sat_count & GMY_FLAG_SAT_MASK);
    if (paused) flags |= GMY_FLAG_PAUSED;
    bool use_hr = (hr_fresh && hr && hr->valid && hr->bpm > 0);
    if (use_hr) flags |= GMY_FLAG_HR_VALID;

    out_sample->unix_ts = gps->unix_ts;
    out_sample->lat_e7 = gps->lat_e7;
    out_sample->lon_e7 = gps->lon_e7;
    out_sample->alt_dm = gps->alt_dm;
    out_sample->hdop_x10 = gps->hdop_x10;
    out_sample->sat_flags = flags;
    out_sample->hr_bpm = use_hr ? hr->bpm : 0;
    out_sample->rr_ms = use_hr ? hr->latest_rr_ms : 0;
    out_sample->crc8 = gmy_crc8((const uint8_t *)out_sample, 19);

    ws->payload_crc32 = gmy_crc32_update(
        ws->payload_crc32, (const uint8_t *)out_sample, sizeof(GmyRunSample)
    );
    ws->sample_count++;
    return true;
}

static inline void watch_build_header(
    const WatchSession *ws, uint16_t start_batt_mv, bool finalized, GmyFileHeader *hdr
) {
    memcpy(hdr->magic, GMY_MAGIC, 4);
    hdr->fw_major = GMY_FW_MAJOR;
    hdr->fw_minor = GMY_FW_MINOR;
    hdr->start_batt_mv = start_batt_mv;
    if (finalized) {
        hdr->sample_count = ws->sample_count;
        hdr->payload_crc32 = ws->payload_crc32 ^ 0xFFFFFFFFu;
    } else {
        hdr->sample_count = GMY_UNCLOSED_COUNT;
        hdr->payload_crc32 = 0;
    }
}

#endif // GUMMYBEAR_WATCH_STATE_H
