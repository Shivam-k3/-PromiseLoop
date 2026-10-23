"""Rule-based extraction of a commitment from natural language.

This is the offline path (and the safety net): it turns
"I promised Abhishek that I'll send him our project demo by tomorrow evening"
into the exact argument set the ``create_commitment`` MCP tool expects.
"""

import re
from dataclasses import dataclass, field

from app.services.timeparse import parse_deadline

# (compiled pattern, expects a recipient group)
PATTERNS: list[tuple[re.Pattern[str], bool]] = [
    (
        re.compile(
            r"\bi\s+promised\s+(?P<who>.+?)\s+that\s+"
            r"(?:i['’]?(?:ll| will| shall| should| am going to| need to| have to| must)|to)\s+"
            r"(?P<action>.+)",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(
            r"\bi\s+told\s+(?P<who>[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)?)\s+"
            r"(?:that\s+)?(?:i['’]?(?:ll| will| shall| should| am going to| need to| have to| must)|to)\s+"
            r"(?P<action>.+)",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(
            r"\b(?P<who>[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)?)\s+asked me to\s+(?P<action>.+)",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(
            r"\bi\s+promised\s+(?P<who>[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)?)\s+(?P<action>.+)",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(r"\bi\s+promise(?:d)?\s+to\s+(?P<action>.+)", re.IGNORECASE),
        False,
    ),
    (
        re.compile(
            r"\bi(?:['’]?ll|\s+(?:will|shall|should|need to|have to|must|am going to))\s+(?P<action>.+)",
            re.IGNORECASE,
        ),
        False,
    ),
    (re.compile(r"\bremind me to\s+(?P<action>.+)", re.IGNORECASE), False),
    (re.compile(r"\bdon['’]?t forget to\s+(?P<action>.+)", re.IGNORECASE), False),
]

RELATIONSHIP_PATTERN = re.compile(
    r"\b(?:to|for)\s+my\s+"
    r"(sister|brother|mother|mom|mum|father|dad|wife|husband|partner|friend|"
    r"boyfriend|girlfriend|colleague|coworker|manager|boss|son|daughter|parent|parents)\b",
    re.IGNORECASE,
)

HYPOTHETICAL = re.compile(
    r"^\s*(?:if|what if|suppose|supposing|imagine|hypothetically|for example|e\.g\.)\b",
    re.IGNORECASE,
)

DEADLINE_MARKERS = (
    "no later than ",
    "by ",
    "before ",
    "due ",
    "on ",
    "until ",
    "at the end of ",
)

PRONOUNS = {"him", "her", "them", "he", "she", "they"}

HIGH_PRIORITY = re.compile(r"\b(urgent|asap|critical|highest priority|immediately)\b", re.I)
LOW_PRIORITY = re.compile(r"\b(sometime|whenever|no rush|low priority|eventually)\b", re.I)


@dataclass
class Extracted:
    title: str
    recipient: str | None = None
    details: str | None = None
    due_text: str | None = None
    priority: str = "normal"
    ambiguous: bool = False
    question: str | None = None
    extra: dict = field(default_factory=dict)

    def as_tool_arguments(self, timezone: str) -> dict:
        arguments: dict = {
            "title": self.title,
            "recipient": self.recipient,
            "details": self.details,
            "due_text": self.due_text,
            "priority": self.priority,
            "timezone": timezone,
        }
        arguments.update(self.extra)
        return {key: value for key, value in arguments.items() if value is not None}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(".,;:")).strip()


def _normalise_recipient(who: str | None) -> str | None:
    if not who:
        return None
    who = who.strip()
    if " " not in who:
        return who[:1].upper() + who[1:]
    if all(part[:1].isupper() for part in who.split() if part):
        return who
    return None


def _replace_pronoun(action: str, recipient: str | None) -> str:
    if not recipient:
        return action
    first_name = recipient.split()[0]
    return re.sub(
        r"\b(him|her|them|he|she|they)\b",
        first_name,
        action,
        flags=re.IGNORECASE,
    )


def _split_deadline(action: str, timezone: str):
    """Split an action into (action without deadline, parsed deadline)."""
    lowered = action.lower()
    for marker in DEADLINE_MARKERS:
        index = lowered.find(marker)
        if index == -1:
            continue
        tail = action[index + len(marker) :]
        parsed = parse_deadline(tail, timezone)
        if parsed is not None:
            return action[:index].strip(" ,"), parsed

    # A bare date phrase ("... tomorrow evening") has no marker word.
    parsed = parse_deadline(action, timezone)
    if parsed is not None and parsed.label:
        without_label = re.sub(
            rf"\s*{re.escape(parsed.label)}\s*$", "", action, flags=re.IGNORECASE
        )
        if without_label != action:
            return without_label.strip(" ,"), parsed
    return action, None


def _priority(text: str) -> str:
    if HIGH_PRIORITY.search(text):
        return "high"
    if LOW_PRIORITY.search(text):
        return "low"
    return "normal"


def extract_commitment(text: str, timezone: str = "UTC") -> Extracted | None:
    """Extract a commitment from a sentence, or ``None`` if it is not one."""
    if not text or not text.strip():
        return None
    if HYPOTHETICAL.search(text) or text.lstrip().startswith(("\"", "'", "“")):
        return None

    for pattern, expects_recipient in PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        action = _clean(match.group("action"))
        recipient = (
            _normalise_recipient(match.groupdict().get("who")) if expects_recipient else None
        )

        action, deadline = _split_deadline(action, timezone)
        action = _replace_pronoun(_clean(action), recipient)
        if not action:
            continue

        if not recipient:
            relationship = RELATIONSHIP_PATTERN.search(action)
            if relationship:
                recipient = relationship.group(1).lower()

        title = action[0].upper() + action[1:]
        ambiguous = bool(deadline and deadline.ambiguous)
        question = deadline.question if deadline else None
        if not recipient and re.search(r"\bfor\s+[A-Z]", text):
            ambiguous = True
            question = question or "Who is this promise for?"

        return Extracted(
            title=title,
            recipient=recipient,
            due_text=deadline.label if deadline else None,
            priority=_priority(text),
            ambiguous=ambiguous,
            question=question,
        )

    return None


def looks_like_commitment(text: str) -> bool:
    return extract_commitment(text) is not None
