"""Read what the Shortcut sends and fold it into the daily history.

The Shortcut dispatches the workflow with two text inputs listing the same samples in
the same order: `time` holds each sample's date, `value` its active energy in kcal.
Samples are summed per local day, and every day in a payload replaces the stored
total, the same as GitHubPoster's incremental mode did.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SERIES = "move"

# 2026-09-28 · 2026-09-28T08:00:00+08:00 · 2026-09-28 08:00:00 +0800 · 2026/9/28 · 2026年9月28日
DATE = re.compile(
    r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"
    r"(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?"
    r"(?:\s?(Z|[+-]\d{2}:?\d{2}))?"
)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class PayloadError(ValueError):
    """The inputs can't be read as matching lists of dates and values."""


@dataclass
class Sample:
    day: date
    moment: datetime | None  # local wall time, when the Shortcut sent a time of day
    value: float


@dataclass
class Change:
    day: date
    samples: int
    first: datetime | None
    last: datetime | None
    old: float | None
    new: float


def _unescape(text):
    # the old workflow read the inputs through bash $'...', which turned a literal \n into a newline
    for escaped, plain in (("\\r\\n", "\n"), ("\\n", "\n"), ("\\r", "\n"), ("\\t", " "), ("\r\n", "\n"), ("\r", "\n")):
        text = text.replace(escaped, plain)
    return text


def _offset(text):
    if text == "Z":
        return timezone.utc
    digits = text[1:].replace(":", "")
    delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return timezone(-delta if text[0] == "-" else delta)


def parse_times(text, tz):
    """Every date in the text, as (local day, local time or None)."""
    stamps = []
    for match in DATE.finditer(_unescape(text)):
        year, month, day, hour, minute, second, offset = match.groups()
        try:
            if hour is None:
                stamps.append((date(int(year), int(month), int(day)), None))
                continue
            moment = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))
        except ValueError as error:
            raise PayloadError(f"「{match.group()}」不是有效的日期：{error}") from None
        if offset:
            # a sample stamped in another zone still belongs to the local day it happened on
            moment = moment.replace(tzinfo=_offset(offset)).astimezone(tz).replace(tzinfo=None)
        stamps.append((moment.date(), moment))
    return stamps


def _number(token):
    match = NUMBER.search(token)
    if not match:
        raise PayloadError(f"「{token.strip()}」不是数字")
    return float(match.group())


def parse_values(text, expected):
    text = re.sub(r"[\[\]'\"]", " ", _unescape(text))
    # GitHubPoster split on commas as well as newlines, which still reads comma separated
    # lists. A list with one value per line may carry thousands separators ("1,257"),
    # so that reading is tried when the first one doesn't pair up with the dates.
    readings = (
        [token for token in re.split(r"[\n,;]", text) if token.strip()],
        [token.replace(",", "") for token in re.split(r"[\n;]", text) if token.strip()],
    )
    for tokens in readings:
        if len(tokens) == expected:
            return [_number(token) for token in tokens]
    raise PayloadError(f"time 里有 {expected} 个日期，value 里有 {len(readings[0])} 个数值，没法一一对应")


def parse(times, values, tz):
    stamps = parse_times(times or "", tz)
    if not stamps and not (values or "").strip():
        return []
    if not stamps:
        raise PayloadError("value 有内容，但 time 里没有找到日期")
    numbers = parse_values(values or "", len(stamps))
    return [Sample(day, moment, value) for (day, moment), value in zip(stamps, numbers)]


def tidy(value):
    value = round(float(value), 1)
    return int(value) if value.is_integer() else value


def merge(series, samples):
    """Replace each day in the payload with the sum of its samples; returns what changed."""
    by_day = defaultdict(list)
    for sample in samples:
        by_day[sample.day].append(sample)
    changes = []
    for day in sorted(by_day):
        group = by_day[day]
        moments = [sample.moment for sample in group if sample.moment]
        total = tidy(sum(sample.value for sample in group))
        key = day.isoformat()
        changes.append(Change(day, len(group), min(moments, default=None), max(moments, default=None), series.get(key), total))
        series[key] = total
    return changes


def report(changes, today):
    """A Markdown table for the job summary, so odd payloads are easy to spot."""
    if not changes:
        return "没有收到样本，只重新生成了热力图。"
    lines = [
        f"收到 {sum(change.samples for change in changes)} 个样本，涉及 {len(changes)} 天。",
        "",
        "| 日期 | 样本数 | 时间范围 | 原值 | 新值 | |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for change in changes:
        span = "—" if not change.first else f"{change.first:%H:%M}" + (
            f"–{change.last:%H:%M}" if change.last != change.first else ""
        )
        old = "—" if change.old is None else f"{change.old:,.0f}"
        note = ""
        if change.day > today:
            note = "⚠️ 未来的日期"
        elif change.old and change.new < change.old * 0.9:
            note = f"⚠️ 比原来少 {1 - change.new / change.old:.0%}"
        lines.append(f"| {change.day} | {change.samples} | {span} | {old} | {change.new:,.0f} | {note} |")
    return "\n".join(lines)


def load(path):
    path = Path(path)
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get(SERIES, {}))


def save(path, series):
    """One day per line, so `git log -p` shows exactly which days each run changed."""
    path = Path(path)
    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    document[SERIES] = {day: tidy(series[day]) for day in sorted(series)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def import_legacy(series, legacy_path):
    """Copy the days this history doesn't have yet from GitHubPoster's apple_history.json."""
    legacy = json.loads(Path(legacy_path).read_text(encoding="utf-8")).get(SERIES, {})
    missing = [day for day in legacy if day not in series]
    for day in missing:
        series[day] = tidy(legacy[day])
    return len(missing)


def local_today(tz):
    return datetime.now(ZoneInfo(tz) if isinstance(tz, str) else tz).date()
