"""GPX 1.1 exporter with Garmin TrackPointExtension v1 heart-rate tags for Strava."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

from gummybear.models import CleanSample


def _iso_utc(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encode_gpx(samples: Sequence[CleanSample], name: str = "Casio W-218H Run") -> str:
    """Render cleaned telemetry into Strava-compatible GPX 1.1 + HR XML."""
    if not samples:
        raise ValueError("Cannot export empty sample sequence to GPX")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx creator="Gummybear Casio W-218H" version="1.1"',
        '  xmlns="http://www.topografix.com/GPX/1/1"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '  xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"',
        '  xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
        'http://www.topografix.com/GPX/1/1/gpx.xsd '
        'http://www.garmin.com/xmlschemas/TrackPointExtension/v1 '
        'http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd">',
        "  <metadata>",
        f"    <time>{_iso_utc(samples[0].unix_ts)}</time>",
        "  </metadata>",
        "  <trk>",
        f"    <name>{escape(name)}</name>",
        "    <type>running</type>",
        "    <trkseg>",
    ]

    # Start a new <trkseg> across pauses so Strava does not draw straight lines across paused gaps
    in_paused_gap = False
    for s in samples:
        if s.paused:
            if not in_paused_gap:
                lines.append("    </trkseg>")
                in_paused_gap = True
            continue
        if in_paused_gap:
            lines.append("    <trkseg>")
            in_paused_gap = False

        lines.append(f'      <trkpt lat="{s.lat:.7f}" lon="{s.lon:.7f}">')
        lines.append(f"        <ele>{s.alt_m:.1f}</ele>")
        lines.append(f"        <time>{_iso_utc(s.unix_ts)}</time>")
        if s.hr_bpm is not None and s.hr_bpm > 0:
            lines.append("        <extensions>")
            lines.append("          <gpxtpx:TrackPointExtension>")
            lines.append(f"            <gpxtpx:hr>{s.hr_bpm}</gpxtpx:hr>")
            lines.append("          </gpxtpx:TrackPointExtension>")
            lines.append("        </extensions>")
        lines.append("      </trkpt>")

    if not in_paused_gap:
        lines.append("    </trkseg>")
    lines.extend(["  </trk>", "</gpx>", ""])
    return "\n".join(lines)


def write_gpx_file(
    path: Path, samples: Sequence[CleanSample], name: str = "Casio W-218H Run"
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode_gpx(samples, name=name), encoding="utf-8")
