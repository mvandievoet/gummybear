#ifndef GUMMYBEAR_TIMEZONE_DST_H
#define GUMMYBEAR_TIMEZONE_DST_H

#include <stdbool.h>
#include <stdint.h>

#include "nmea_parser.h"

/*
 * Travel Timezone + Automatic Daylight Saving Time (US/Canada & EU/UK rules).
 * Exact to the second using UTC epoch transition timestamps.
 */

typedef enum {
    DST_NONE = 0,
    DST_US_CANADA = 1, // 2nd Sun Mar 02:00 local -> 1st Sun Nov 02:00 DST local
    DST_EU_UK = 2      // Last Sun Mar 01:00 UTC  -> Last Sun Oct 01:00 UTC
} DstRule;

typedef struct {
    const char *label;      // Short 3-char label shown when cycling travel zones
    int8_t      std_offset; // Standard (winter) UTC offset in hours
    DstRule     dst_rule;
} TravelZone;

static const TravelZone kTravelZones[] = {
    {"SFO", -8, DST_US_CANADA}, // Pacific Time (San Francisco / Vancouver)
    {"DEN", -7, DST_US_CANADA}, // Mountain Time (Denver / Boulder)
    {"CHI", -6, DST_US_CANADA}, // Central Time
    {"TOR", -5, DST_US_CANADA}, // Eastern Time (Toronto / New York)
    {"LIS",  0, DST_EU_UK},     // Western European / UK (Portugal / London)
    {"BRU", +1, DST_EU_UK},     // Central European (Brussels / Paris / Budapest)
    {"EET", +2, DST_EU_UK},     // Eastern European
    {"TOK", +9, DST_NONE},      // Japan (no DST)
    {"NZL", +12, DST_NONE}      // New Zealand base
};

#define NUM_TRAVEL_ZONES ((uint8_t)(sizeof(kTravelZones) / sizeof(kTravelZones[0])))

typedef struct {
    uint16_t year;
    uint8_t  month;
    uint8_t  day;
    uint8_t  hour;
    uint8_t  min;
    uint8_t  sec;
    uint8_t  dow; // 0 = Sun .. 6 = Sat
    bool     is_dst;
} LocalDateTime;

// Inverse of Howard Hinnant civil-to-days: epoch seconds -> civil date/time
static inline void unix_ts_to_civil(uint32_t ts, LocalDateTime *out) {
    uint32_t days_u = ts / 86400u;
    uint32_t rem = ts % 86400u;
    out->hour = (uint8_t)(rem / 3600u);
    rem %= 3600u;
    out->min = (uint8_t)(rem / 60u);
    out->sec = (uint8_t)(rem % 60u);
    out->dow = (uint8_t)((days_u + 4u) % 7u); // 1970-01-01 was Thu (4)

    int64_t z = (int64_t)days_u + 719468LL;
    int64_t era = (z >= 0 ? z : z - 146096LL) / 146097LL;
    unsigned doe = (unsigned)(z - era * 146097LL);
    unsigned yoe = (doe - doe / 1460u + doe / 36524u - doe / 146096u) / 365u;
    int64_t y = (int64_t)yoe + era * 400LL;
    unsigned doy = doe - (365u * yoe + yoe / 4u - yoe / 100u);
    unsigned mp = (5u * doy + 2u) / 153u;
    unsigned d = doy - (153u * mp + 2u) / 5u + 1u;
    unsigned m = mp + (mp < 10u ? 3u : (unsigned)-9);
    y += (m <= 2u ? 1 : 0);

    out->year = (uint16_t)y;
    out->month = (uint8_t)m;
    out->day = (uint8_t)d;
    out->is_dst = false;
}

static inline bool is_dst_at_utc(uint32_t utc_ts, const TravelZone *zone) {
    if (!zone || zone->dst_rule == DST_NONE || utc_ts < 946684800u) return false;

    LocalDateTime utc_dt;
    unix_ts_to_civil(utc_ts, &utc_dt);
    int yr = (int)utc_dt.year;

    if (zone->dst_rule == DST_US_CANADA) {
        uint32_t mar1 = utc_to_unix_ts(yr, 3, 1, 0, 0, 0);
        int dow_mar1 = (int)(((mar1 / 86400u) + 4u) % 7u);
        int second_sun_mar = 1 + ((7 - dow_mar1) % 7) + 7;
        uint32_t spring_utc = utc_to_unix_ts(yr, 3, second_sun_mar, 2 - zone->std_offset, 0, 0);

        uint32_t nov1 = utc_to_unix_ts(yr, 11, 1, 0, 0, 0);
        int dow_nov1 = (int)(((nov1 / 86400u) + 4u) % 7u);
        int first_sun_nov = 1 + ((7 - dow_nov1) % 7);
        uint32_t fall_utc = utc_to_unix_ts(yr, 11, first_sun_nov, 1 - zone->std_offset, 0, 0);

        return (utc_ts >= spring_utc) && (utc_ts < fall_utc);
    }

    if (zone->dst_rule == DST_EU_UK) {
        uint32_t mar31 = utc_to_unix_ts(yr, 3, 31, 0, 0, 0);
        int dow_mar31 = (int)(((mar31 / 86400u) + 4u) % 7u);
        int last_sun_mar = 31 - dow_mar31;
        uint32_t spring_utc = utc_to_unix_ts(yr, 3, last_sun_mar, 1, 0, 0);

        uint32_t oct31 = utc_to_unix_ts(yr, 10, 31, 0, 0, 0);
        int dow_oct31 = (int)(((oct31 / 86400u) + 4u) % 7u);
        int last_sun_oct = 31 - dow_oct31;
        uint32_t fall_utc = utc_to_unix_ts(yr, 10, last_sun_oct, 1, 0, 0);

        return (utc_ts >= spring_utc) && (utc_ts < fall_utc);
    }

    return false;
}

static inline void utc_to_local_datetime(
    uint32_t utc_ts, uint8_t zone_idx, LocalDateTime *out
) {
    const TravelZone *z = &kTravelZones[zone_idx % NUM_TRAVEL_ZONES];
    bool dst = is_dst_at_utc(utc_ts, z);
    int32_t total_offset_s = ((int32_t)z->std_offset + (dst ? 1 : 0)) * 3600;
    int64_t shifted = (int64_t)utc_ts + (int64_t)total_offset_s;
    if (shifted < 0) shifted = 0;
    unix_ts_to_civil((uint32_t)shifted, out);
    out->is_dst = dst;
}

#endif // GUMMYBEAR_TIMEZONE_DST_H
