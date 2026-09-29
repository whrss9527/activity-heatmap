"""Draw the history as a calendar heatmap card that sits with the profile's project cards.

GitHub shows README images through <img>, which blocks anything an SVG loads from
elsewhere, so the card uses system fonts only.
"""

from __future__ import annotations

from datetime import date, timedelta
from xml.sax.saxutils import escape, quoteattr

WIDTH, PAD, RADIUS = 808, 24, 18  # the profile shows project cards two to a row, 808px in all
CELL, GAP = 10, 3
PITCH = CELL + GAP
GUTTER = 56  # the year and its total sit left of each grid
GRID_X = PAD + GUTTER
ROW_HEIGHT, ROW_GAP = 7 * PITCH - GAP, 16
ICON = 52
TILE_Y, TILE_HEIGHT, TILE_GAP = PAD + ICON + 18, 64, 12
MONTH_Y = TILE_Y + TILE_HEIGHT + 30  # baseline of the month names
GRID_Y = MONTH_Y + 9
FONTS = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", '
    '"Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", sans-serif'
)

# Muted rose up to Apple's Move ring red, so ordinary days stay calm and big days stand out.
# Checked as an ordinal ramp (monotone lightness, visible steps, faintest step >= 2:1)
# against the lightest, middle and darkest parts of the card background.
LEVELS = ("#7E384C", "#A3425B", "#C94C67", "#FD4461")
QUANTILES = (0.25, 0.5, 0.9)  # so the brightest cells are the top tenth of days
WEEKDAYS = "一二三四五六日"


def text_width(text, size):
    """Rough advance width, enough to space the legend."""
    width = 0.0
    for char in text:
        if ord(char) > 0x2E80:
            width += 1.0
        elif char == " ":
            width += 0.3
        elif char.isdigit() or char in "<>≥–,":
            width += 0.6
        else:
            width += 0.55
    return width * size


def _step(value):
    digits = len(str(int(value)))
    return 5 * 10 ** (digits - 2) if digits >= 2 else 1


def nice(value):
    """Round to a number worth printing on a legend: 394 -> 400, 816 -> 800, 1234 -> 1000."""
    step = _step(value)
    return max(step, round(value / step) * step)


def thresholds(values):
    """Three cut points between the four levels, from the spread of all recorded days."""
    values = sorted(value for value in values if value > 0)
    cuts = []
    for quantile in QUANTILES:
        cut = nice(values[min(len(values) - 1, int(quantile * len(values)))]) if values else 1
        if cuts and cut <= cuts[-1]:
            cut = cuts[-1] + _step(cuts[-1])
        cuts.append(cut)
    return tuple(cuts)


def level(value, cuts):
    if not value or value <= 0:
        return 0
    return 1 + sum(value >= cut for cut in cuts)


def days_before(series, end, count, skip=0):
    """(day, value) for the `count` days before `end`, after skipping `skip` of them."""
    pairs = []
    for back in range(skip + 1, skip + count + 1):
        day = end - timedelta(days=back)
        if day.isoformat() in series:
            pairs.append((day, series[day.isoformat()]))
    return pairs


def average(pairs):
    values = [value for _, value in pairs if value > 0]
    return sum(values) / len(values) if values else None


def compact(value):
    if value >= 10_000:
        return f"{value / 1000:.0f}k"
    if value >= 1_000:
        return f"{value / 1000:.1f}k"
    return f"{value:.0f}"


def tiles(series, last):
    """The four figures above the grid. The latest day is usually still in progress, so every
    window ends the day before it."""
    year = days_before(series, last, 365)
    recent, before = average(days_before(series, last, 30)), average(days_before(series, last, 30, skip=30))
    best = max(year, key=lambda pair: pair[1], default=None)
    trend = f"环比 {recent / before - 1:+.0%}".replace("-", "−") if recent and before else ""
    dash = "—"
    return [
        ("近一年累计", f"{sum(value for _, value in year):,.0f}" if year else dash, ""),
        ("近一年日均", f"{average(year):,.0f}" if average(year) else dash, ""),
        ("近一年最高", f"{best[1]:,.0f}" if best else dash, f"{best[0].month}月{best[0].day}日" if best else ""),
        ("近 30 天日均", f"{recent:,.0f}" if recent else dash, trend),
    ]


