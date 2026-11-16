#ifndef GUMMYBEAR_NMEA_PARSER_H
#define GUMMYBEAR_NMEA_PARSER_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

/*
 * Zero-allocation NMEA-0183 parser ($GNRMC/$GPRMC + $GNGGA/$GPGGA) for the
 * Flywoo GOKU GM10 Nano V3.1 (u-blox M10050).
 *
 * Uses 64-bit integer fixed-point parsing (`lat_e7`, `lon_e7`) instead of
 * 32-bit `float` to preserve full ~1.1 cm coordinate resolution on Cortex-M4F.
 */

#define NMEA_MAX_LINE 96

typedef struct {
    bool     has_fix;
    uint32_t unix_ts;
    int32_t  lat_e7;
    int32_t  lon_e7;
    int16_t  alt_dm;
    uint8_t  hdop_x10;
    uint8_t  sat_count;
    uint8_t  utc_hour;
    uint8_t  utc_min;
    uint8_t  utc_sec;

    char     line_buf[NMEA_MAX_LINE];
    uint8_t  line_len;
} NmeaGpsState;

static inline void nmea_init(NmeaGpsState *st) {
    memset(st, 0, sizeof(*st));
    st->hdop_x10 = 99;
}

static inline int8_t _hex_nibble(char c) {
    if (c >= '0' && c <= '9') return (int8_t)(c - '0');
    if (c >= 'A' && c <= 'F') return (int8_t)(c - 'A' + 10);
    if (c >= 'a' && c <= 'f') return (int8_t)(c - 'a' + 10);
    return -1;
}

static inline bool nmea_verify_checksum(const char *line) {
    if (!line || line[0] != '$') return false;
    uint8_t xsum = 0;
    const char *p = line + 1;
    while (*p && *p != '*') {
        xsum ^= (uint8_t)(*p);
        p++;
    }
    if (*p != '*') return false;
    int8_t hi = _hex_nibble(p[1]);
    int8_t lo = _hex_nibble(p[2]);
    if (hi < 0 || lo < 0) return false;
    return xsum == (uint8_t)((hi << 4) | lo);
}

// Advance pointer to start of next comma-delimited token (or NULL if at end/*)
static inline const char *_next_field(const char *p) {
    if (!p) return NULL;
    while (*p && *p != ',' && *p != '*') p++;
    return (*p == ',') ? (p + 1) : NULL;
}

// Parse DDMM.MMMMM (or DDDMM.MMMMM) + hemisphere (N/S/E/W) into degrees * 1e7
static inline bool parse_nmea_coord_e7(const char *val, char hemi, int32_t *out_e7) {
    if (!val || !*val || *val == ',' || *val == '*') return false;
    int64_t whole = 0;
    const char *p = val;
    while (*p >= '0' && *p <= '9') {
        whole = whole * 10 + (*p - '0');
        p++;
    }
    int64_t frac_m6 = 0;
    int64_t scale = 1000000LL;
    if (*p == '.') {
        p++;
        while (*p >= '0' && *p <= '9') {
            if (scale >= 10) {
                scale /= 10;
                frac_m6 += (*p - '0') * scale;
            }
            p++;
        }
    }
    int64_t deg = whole / 100;
    int64_t mins = whole % 100;
    int64_t total_micro_min = mins * 1000000LL + frac_m6;
    int64_t e7 = deg * 10000000LL + (total_micro_min + 3LL) / 6LL;
    if (hemi == 'S' || hemi == 'W') e7 = -e7;
    *out_e7 = (int32_t)e7;
    return true;
}

// Howard Hinnant civil-to-days algorithm -> exact UTC Unix epoch seconds
static inline uint32_t utc_to_unix_ts(
    int year, int month, int day, int hour, int min, int sec
) {
    int y = year - (month <= 2 ? 1 : 0);
    int era = (y >= 0 ? y : y - 399) / 400;
    unsigned yoe = (unsigned)(y - era * 400);
    unsigned doy = (153u * (unsigned)(month + (month > 2 ? -3 : 9)) + 2u) / 5u + (unsigned)day - 1u;
    unsigned doe = yoe * 365u + yoe / 4u - yoe / 100u + doy;
    int64_t days = (int64_t)era * 146097LL + (int64_t)doe - 719468LL;
    if (days < 0) return 0;
    return (uint32_t)(days * 86400LL + hour * 3600LL + min * 60LL + sec);
}

static inline int32_t _parse_dec_x10(const char *s) {
    if (!s || !*s || *s == ',' || *s == '*') return 0;
    bool neg = false;
    if (*s == '-') {
        neg = true;
        s++;
    }
    int32_t whole = 0;
    while (*s >= '0' && *s <= '9') {
        whole = whole * 10 + (*s - '0');
        s++;
    }
    int32_t tenths = 0;
    if (*s == '.' && s[1] >= '0' && s[1] <= '9') {
        tenths = s[1] - '0';
    }
    int32_t res = whole * 10 + tenths;
    return neg ? -res : res;
}

