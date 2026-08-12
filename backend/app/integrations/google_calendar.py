"""Thin client for the Google Calendar events API.

Two things about Google's sync model shape everything here:

* `singleEvents=true` expands a recurring event into its individual instances,
  which is what a calendar view wants. It also means the response is bounded by
  the time window rather than the recurrence rule.
* A `syncToken` from a previous response returns only what changed since. It is
  invalidated after roughly a week, or whenever the query parameters change,
  and the API says so with a 410 — which is a normal event, not a failure.
"""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import httpx

BASE_URL = "https://www.googleapis.com/calendar/v3"
CALENDAR_LIST_URL = f"{BASE_URL}/users/me/calendarList"


def events_url(calendar_id: str) -> str:
    """Events live under the calendar they belong to, not under the account.

    Reading only `primary` would miss every other calendar in the account —
    which is most of them for anyone keeping work and personal apart.
    """
    return f"{BASE_URL}/calendars/{quote(calendar_id, safe='')}/events"


# Google's own ceiling per page.
PAGE_SIZE = 250

# Total pages one sync will walk before giving up, so a pathological calendar
# cannot hold a request open indefinitely.
MAX_PAGES = 20


class SyncTokenExpired(Exception):
    """The stored syncToken is no longer usable; a full import is required."""


@dataclass(frozen=True)
class EventPage:
    items: list[dict]
    next_page_token: str | None
    # Present only on the final page of a sync, and stored for next time.
    next_sync_token: str | None


def _get(url: str, access_token: str, params: dict) -> dict:
    response = httpx.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code == 410:
        # Expected once a token ages out. The caller drops it and re-imports.
        raise SyncTokenExpired()
    response.raise_for_status()
    return response.json()


def fetch_calendar_list(access_token: str) -> list[dict]:
    """Every calendar the account can see, including subscribed ones.

    This is the list Google Calendar shows with checkboxes down the left, and
    Apple's Calendar nests under each account.
    """
    items: list[dict] = []
    page_token: str | None = None

    for _ in range(MAX_PAGES):
        params: dict[str, object] = {"maxResults": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        payload = _get(CALENDAR_LIST_URL, access_token, params)
        items.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return items


def fetch_page(
    access_token: str,
    calendar_id: str,
    *,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    sync_token: str | None = None,
    page_token: str | None = None,
) -> EventPage:
    """One page of events, either a windowed import or an incremental sync.

    `time_min`/`time_max` and `sync_token` are mutually exclusive: Google
    rejects a request carrying both, because the token already encodes the
    window it was issued for.
    """
    params: dict[str, object] = {
        "singleEvents": "true",
        "showDeleted": "true",
        "maxResults": PAGE_SIZE,
    }

    if sync_token:
        params["syncToken"] = sync_token
    else:
        if time_min:
            params["timeMin"] = time_min.isoformat()
        if time_max:
            params["timeMax"] = time_max.isoformat()
    if page_token:
        params["pageToken"] = page_token

    payload = _get(events_url(calendar_id), access_token, params)
    return EventPage(
        items=payload.get("items", []),
        next_page_token=payload.get("nextPageToken"),
        next_sync_token=payload.get("nextSyncToken"),
    )


def fetch_all(
    access_token: str,
    calendar_id: str,
    *,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    sync_token: str | None = None,
) -> tuple[list[dict], str | None]:
    """Walk every page, returning the events and the token for next time."""
    items: list[dict] = []
    page_token: str | None = None
    next_sync_token: str | None = None

    for _ in range(MAX_PAGES):
        page = fetch_page(
            access_token, calendar_id, time_min=time_min, time_max=time_max,
            sync_token=sync_token, page_token=page_token,
        )
        items.extend(page.items)
        next_sync_token = page.next_sync_token or next_sync_token
        page_token = page.next_page_token
        if not page_token:
            break

    return items, next_sync_token
