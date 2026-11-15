#ifndef GUMMYBEAR_PROTOCOL_H
#define GUMMYBEAR_PROTOCOL_H

#include <stdint.h>

/*
 * Shared binary wire format between Seeed XIAO nRF52840 firmware (little-endian ARM)
 * and the macOS Python ingestion pipeline (`gummybear/binary.py`).
 */

#define GMY_MAGIC "GMY1"
#define GMY_FW_MAJOR 0
#define GMY_FW_MINOR 1
#define GMY_UNCLOSED_COUNT 0xFFFFFFFFu

#define GMY_FLAG_SAT_MASK 0x3Fu  // bits 0..5: satellite count (0..63)
#define GMY_FLAG_PAUSED   0x40u  // bit 6: timer paused
#define GMY_FLAG_HR_VALID 0x80u  // bit 7: BLE Garmin chest strap connected & valid

// 16-byte file header written at start of run; sample_count & payload_crc32
// are finalized on BTN_STOP (or left as GMY_UNCLOSED_COUNT if battery dies mid-ultra).
typedef struct __attribute__((packed)) {
    char     magic[4];       // "GMY1"
    uint8_t  fw_major;       // 0
    uint8_t  fw_minor;       // 1
    uint16_t start_batt_mv;  // Battery voltage at run start in millivolts (e.g. 4150)
    uint32_t sample_count;   // Number of RunSample records, or 0xFFFFFFFF if unclosed
    uint32_t payload_crc32;  // IEEE CRC-32 of all RunSample bytes, or 0 if unclosed
} GmyFileHeader;

// 20-byte 1 Hz telemetry sample (72 KB / hour -> ~28 hours raw on 2 MB QSPI flash)
typedef struct __attribute__((packed)) {
    uint32_t unix_ts;        // 4B: UTC epoch seconds from GPS
    int32_t  lat_e7;         // 4B: Latitude * 1e7 (~1.1 cm resolution)
    int32_t  lon_e7;         // 4B: Longitude * 1e7
    int16_t  alt_dm;         // 2B: Altitude above MSL in decimeters (-3276.8m..+3276.7m)
    uint8_t  hdop_x10;       // 1B: Horizontal dilution of precision * 10 (e.g. 12 -> 1.2)
    uint8_t  sat_flags;      // 1B: [bits 0..5 sats] [bit 6 paused] [bit 7 hr_valid]
    uint8_t  hr_bpm;         // 1B: Heart rate BPM from BLE 0x180D (0 if invalid)
    uint16_t rr_ms;          // 2B: Latest chest-strap R-R interval in milliseconds (0 if none)
    uint8_t  crc8;           // 1B: CRC-8 (poly 0x07, init 0x00) over first 19 bytes
} GmyRunSample;

static inline uint8_t gmy_crc8(const uint8_t *data, uint32_t len) {
    uint8_t crc = 0x00;
    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t b = 0; b < 8; b++) {
            crc = (crc & 0x80u) ? (uint8_t)((crc << 1) ^ 0x07u) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

#endif // GUMMYBEAR_PROTOCOL_H
