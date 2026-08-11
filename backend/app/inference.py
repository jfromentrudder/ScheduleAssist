"""Guessing which imported events are deadlines.

Google Calendar has no concept of a deadline: everything it hands us is a span
of time. But a school calendar's "Essay 2 due" is not busy time the user should
schedule around — it is work they need periods allocated *before*. Without this
module the whole prep-allocation half of the engine has nothing to act on.

Pure logic, like `app/scheduler.py`: strings and enums in, a verdict out. The
keyword table is a module constant rather than a database table on purpose —
it is versioned in git, diffable in review, and testable without fixtures.
Move it into the database only when users need their own keywords.

`classify` is the single entry point, so a model-backed classifier can replace
the matching below without any caller changing.
"""

import re
from dataclasses import dataclass

from app.models import CalendarKind, EventType

# Length of a period is a user preference, so prep hints are expressed in
# minutes and rounded into periods by the engine. These are deliberately
# coarse: the point is "an exam needs more than a quiz", not an estimate
# anyone should trust. Users correct them in #13, which sets type_locked.
QUICK = 60
MEDIUM = 90
SUBSTANTIAL = 180


@dataclass(frozen=True)
class Keyword:
    """A word that suggests a deadline, and roughly how much work it implies."""

    word: str
    prep_minutes: int
    # Which sorts of calendar this applies to. "Lab" means something on a
    # school calendar that it does not on a work one.
    kinds: frozenset[CalendarKind]


_ACADEMIC = frozenset({CalendarKind.SCHOOL})
_PROFESSIONAL = frozenset({CalendarKind.WORK})
_ANY_MANAGED = frozenset({CalendarKind.SCHOOL, CalendarKind.WORK})


# Ordered by prep weight so that the heaviest match wins when a title contains
# several — "final project proposal" should read as the project, not the noun
# "proposal" alone.
KEYWORDS: tuple[Keyword, ...] = (
    # Unambiguous on any managed calendar.
    Keyword("deadline", MEDIUM, _ANY_MANAGED),
    Keyword("due", MEDIUM, _ANY_MANAGED),
    Keyword("submit", MEDIUM, _ANY_MANAGED),
    Keyword("submission", MEDIUM, _ANY_MANAGED),

    # School.
    Keyword("final", SUBSTANTIAL, _ACADEMIC),
    Keyword("midterm", SUBSTANTIAL, _ACADEMIC),
    Keyword("exam", SUBSTANTIAL, _ACADEMIC),
    Keyword("thesis", SUBSTANTIAL, _ACADEMIC),
    Keyword("dissertation", SUBSTANTIAL, _ACADEMIC),
    Keyword("project", SUBSTANTIAL, _ACADEMIC),
    Keyword("presentation", SUBSTANTIAL, _ACADEMIC),
    Keyword("essay", SUBSTANTIAL, _ACADEMIC),
    Keyword("paper", SUBSTANTIAL, _ACADEMIC),
    Keyword("assignment", MEDIUM, _ACADEMIC),
    Keyword("homework", MEDIUM, _ACADEMIC),
    Keyword("hw", MEDIUM, _ACADEMIC),
    Keyword("pset", MEDIUM, _ACADEMIC),
    Keyword("problem set", MEDIUM, _ACADEMIC),
    Keyword("lab", MEDIUM, _ACADEMIC),
    Keyword("draft", MEDIUM, _ACADEMIC),
    Keyword("milestone", MEDIUM, _ACADEMIC),
    Keyword("quiz", QUICK, _ACADEMIC),
    Keyword("test", QUICK, _ACADEMIC),
    Keyword("reading", QUICK, _ACADEMIC),
    Keyword("response", QUICK, _ACADEMIC),

    # Work.
    Keyword("deliverable", SUBSTANTIAL, _PROFESSIONAL),
    Keyword("report", SUBSTANTIAL, _PROFESSIONAL),
    Keyword("proposal", SUBSTANTIAL, _PROFESSIONAL),
    Keyword("review", MEDIUM, _PROFESSIONAL),
    Keyword("filing", MEDIUM, _PROFESSIONAL),
    Keyword("invoice", QUICK, _PROFESSIONAL),
    Keyword("renewal", QUICK, _PROFESSIONAL),
    Keyword("expenses", QUICK, _PROFESSIONAL),
)


# Checked before the keywords above. An all-day "Reading day" or "Spring break"
# is the opposite of work to prepare for, but would otherwise match "reading".
EXCLUSIONS: tuple[str, ...] = (
    "break",
    "holiday",
    "vacation",
    "recess",
    "no class",
    "no classes",
    "cancelled",
    "canceled",
    "closed",
    "day off",
    "out of office",
    "ooo",
    "pto",
    "reading day",
    "study day",
    "birthday",
    "anniversary",
)


@dataclass(frozen=True)
class Classification:
    """What an imported event should become."""

    event_type: EventType
    # None for one_time events, and for deadlines whose keyword carries no
    # estimate. The engine reads None as "unknown", not "no work".
    prep_minutes: int | None = None
    # Which keyword fired, kept so the UI can explain the guess and so a wrong
    # inference is debuggable rather than mysterious.
    matched: str | None = None


def _mentions(title: str, phrase: str) -> bool:
    """Word-boundary, case-insensitive match.

    Substring matching would read "duel" as "due" and "testimony" as "test".
    """
    return re.search(rf"\b{re.escape(phrase)}\b", title, re.IGNORECASE) is not None


def is_excluded(title: str) -> bool:
    return any(_mentions(title, phrase) for phrase in EXCLUSIONS)


def match_keyword(title: str, kind: CalendarKind) -> Keyword | None:
    """The heaviest keyword in the title that applies to this calendar kind."""
    matches = [
        keyword for keyword in KEYWORDS
        if kind in keyword.kinds and _mentions(title, keyword.word)
    ]
    if not matches:
        return None
    # Ties broken by table order, which is stable, so the result is too.
    return max(matches, key=lambda keyword: keyword.prep_minutes)


def classify(
    title: str,
    is_all_day: bool,
    kind: CalendarKind,
) -> Classification:
    """Decide whether an imported event is a deadline or committed time.

    Two rules do most of the work:

    * A *timed* event is never a deadline. A lecture, a meeting, an exam
      sitting — these occupy the calendar at a known hour, so they are busy
      time to schedule around. School calendars are mostly this.
    * An *all-day* event on a managed calendar is a deadline if its title says
      so. This is how school calendars express assignments: no hour, just a
      date they are owed by.

    Personal calendars are never inferred against. Someone's own calendar is
    full of words like "test" and "review" that mean nothing of the sort, and a
    wrong guess there costs more than the feature gains.
    """
    if kind == CalendarKind.PERSONAL:
        return Classification(EventType.ONE_TIME)

    if not is_all_day:
        return Classification(EventType.ONE_TIME)

    if is_excluded(title):
        return Classification(EventType.ONE_TIME)

    keyword = match_keyword(title, kind)
    if keyword is None:
        return Classification(EventType.ONE_TIME)

    return Classification(
        event_type=EventType.DEADLINE,
        prep_minutes=keyword.prep_minutes,
        matched=keyword.word,
    )