static inline bool nmea_parse_line(NmeaGpsState *st, const char *line) {
    if (!nmea_verify_checksum(line)) return false;

    // Match $GxRMC (e.g. $GNRMC, $GPRMC)
    if (strncmp(line + 3, "RMC,", 4) == 0) {
        const char *f_time = _next_field(line);        // 1: HHMMSS.ss
        const char *f_stat = _next_field(f_time);      // 2: A=active, V=void
        const char *f_lat  = _next_field(f_stat);      // 3: DDMM.MMMMM
        const char *f_ns   = _next_field(f_lat);       // 4: N/S
        const char *f_lon  = _next_field(f_ns);        // 5: DDDMM.MMMMM
        const char *f_ew   = _next_field(f_lon);       // 6: E/W
        const char *f_spd  = _next_field(f_ew);        // 7: knots
        const char *f_cog  = _next_field(f_spd);       // 8: course
        const char *f_date = _next_field(f_cog);       // 9: DDMMYY

        if (f_time && strlen(f_time) >= 6 && f_time[0] >= '0' && f_time[0] <= '9') {
            st->utc_hour = (uint8_t)((f_time[0] - '0') * 10 + (f_time[1] - '0'));
            st->utc_min  = (uint8_t)((f_time[2] - '0') * 10 + (f_time[3] - '0'));
            st->utc_sec  = (uint8_t)((f_time[4] - '0') * 10 + (f_time[5] - '0'));
            if (f_date && strlen(f_date) >= 6 && f_date[0] >= '0' && f_date[0] <= '9') {
                int dd = (f_date[0] - '0') * 10 + (f_date[1] - '0');
                int mm = (f_date[2] - '0') * 10 + (f_date[3] - '0');
                int yy = (f_date[4] - '0') * 10 + (f_date[5] - '0');
                st->unix_ts = utc_to_unix_ts(2000 + yy, mm, dd, st->utc_hour, st->utc_min, st->utc_sec);
            }
        }

        if (f_stat && *f_stat == 'A' && f_ns && f_ew) {
            int32_t lat_e7 = 0, lon_e7 = 0;
            if (parse_nmea_coord_e7(f_lat, *f_ns, &lat_e7) &&
                parse_nmea_coord_e7(f_lon, *f_ew, &lon_e7)) {
                st->lat_e7 = lat_e7;
                st->lon_e7 = lon_e7;
                st->has_fix = true;
            }
        } else if (f_stat && *f_stat == 'V') {
            st->has_fix = false;
        }
        return true;
    }

    // Match $GxGGA (e.g. $GNGGA, $GPGGA) for altitude, HDOP, and satellite count
    if (strncmp(line + 3, "GGA,", 4) == 0) {
        const char *f_time = _next_field(line);        // 1: HHMMSS.ss
        const char *f_lat  = _next_field(f_time);      // 2: lat
        const char *f_ns   = _next_field(f_lat);       // 3: N/S
        const char *f_lon  = _next_field(f_ns);        // 4: lon
        const char *f_ew   = _next_field(f_lon);       // 5: E/W
        const char *f_qual = _next_field(f_ew);        // 6: fix quality (0=invalid, 1=GPS, 2=DGPS)
        const char *f_sats = _next_field(f_qual);      // 7: num satellites
        const char *f_hdop = _next_field(f_sats);      // 8: HDOP
        const char *f_alt  = _next_field(f_hdop);      // 9: MSL altitude (meters)

        if (f_sats && *f_sats >= '0' && *f_sats <= '9') {
            int sats = 0;
            const char *p = f_sats;
            while (*p >= '0' && *p <= '9') {
                sats = sats * 10 + (*p - '0');
                p++;
            }
            st->sat_count = (sats > 63) ? 63u : (uint8_t)sats;
        }
        if (f_hdop) {
            int32_t hdop10 = _parse_dec_x10(f_hdop);
            if (hdop10 > 0) {
                st->hdop_x10 = (hdop10 > 255) ? 255u : (uint8_t)hdop10;
            }
        }
        if (f_qual && *f_qual >= '1' && *f_qual <= '9') {
            if (f_alt) {
                int32_t alt_dm = _parse_dec_x10(f_alt);
                if (alt_dm < -32768) alt_dm = -32768;
                if (alt_dm > 32767) alt_dm = 32767;
                st->alt_dm = (int16_t)alt_dm;
            }
            if (f_ns && f_ew) {
                int32_t lat_e7 = 0, lon_e7 = 0;
                if (parse_nmea_coord_e7(f_lat, *f_ns, &lat_e7) &&
                    parse_nmea_coord_e7(f_lon, *f_ew, &lon_e7)) {
                    st->lat_e7 = lat_e7;
                    st->lon_e7 = lon_e7;
                    st->has_fix = true;
                }
            }
        }
        return true;
    }

    return false;
}

static inline bool nmea_feed_char(NmeaGpsState *st, char c) {
    if (c == '$') {
        st->line_buf[0] = '$';
        st->line_len = 1;
        return false;
    }
    if (st->line_len == 0) return false;

    if (c == '\r' || c == '\n') {
        st->line_buf[st->line_len] = '\0';
        st->line_len = 0;
        return nmea_parse_line(st, st->line_buf);
    }

    if (st->line_len + 1 < NMEA_MAX_LINE) {
        st->line_buf[st->line_len++] = c;
    } else {
        st->line_len = 0; // Overflow reset
    }
    return false;
}

#endif // GUMMYBEAR_NMEA_PARSER_H
