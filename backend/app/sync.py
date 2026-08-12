"""Importing a connected calendar's events into the local schedule.

Turns Google's event payloads into `Event` rows, running each through
`app/inference.py` to decide whether it is committed time or a deadline. The
network lives in `app/google_calendar.py`; everything here is mapping and
persistence, so the interesting parts are testable with plain dicts.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import google_calendar
from app.calendar_tokens import CalendarReauthRequired, get_access_token
from app.inference import classify
from app.models import (
    Availability, Calendar, CalendarConnection, Event, EventSource, EventType,
)
from app.periods import clear_orphaned_periods

# How much of the calendar an import covers. Wide enough to hold next term's
# deadlines, bounded so a decade-old calendar is not dragged in wholesale.
IMPORT_PAST = timedelta(days=30)
IMPORT_FUTURE = timedelta(days=180)


@dataclass(frozen=True)
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    # True when a stale sync token forced a full re-import.
    full_resync: bool = False


def _parse_endpoint(value: dict) -> tuple[datetime | None, date | None]:
    """Read one end of a Google event, which is either a time or a date.

    An all-day event carries `date`; everything else carries `dateTime`. Which
    one is present is how the API signals all-day, so both are returned and the
    caller decides.
    """
    if "dateTime" in value:
        raw = value["dateTime"]
        # Google returns "…Z", which fromisoformat only accepts from Python
        # 3.11. The project targets 3.10, so normalize it here.
        if raw.endswith(("Z", "z")):
            raw = f"{raw[:-1]}+00:00"
        stamp = datetime.fromisoformat(raw)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc), None
    if "date" in value:
        return None, date.fromisoformat(value["date"])
    return None, None


def deadline_moment(day: date, tz: ZoneInfo) -> datetime:
    """When an all-day assignment is actually due.

    Google gives a bare date, but the engine needs an instant to schedule
    before. The end of that day in the user's own timezone is the reading that
    matches how people talk: "due Friday" means by the end of Friday.
    """
    midnight_after = datetime.combine(day + timedelta(days=1), time(0, 0),
                                      tzinfo=tz)
    return (midnight_after - timedelta(minutes=1)).astimezone(timezone.utc)


def infer_availability(payload: dict, is_all_day: bool) -> Availability:
    """Whether an imported event occupies the user's time.

    Google already records this: `transparency: "transparent"` is the "Free"
    setting in its UI. Ignoring it meant every event a user had deliberately
    marked free was still blocking their schedule.

    Nothing is inferred as a work window — that is a judgement about what the
    user does with their time, so it stays theirs to set in #13.
    """
    if is_all_day:
        # An all-day entry is a label on the day, not a claim on its hours.
        return Availability.FREE
    if payload.get("transparency") == "transparent":
        return Availability.FREE
    return Availability.BUSY


def apply_payload(
    event: Event,
    payload: dict,
    kind,
    tz: ZoneInfo,
) -> bool:
    """Copy a Google event onto an Event row. False if it should be skipped.

    The events table has a CHECK constraint tying the time columns to the event
    type: a deadline has `due_at` and no span, a one_time event has a span and
    no `due_at`. Writing both would raise, so the columns are set from the
    classified type rather than from whatever Google happened to send.
    """
    title = payload.get("summary") or "(untitled)"
    starts_at, start_date = _parse_endpoint(payload.get("start", {}))
    ends_at, end_date = _parse_endpoint(payload.get("end", {}))

    is_all_day = start_date is not None
    if not is_all_day and (starts_at is None or ends_at is None):
        # Neither a span nor a date: nothing the schedule can position.
        return False

    event.title = title
    event.description = payload.get("description")
    event.is_all_day = is_all_day

    # A user's correction outranks any guess we would make, so re-syncing
    # updates the wording and timing but leaves the classification alone.
    if event.type_locked:
        verdict_type = event.event_type
    else:
        verdict = classify(title, is_all_day, kind)
        verdict_type = verdict.event_type
        event.expected_prep_minutes = verdict.prep_minutes
        event.availability = infer_availability(payload, is_all_day)

    event.event_type = verdict_type

    if verdict_type == EventType.DEADLINE:
        event.due_at = deadline_moment(start_date, tz)
        event.starts_at = None
        event.ends_at = None
    else:
        event.due_at = None
        if is_all_day:
            # Google's end date is exclusive, so a one-day event ends on the
            # following date. Clamped to at least a day because a payload where
            # end does not exceed start would violate the end-after-start
            # constraint and fail the whole import.
            last_day = (end_date if end_date and end_date > start_date
                        else start_date + timedelta(days=1))
            event.starts_at = datetime.combine(
                start_date, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
            event.ends_at = datetime.combine(
                last_day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        else:
            event.starts_at = starts_at
            event.ends_at = ends_at

    return True


def _existing(db: Session, calendar: Calendar) -> dict[str, Event]:
    rows = db.scalars(
        select(Event).where(
            Event.calendar_id == calendar.id,
            Event.provider_event_id.is_not(None),
        )
    ).all()
    return {row.provider_event_id: row for row in rows}


def apply_events(
    db: Session,
    calendar: Calendar,
    payloads: list[dict],
    tz: ZoneInfo,
) -> SyncResult:
    """Upsert a batch of Google events, honouring cancellations."""
    known = _existing(db, calendar)
    created = updated = deleted = 0

    for payload in payloads:
        provider_id = payload.get("id")
        if not provider_id:
            continue

        existing = known.get(provider_id)

        # Incremental syncs report deletions as cancelled rather than omitting
        # them, which is the only way to learn an event went away.
        if payload.get("status") == "cancelled":
            if existing is not None:
                db.delete(existing)
                deleted += 1
            continue

        event = existing
        if event is None:
            event = Event(
                user_id=calendar.connection.user_id,
                source=EventSource.IMPORTED,
                calendar_id=calendar.id,
                provider_event_id=provider_id,
                # Overwritten by apply_payload; set so the row is never
                # momentarily in a state the CHECK constraint rejects.
                event_type=EventType.ONE_TIME,
                title="",
            )

        if not apply_payload(event, payload, calendar.kind, tz):
            continue

        if existing is None:
            db.add(event)
            created += 1
        else:
            updated += 1

    return SyncResult(created=created, updated=updated, deleted=deleted)


def discover_calendars(
    db: Session, connection: CalendarConnection, access_token: str
) -> list[Calendar]:
    """Refresh the list of calendars in the account.

    Matches on the provider's calendar id, so renaming or recolouring a
    calendar in Google updates the existing row rather than creating a second
    one, and the user's own selection survives.
    """
    known = {c.provider_calendar_id: c for c in connection.calendars}

    for payload in google_calendar.fetch_calendar_list(access_token):
        provider_id = payload.get("id")
        if not provider_id:
            continue

        calendar = known.get(provider_id)
        if calendar is None:
            calendar = Calendar(
                calendar_connection_id=connection.id,
                provider_calendar_id=provider_id,
                # Mirror whether the user has this calendar ticked in Google,
                # so what they see here matches what they already curate there.
                selected=bool(payload.get("selected", False))
                or bool(payload.get("primary", False)),
                kind=connection.default_kind,
            )
            db.add(calendar)
            connection.calendars.append(calendar)

        # Presentation follows the provider; selection and kind are the user's.
        calendar.name = payload.get("summaryOverride") or payload.get(
            "summary") or provider_id
        calendar.description = payload.get("description")
        calendar.color = payload.get("backgroundColor")
        calendar.is_primary = bool(payload.get("primary", False))

    db.commit()
    return list(connection.calendars)


def sync_calendar(
    db: Session,
    calendar: Calendar,
    access_token: str,
    *,
    now: datetime,
) -> SyncResult:
    """Import or refresh one calendar's events.

    Uses the stored sync token when there is one, and falls back to a full
    windowed import when Google says it has expired.
    """
    tz = ZoneInfo(calendar.connection.user.timezone)
    provider_id = calendar.provider_calendar_id
    sync_token = calendar.sync_token
    full_resync = sync_token is None

    def full_import() -> tuple[list[dict], str | None]:
        return google_calendar.fetch_all(
            access_token, provider_id,
            time_min=now - IMPORT_PAST,
            time_max=now + IMPORT_FUTURE,
        )

    if sync_token:
        try:
            payloads, next_token = google_calendar.fetch_all(
                access_token, provider_id, sync_token=sync_token)
        except google_calendar.SyncTokenExpired:
            payloads, next_token = full_import()
            full_resync = True
    else:
        payloads, next_token = full_import()

    result = apply_events(db, calendar, payloads, tz)

    calendar.sync_token = next_token
    calendar.last_synced_at = now
    calendar.last_sync_error = None
    db.commit()

    # An event cancelled at the provider leaves its periods behind, holding
    # time for work that no longer exists.
    if result.deleted:
        clear_orphaned_periods(db, calendar.connection.user_id)

    return SyncResult(result.created, result.updated, result.deleted,
                      full_resync)


def clear_calendar(db: Session, calendar: Calendar) -> int:
    """Drop everything imported from a calendar the user has unticked.

    An unselected calendar must not keep blocking out work periods, so its
    events go rather than being hidden. Clearing the token means re-selecting
    it does a fresh full import.

    Periods allocated for deadlines this calendar supplied go with them. This
    is a bulk delete, so the ORM never sees the rows and only the database-level
    cascade on `period_events` fires — which unlinks the periods without
    removing them.
    """
    removed = db.query(Event).filter(Event.calendar_id == calendar.id).delete()
    calendar.sync_token = None
    calendar.last_synced_at = None
    db.commit()
    clear_orphaned_periods(db, calendar.connection.user_id)
    return removed


def sync_connection(
    db: Session,
    connection: CalendarConnection,
    *,
    now: datetime | None = None,
) -> SyncResult:
    """Refresh the account's calendar list, then sync every selected calendar.

    One calendar failing does not abandon the rest: the error is recorded
    against that calendar and the others still import.
    """
    now = now or datetime.now(timezone.utc)
    access_token = get_access_token(db, connection)

    calendars = discover_calendars(db, connection, access_token)

    created = updated = deleted = 0
    full_resync = False
    failures = 0

    for calendar in calendars:
        if not calendar.selected:
            continue
        try:
            result = sync_calendar(db, calendar, access_token, now=now)
        except CalendarReauthRequired:
            raise
        except Exception as failure:  # noqa: BLE001 - recorded per calendar
            calendar.last_sync_error = f"Could not import events: {failure}"
            failures += 1
            db.commit()
            continue

        created += result.created
        updated += result.updated
        deleted += result.deleted
        full_resync = full_resync or result.full_resync

    connection.last_synced_at = now
    connection.last_sync_error = (
        f"{failures} calendar(s) could not be imported" if failures else None)
    db.commit()

    return SyncResult(created, updated, deleted, full_resync)


def sync_quietly(db: Session, connection: CalendarConnection) -> None:
    """Sync without letting a failure break the caller.

    Used on the connect path, where the calendar is already linked and a failed
    first import should surface as a message on the connection rather than an
    error page over a flow that otherwise succeeded.
    """
    try:
        sync_connection(db, connection)
    except CalendarReauthRequired:
        connection.last_sync_error = "Access expired. Please reconnect this calendar."
        db.commit()
    except Exception as failure:  # noqa: BLE001 - recorded, not swallowed
        connection.last_sync_error = f"Could not import events: {failure}"
        db.commit()
