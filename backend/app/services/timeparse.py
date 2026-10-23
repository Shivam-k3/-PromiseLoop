"""Natural-language deadline parsing.

The parser is intentionally rule based: it works offline, it is deterministic
(it can be unit tested), and it never invents a date it is not sure about -
anything it cannot pin down is reported as ambiguous and gets confirmed with
the user before it is saved.

The LLM can override these rules, but the rules are the safety net and the
source of truth for timezone maths.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Precision = Literal["exact", "day", "vague"]

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# words that introduce a deadline
DEADLINE_MARKERS = (
    "no later than ",
    "by ",
    "before ",
    "due ",
    "on ",
    "until ",
    "at the end of ",
)

# time-of-day words are fuzzy: the user did not name a clock time.
FUZZY_TIMES = {
    "morning": time(9, 0),
    "noon": time(12, 0),
    "midday": time(12, 0),
    "afternoon": time(15, 0),
    "evening": time(18, 0),
    "tonight": time(20, 0),
    "eod": time(18, 0),
    "end of day": time(18, 0),
    "end of the day": time(18, 0),
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass
class Deadline:
    """A deadline resolved against a concrete calendar."""

    date: date
    time: time | None
    precision: Precision
    label: str
    ambiguous: bool = False
    question: str | None = None

    def as_utc(self, tz_name: str) -> datetime:
        tz = _zone(tz_name)
        moment = datetime.combine(self.date, self.time or time(18, 0))
        return moment.replace(tzinfo=tz).astimezone(timezone.utc)


def _zone(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return timezone.utc


def _today(now: datetime, tz_name: str) -> date:
    return now.astimezone(_zone(tz_name)).date()


def _next_weekday(today: date, weekday: int, *, next_week: bool) -> date:
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0:
        ahead = 7
    if next_week:
        ahead += 7
    return today + timedelta(days=ahead)


def _last_day_of_month(today: date) -> date:
    if today.month == 12:
        return date(today.year, 12, 31)
    return date(today.year, today.month + 1, 1) - timedelta(days=1)


def _find_time_of_day(text: str) -> tuple[time | None, str | None, bool]:
    """Return (time, matched label, is_fuzzy) for a time-of-day phrase."""
    lowered = text.lower()

    for label in ("end of the day", "end of day"):
        if re.search(rf"\b{re.escape(label)}\b", lowered):
            return FUZZY_TIMES[label], label, True

    for label, value in FUZZY_TIMES.items():
        if re.search(rf"\b{re.escape(label)}\b", lowered):
            return value, label, True

    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if match:
        hour = int(match.group(1)) % 12
        if match.group(3) == "pm":
            hour += 12
        minute = int(match.group(2) or 0)
        return time(hour % 24, minute), match.group(0), False

    match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if match:
        return time(int(match.group(1)) % 24, int(match.group(2))), match.group(0), False

    return None, None, False


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_date(text: str, today: date) -> tuple[date | None, str, bool]:
    """Return (date, matched label, ambiguous)."""
    lowered = text.lower()

    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        parsed = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed:
            return parsed, match.group(0), False

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if match:
        first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if year < 100:
            year += 2000
        for day, month in ((first, second), (second, first)):
            parsed = _safe_date(year, month, day)
            if parsed:
                return parsed, match.group(0), False

    for name, number in MONTHS.items():
        match = re.search(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{name}\b|\b{name}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
            lowered,
        )
        if match:
            day = int(match.group(1) or match.group(2))
            parsed = _safe_date(today.year, number, day)
            if parsed is None:
                continue
            if parsed < today:
                parsed = _safe_date(today.year + 1, number, day)
            if parsed:
                return parsed, match.group(0), False

    if "day after tomorrow" in lowered:
        return today + timedelta(days=2), "day after tomorrow", False
    if "tomorrow" in lowered:
        return today + timedelta(days=1), "tomorrow", False
    if "tonight" in lowered:
        return today, "tonight", False
    if re.search(r"\btoday\b", lowered):
        return today, "today", False

    match = re.search(r"\bin (\d+) (day|days|week|weeks|month|months)\b", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit.startswith("day"):
            return today + timedelta(days=amount), match.group(0), False
        if unit.startswith("week"):
            return today + timedelta(weeks=amount), match.group(0), False
        return today + timedelta(days=30 * amount), match.group(0), False

    if "this weekend" in lowered or "the weekend" in lowered:
        return _next_weekday(today, 5), "this weekend", False
    if "end of month" in lowered:
        return _last_day_of_month(today), "end of month", False
    if "end of week" in lowered:
        return _next_weekday(today, 4), "end of week", False
    if "next week" in lowered:
        return today + timedelta(days=7), "next week", False

    for name, weekday in WEEKDAYS.items():
        match = re.search(rf"\b(?:(next|this|on|by)\s+)?{name}\b", lowered)
        if match:
            qualifier = (match.group(1) or "").strip()
            target = _next_weekday(today, weekday, next_week=qualifier == "next")
            return target, match.group(0).strip(), qualifier != "next"

    return None, "", False


def parse_deadline(
    text: str, tz_name: str = "UTC", now: datetime | None = None
) -> Deadline | None:
    """Parse the first deadline mentioned in ``text``.

    Returns ``None`` when the text carries no deadline at all.
    """
    if not text or not text.strip():
        return None

    now = now or datetime.now(timezone.utc)
    today = _today(now, tz_name)

    candidates: list[tuple[int, Deadline]] = []

    explicit_date, date_label, ambiguous = _extract_date(text, today)
    if explicit_date is not None:
        moment, time_label, fuzzy = _find_time_of_day(text)
        candidates.append(
            (
                0,
                _build_deadline(
                    explicit_date,
                    moment,
                    time_label,
                    date_label,
                    fuzzy,
                    ambiguous,
                ),
            )
        )

    lowered = text.lower()
    for marker in DEADLINE_MARKERS:
        index = lowered.find(marker)
        if index == -1:
            continue
        phrase = _trim_phrase(text[index + len(marker) :])
        parsed_date, date_label, ambiguous = _extract_date(phrase, today)
        if parsed_date is None:
            continue
        moment, time_label, fuzzy = _find_time_of_day(phrase)
        candidates.append(
            (
                1,
                _build_deadline(parsed_date, moment, time_label, date_label, fuzzy, ambiguous),
            )
        )

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _build_deadline(
    day: date,
    moment: time | None,
    time_label: str | None,
    date_label: str,
    fuzzy_time: bool,
    ambiguous: bool,
) -> Deadline:
    label = " ".join(part for part in (date_label.strip(), (time_label or "").strip()) if part)
    if moment is None:
        precision: Precision = "day"
    elif fuzzy_time:
        precision = "day"
    else:
        precision = "exact"

    question = None
    if ambiguous:
        date_text = re.sub(
            r"^(?:by|before|on|until|due|no later than)\s+",
            "",
            date_label.strip(),
            flags=re.IGNORECASE,
        )
        question = (
            f"Which {date_text.title()} do you mean? I have pencilled in {day}."
        )

    return Deadline(
        date=day,
        time=moment,
        precision=precision,
        label=label,
        ambiguous=ambiguous,
        question=question,
    )


def _trim_phrase(text: str) -> str:
    """Cut a deadline phrase at the first word that clearly ends it."""
    stop_words = {
        "and",
        "but",
        "so",
        "because",
        "then",
        "if",
        "while",
        "also",
        "plus",
        "after",
        "i",
        "we",
        "he",
        "she",
        "they",
        "it",
        "please",
        "thanks",
        "thank",
        ".",
        ",",
        ";",
    }
    words = re.split(r"(\s+)", text.strip())
    kept: list[str] = []
    for word in words:
        stripped = word.strip().lower().strip(".,;:")
        if stripped in stop_words:
            break
        kept.append(word)
        if len("".join(kept).split()) >= 6:
            break
    return " ".join(kept).strip()
