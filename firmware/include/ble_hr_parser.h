#ifndef GUMMYBEAR_BLE_HR_PARSER_H
#define GUMMYBEAR_BLE_HR_PARSER_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Parser for Bluetooth SIG Heart Rate Service (0x180D) ->
 * Heart Rate Measurement Characteristic (0x2A37), as broadcast by Garmin
 * HRM-Dual / HRM-Pro chest straps.
 *
 * Spec notes:
 *   - Flag bit 0 (0x01): 0 = UINT8 BPM, 1 = UINT16 BPM
 *   - Flag bit 3 (0x08): Energy Expended (UINT16) present
 *   - Flag bit 4 (0x10): One or more R-R intervals (UINT16 in 1/1024 sec units) present
 */

typedef struct {
    bool     valid;
    uint8_t  bpm;
    uint16_t latest_rr_ms;  // Most recent beat-to-beat interval converted to ms (0 if absent)
    uint8_t  rr_count;      // Number of R-R intervals unpacked from this notification
    uint16_t rr_list_ms[4]; // Up to 4 R-R intervals per 1 Hz notification
} BleHrReading;

static inline bool parse_ble_hr_measurement(
    const uint8_t *buf, uint16_t len, BleHrReading *out
) {
    if (!buf || !out || len < 2) {
        if (out) out->valid = false;
        return false;
    }

    out->valid = false;
    out->bpm = 0;
    out->latest_rr_ms = 0;
    out->rr_count = 0;

    uint8_t flags = buf[0];
    uint16_t idx = 1;

    if (flags & 0x01u) {
        if (idx + 2 > len) return false;
        uint16_t bpm16 = (uint16_t)buf[idx] | ((uint16_t)buf[idx + 1] << 8);
        out->bpm = (bpm16 > 255u) ? 255u : (uint8_t)bpm16;
        idx += 2;
    } else {
        out->bpm = buf[idx];
        idx += 1;
    }

    // Skip optional 2-byte Energy Expended field if present
    if (flags & 0x08u) {
        if (idx + 2 > len) return false;
        idx += 2;
    }

    // Extract optional R-R intervals (encoded in 1/1024 s ticks per Bluetooth GATT spec)
    if (flags & 0x10u) {
        while (idx + 2 <= len) {
            uint16_t raw_1024 = (uint16_t)buf[idx] | ((uint16_t)buf[idx + 1] << 8);
            uint16_t rr_ms = (uint16_t)((((uint32_t)raw_1024 * 1000u) + 512u) >> 10);
            if (rr_ms > 0) {
                out->latest_rr_ms = rr_ms;
                if (out->rr_count < 4) {
                    out->rr_list_ms[out->rr_count] = rr_ms;
                }
                out->rr_count++;
            }
            idx += 2;
        }
    }

    out->valid = (out->bpm > 0);
    return out->valid;
}

#endif // GUMMYBEAR_BLE_HR_PARSER_H
