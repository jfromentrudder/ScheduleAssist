"""Tests for deadline inference.

Pure string-in, verdict-out. Titles here are the sort of thing that actually
turns up on a university calendar, including the ones that should *not* be
read as work.
"""

import pytest

from app.inference import classify, match_keyword
from app.models import CalendarKind, EventType

SCHOOL = CalendarKind.SCHOOL
WORK = CalendarKind.WORK
PERSONAL = CalendarKind.PERSONAL


def school(title, all_day=True):
    return classify(title, all_day, SCHOOL)


# --- The two structural rules -------------------------------------------

@pytest.mark.parametrize("title", [
    "CS406 Lecture", "Office Hours", "Exam", "Final exam", "Lab section",
])
def test_a_timed_event_is_never_a_deadline(title):
    """A lecture and an exam sitting are both busy time at a known hour.

    Without this a school calendar full of recurring lectures would generate a
    prep period for every single one.
    """
    assert school(title, all_day=False).event_type == EventType.ONE_TIME


def test_an_all_day_event_with_a_keyword_is_a_deadline():
    result = school("Essay 2 due")
    assert result.event_type == EventType.DEADLINE
    # Both "essay" and "due" match; the heavier one is the useful estimate.
    assert result.matched == "essay"
    assert result.prep_minutes


def test_an_all_day_event_without_a_keyword_stays_committed_time():
    assert school("Department retreat").event_type == EventType.ONE_TIME


# --- Calendar kind changes the reading ----------------------------------

@pytest.mark.parametrize("title", [
    "Essay 2 due", "Final project", "Midterm", "Quiz 3", "Problem set 4",
])
def test_personal_calendars_are_never_inferred_against(title):
    """"Review", "test" and "project" mean nothing scholarly on a personal
    calendar, and a wrong guess there costs more than the feature gains."""
    assert classify(title, True, PERSONAL).event_type == EventType.ONE_TIME


def test_academic_words_do_not_fire_on_a_work_calendar():
    assert classify("Problem set 4", True, WORK).event_type == EventType.ONE_TIME


def test_work_words_do_not_fire_on_a_school_calendar():
    assert school("Expenses").event_type == EventType.ONE_TIME


def test_generic_deadline_words_fire_on_both():
    for kind in (SCHOOL, WORK):
        assert classify("Tax forms due", True,
                        kind).event_type == EventType.DEADLINE


def test_work_calendars_recognise_their_own_vocabulary():
    result = classify("Q3 report", True, WORK)
    assert result.event_type == EventType.DEADLINE
    assert result.matched == "report"


# --- Exclusions ---------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Reading day",
    "Spring break",
    "Winter recess",
    "No class",
    "Thanksgiving holiday",
    "Midterm exam — cancelled",
    "PTO",
])
def test_days_off_are_not_deadlines(title):
    """"Reading day" would otherwise match "reading" and invent work."""
    assert school(title).event_type == EventType.ONE_TIME


# --- Matching precision -------------------------------------------------

@pytest.mark.parametrize("title", [
    "Duel Club",          # contains "due"
    "Testimony workshop",  # contains "test"
    "Labrador meetup",    # contains "lab"
    "Papers, Please tournament",  # "papers" is not "paper"
])
def test_substrings_do_not_count_as_matches(title):
    assert school(title).event_type == EventType.ONE_TIME


def test_matching_is_case_insensitive():
    assert school("ESSAY 1 DUE").event_type == EventType.DEADLINE


def test_punctuation_does_not_hide_a_keyword():
    assert school("Lab #3, due Friday").event_type == EventType.DEADLINE


# --- Prep estimates -----------------------------------------------------

def test_heavier_work_gets_a_bigger_estimate():
    assert school("Final exam paper").prep_minutes > school(
        "Quiz 2").prep_minutes


def test_the_heaviest_keyword_in_a_title_wins():
    """"Final project due" is substantial work, not the 90 minutes "due" alone
    would imply. Which of the two equally-heavy words is reported is arbitrary;
    the estimate they agree on is what matters."""
    result = school("Final project due")
    assert result.matched in {"final", "project"}
    assert result.prep_minutes == school("Quiz 2").prep_minutes * 3


def test_every_inferred_deadline_carries_an_estimate():
    """A deadline with no estimate would allocate a single token period, which
    defeats the point of inferring it at all."""
    for keyword in ("essay", "quiz", "assignment", "due", "midterm"):
        result = school(f"Something {keyword}")
        assert result.event_type == EventType.DEADLINE
        assert result.prep_minutes and result.prep_minutes > 0


def test_a_one_time_event_carries_no_estimate():
    assert school("Department retreat").prep_minutes is None


# --- Determinism --------------------------------------------------------

def test_classification_is_deterministic():
    title = "Final project draft due"
    assert [school(title) for _ in range(5)].count(school(title)) == 5


def test_match_keyword_ignores_keywords_from_other_kinds():
    assert match_keyword("Invoice", SCHOOL) is None
    assert match_keyword("Invoice", WORK) is not None