def ring_icon(x, y):
    """A Move ring on black, standing in for the app icon the project cards carry."""
    cx, cy, r = x + ICON / 2, y + ICON / 2, 14.5
    return (
        f'<rect x="{x}" y="{y}" width="{ICON}" height="{ICON}" rx="13" fill="#000000" filter="url(#lift)"/>'
        f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{ICON - 1}" height="{ICON - 1}" rx="12.5" fill="none" stroke="url(#rim)"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#FA114F" stroke-opacity="0.25" stroke-width="7"/>'
        f'<path d="M{cx},{cy - r} A{r},{r} 0 1 1 {cx - r},{cy}" fill="none" stroke="url(#move)" '
        'stroke-width="7" stroke-linecap="round"/>'
        f'<path d="M{cx - 1.8},{cy - r - 2.4} L{cx + 0.8},{cy - r} L{cx - 1.8},{cy - r + 2.4}" fill="none" '
        'stroke="#000000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    )


def year_row(series, year, top, cuts, last):
    first = date(year, 1, 1)
    offset, cells, day = first.weekday(), [], first
    while day.year == year and day <= last:
        index = offset + (day - first).days
        x, y = GRID_X + index // 7 * PITCH, top + index % 7 * PITCH
        value = series.get(day.isoformat())
        label = f"{day} 周{WEEKDAYS[day.weekday()]} · " + ("无记录" if value is None else f"{value:,.0f} kcal")
        cells.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2.5" class="l{level(value, cuts)}">'
            f"<title>{escape(label)}</title></rect>"
        )
        if day == last:
            cells.append(
                f'<rect x="{x - 2}" y="{y - 2}" width="{CELL + 4}" height="{CELL + 4}" rx="4" fill="none" '
                'stroke="#FFFFFF" stroke-opacity="0.9" stroke-width="1.2"/>'
            )
        day += timedelta(days=1)
    total = sum(value for key, value in series.items() if key.startswith(f"{year}-"))
    return (
        f'<text x="{PAD}" y="{top + 11}" class="year">{year}</text>'
        f'<text x="{PAD}" y="{top + 27}" class="total">{compact(total)}</text>' + "".join(cells)
    )


def month_labels(year):
    first, labels = date(year, 1, 1), []
    for month in range(1, 13):
        index = first.weekday() + (date(year, month, 1) - first).days
        labels.append(f'<text x="{GRID_X + index // 7 * PITCH}" y="{MONTH_Y}" class="axis">{month}月</text>')
    return "".join(labels)


def legend(y, cuts):
    items = [
        ("l0", "无记录"),
        ("l1", f"< {cuts[0]:,}"),
        ("l2", f"{cuts[0]:,}–{cuts[1]:,}"),
        ("l3", f"{cuts[1]:,}–{cuts[2]:,}"),
        ("l4", f"≥ {cuts[2]:,}"),
    ]
    parts, x = [f'<text x="{PAD}" y="{y}" class="axis">每日 kcal</text>'], PAD + text_width("每日 kcal", 11) + 14
    for name, label in items:
        parts.append(f'<rect x="{x:.1f}" y="{y - 9}" width="{CELL}" height="{CELL}" rx="2.5" class="{name}"/>')
        parts.append(f'<text x="{x + CELL + 6:.1f}" y="{y}" class="axis">{escape(label)}</text>')
        x += CELL + 6 + text_width(label, 11) + 16
    return "".join(parts)


def render(series, *, years=0, levels=None, title="活动能量", today=None):
    """The whole card as an SVG string. `today` only matters while the history is empty."""
    days = sorted(date.fromisoformat(key) for key in series)
    last = days[-1] if days else (today or date.today())
    first = days[0] if days else last
    cuts = tuple(levels) if levels else thresholds(series.values())
    shown = list(range(last.year, first.year - 1, -1))[: years or None]

    rows_bottom = GRID_Y + len(shown) * (ROW_HEIGHT + ROW_GAP) - ROW_GAP
    legend_y = rows_bottom + 32
    height = legend_y + PAD

    figures = tiles(series, last)
    tile_width = (WIDTH - 2 * PAD - 3 * TILE_GAP) / 4
    tile_parts = []
    for index, (label, value, note) in enumerate(figures):
        x = PAD + index * (tile_width + TILE_GAP)
        tile_parts.append(
            f'<rect x="{x:.1f}" y="{TILE_Y}" width="{tile_width:.1f}" height="{TILE_HEIGHT}" rx="12" '
            'fill="#FFFFFF" fill-opacity="0.05" stroke="#FFFFFF" stroke-opacity="0.10"/>'
            f'<text x="{x + 14:.1f}" y="{TILE_Y + 23}" class="label">{escape(label)}</text>'
            f'<text x="{x + tile_width - 14:.1f}" y="{TILE_Y + 23}" text-anchor="end" class="note">{escape(note)}</text>'
            f'<text x="{x + 14:.1f}" y="{TILE_Y + 50}" class="value">{value}'
            f'<tspan class="unit">{" kcal" if value != "—" else ""}</tspan></text>'
        )

    recorded = sum(1 for value in series.values() if value > 0)
    tagline = f"来自 Apple 健康 · {first.year} 年至今记录了 {recorded:,} 天"
    stamp = f"截至 {last.month}月{last.day}日"
    stamp_width = text_width(stamp, 11) + 22
    summary = f"{title}热力图，" + "，".join(f"{label} {value}" + (" kcal" if value != "—" else "") for label, value, _ in figures)
    rows = "".join(
        year_row(series, year, GRID_Y + index * (ROW_HEIGHT + ROW_GAP), cuts, last) for index, year in enumerate(shown)
    )
    level_styles = "\n".join(f".l{index + 1} {{ fill: {color}; }}" for index, color in enumerate(LEVELS))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" role="img" aria-label={quoteattr(summary)}>
<title>{escape(summary)}</title>
<defs>
<clipPath id="card"><rect width="{WIDTH}" height="{height}" rx="{RADIUS}"/></clipPath>
<linearGradient id="base" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1B1A2E"/><stop offset="1" stop-color="#0B0B14"/></linearGradient>
<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="{GRID_Y}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.08"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>
<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.34"/><stop offset="0.5" stop-color="#FFFFFF" stop-opacity="0.10"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0.06"/></linearGradient>
<linearGradient id="move" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E6004C"/><stop offset="1" stop-color="#FF4F7E"/></linearGradient>
<filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="38"/></filter>
<filter id="lift" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="6" stdDeviation="7" flood-color="#000000" flood-opacity="0.35"/></filter>
<style>
text {{ font-family: {FONTS}; fill: #FFFFFF; }}
.title {{ font-size: 22px; font-weight: 700; letter-spacing: -0.2px; }}
.tagline {{ font-size: 13px; fill-opacity: 0.68; }}
.stamp {{ font-size: 11px; font-weight: 500; fill-opacity: 0.62; letter-spacing: 0.2px; }}
.label {{ font-size: 12px; fill-opacity: 0.62; }}
.note {{ font-size: 11px; fill-opacity: 0.5; }}
.value {{ font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }}
.unit {{ font-size: 12px; font-weight: 400; fill-opacity: 0.62; letter-spacing: 0; }}
.axis {{ font-size: 11px; fill-opacity: 0.55; }}
.year {{ font-size: 13px; font-weight: 600; fill-opacity: 0.9; }}
.total {{ font-size: 11px; fill-opacity: 0.5; }}
.l0 {{ fill: #FFFFFF; fill-opacity: 0.07; }}
{level_styles}
</style>
</defs>
<g clip-path="url(#card)">
<rect width="{WIDTH}" height="{height}" fill="url(#base)"/>
<circle cx="{WIDTH - 40}" cy="-10" r="150" fill="#FA114F" fill-opacity="0.26" filter="url(#glow)"/>
<circle cx="30" cy="{height + 20}" r="170" fill="#6D5CF0" fill-opacity="0.22" filter="url(#glow)"/>
<rect width="{WIDTH}" height="{GRID_Y}" fill="url(#sheen)"/>
</g>
<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="{RADIUS - 0.5}" fill="none" stroke="url(#rim)"/>
{ring_icon(PAD, PAD)}
<text x="{PAD + ICON + 16}" y="{PAD + 23}" class="title">{escape(title)}</text>
<text x="{PAD + ICON + 16}" y="{PAD + 45}" class="tagline">{escape(tagline)}</text>
<rect x="{WIDTH - PAD - stamp_width:.1f}" y="{PAD + 0.5}" width="{stamp_width:.1f}" height="22" rx="11" fill="#FFFFFF" fill-opacity="0.06" stroke="#FFFFFF" stroke-opacity="0.18"/>
<text x="{WIDTH - PAD - stamp_width / 2:.1f}" y="{PAD + 15.5}" text-anchor="middle" class="stamp">{escape(stamp)}</text>
{"".join(tile_parts)}
{month_labels(last.year)}
{rows}
{legend(legend_y, cuts)}
</svg>
'''
