"""Calendrier serveur : 1er et 15 à 09:00, Casablanca, rattrapage 48 h."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Africa/Casablanca")
SITES = {"walmart": "https://www.walmart.com/", "academy": "https://www.academy.com/", "basspro": "https://www.basspro.com/"}


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def slots(now):
    local = aware(now).astimezone(ZONE)
    # Les échéances proches suffisent pour prochain passage et rattrapage.
    for delta in range(-2, 33):
        day = (local + timedelta(days=delta)).date()
        if day.day in (1, 15):
            yield datetime(day.year, day.month, day.day, 9, tzinfo=ZONE)


def due_slot(now, created_at):
    current = aware(now)
    eligible = [s for s in slots(now) if aware(created_at) <= s <= current and current - s <= timedelta(hours=48)]
    return max(eligible).date().isoformat() if eligible else None


def next_slot(now):
    return min(s for s in slots(now) if s > aware(now)).isoformat()
