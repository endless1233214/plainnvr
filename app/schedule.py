import re
from datetime import datetime


DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def default_schedule():
    return {"mode": "always", "days": {day: [] for day in DAY_KEYS}}


def normalize_schedule(value):
    if not isinstance(value, dict):
        return default_schedule()
    mode = value.get("mode", "always")
    days = value.get("days") if isinstance(value.get("days"), dict) else {}
    normalized = {"mode": "weekly" if mode == "weekly" else "always", "days": {}}
    for day in DAY_KEYS:
        windows = []
        for item in days.get(day, []):
            if not isinstance(item, dict):
                continue
            start = str(item.get("start", "")).strip()
            end = str(item.get("end", "")).strip()
            if re.match(r"^\d{2}:\d{2}$", start) and re.match(r"^\d{2}:\d{2}$", end):
                windows.append({"start": start, "end": end})
        normalized["days"][day] = windows
    return normalized


def time_to_minutes(value):
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def schedule_active(schedule, now=None):
    schedule = normalize_schedule(schedule)
    if schedule["mode"] == "always":
        return True
    now = now or datetime.now()
    day_key = DAY_KEYS[now.weekday()]
    current = now.hour * 60 + now.minute
    for window in schedule["days"].get(day_key, []):
        start = time_to_minutes(window["start"])
        end = time_to_minutes(window["end"])
        if start == end:
            return True
        if start < end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False
