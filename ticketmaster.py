import os
import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://app.ticketmaster.com/discovery/v2"


def search_events(
    city: str,
    state_code: str | None = None,
    radius: int = 10,
    unit: str = "miles",
    start_date: str | None = None,
    end_date: str | None = None,
    classification: str | None = None,
    size: int = 20,
) -> list[dict]:
    """
    Search Ticketmaster for upcoming events near a location.

    Args:
        city: City name (e.g. "San Jose").
        state_code: Two-letter state code (e.g. "CA").
        radius: Search radius from city center.
        unit: "miles" or "km".
        start_date: ISO date string (YYYY-MM-DD). Defaults to today.
        end_date: ISO date string (YYYY-MM-DD). Defaults to start_date + 7 days.
        classification: Filter by segment name (e.g. "music", "sports").
        size: Max results to return (1-200).

    Returns:
        List of normalized event dicts with keys:
        name, date, time, venue, city, state, classification, url
    """
    api_key = os.environ.get("TICKETMASTER_API_KEY")
    if not api_key:
        raise ValueError("TICKETMASTER_API_KEY environment variable is required")

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=7)
        end_date = end_dt.strftime("%Y-%m-%d")

    params: dict = {
        "apikey": api_key,
        "city": city,
        "startDateTime": f"{start_date}T00:00:00Z",
        "endDateTime": f"{end_date}T23:59:59Z",
        "size": str(min(size, 200)),
        "sort": "date,asc",
        "countryCode": "US",
    }

    if state_code:
        params["stateCode"] = state_code
    if radius:
        params["radius"] = str(radius)
        params["unit"] = unit
    if classification:
        params["classificationName"] = classification

    logger.info(
        "Ticketmaster search: city=%s state=%s dates=%s-%s classification=%s",
        city, state_code, start_date, end_date, classification,
    )

    resp = httpx.get(f"{BASE_URL}/events.json", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    raw_events = data.get("_embedded", {}).get("events", [])
    logger.info("Ticketmaster returned %d events", len(raw_events))

    return [_normalize_event(e) for e in raw_events]


def _normalize_event(raw: dict) -> dict:
    """Extract the fields we care about from a raw Ticketmaster event."""
    dates = raw.get("dates", {}).get("start", {})
    venues = raw.get("_embedded", {}).get("venues", [{}])
    venue = venues[0] if venues else {}
    classifications = raw.get("classifications", [{}])
    primary_class = classifications[0] if classifications else {}

    return {
        "name": raw.get("name", "Unknown Event"),
        "date": dates.get("localDate", "TBD"),
        "time": dates.get("localTime", "TBD"),
        "venue": venue.get("name", "Unknown Venue"),
        "city": venue.get("city", {}).get("name", ""),
        "state": venue.get("state", {}).get("stateCode", ""),
        "classification": primary_class.get("segment", {}).get("name", "Other"),
        "genre": primary_class.get("genre", {}).get("name", ""),
        "url": raw.get("url", ""),
    }


def format_events_for_llm(events: list[dict], restaurant_info: dict) -> str:
    """
    Format Ticketmaster events into a context string for the LLM.

    Args:
        events: List of normalized event dicts from search_events().
        restaurant_info: Dict with keys like name, type, city, state.

    Returns:
        Formatted string ready to inject into the LLM prompt.
    """
    r = restaurant_info
    header = (
        f"Restaurant: {r.get('name', 'Our Restaurant')} "
        f"({r.get('type', 'general')}) in "
        f"{r.get('city', 'Unknown')}, {r.get('state', '')}\n\n"
        f"Upcoming events found near the restaurant:\n"
    )

    if not events:
        return header + "\nNo upcoming events found in this area."

    lines = []
    for e in events:
        line = (
            f"- {e['name']} | {e['classification']}"
            f"{' / ' + e['genre'] if e['genre'] else ''}"
            f" | Date: {e['date']} {e['time']}"
            f" | Venue: {e['venue']}, {e['city']} {e['state']}"
        )
        lines.append(line)

    return header + "\n".join(lines)
