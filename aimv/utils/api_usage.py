"""
API call usage tracker for AIMV.

Persists daily call counts to a JSON file in ~/.aimv/ and enforces
both a daily cap and a per-minute (RPM) rate limit.
"""

import json
import os
import time
from collections import deque
from datetime import date, datetime
from typing import Deque, Dict, Optional


class APILimitExceeded(Exception):
    """Raised when the daily API call limit has been reached."""


class APIUsageTracker:
    """Track and enforce daily API call limits and per-minute rate limits."""

    def __init__(self, usage_path: str, daily_limit: int, rpm_limit: int = 0):
        self.usage_path = usage_path
        self.daily_limit = daily_limit
        self.rpm_limit = rpm_limit
        self._data: Dict = self._load()
        self._recent_timestamps: Deque[float] = deque()

    def _load(self) -> Dict:
        if not os.path.exists(self.usage_path):
            return {"days": {}}
        try:
            with open(self.usage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "days" not in data:
                return {"days": {}}
            return data
        except (json.JSONDecodeError, OSError):
            return {"days": {}}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.usage_path), exist_ok=True)
            with open(self.usage_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            print(f"Warning: Could not save API usage data: {e}")

    def _today_key(self) -> str:
        return date.today().isoformat()

    def _today_entry(self) -> Dict:
        key = self._today_key()
        if key not in self._data["days"]:
            self._data["days"][key] = {"calls": 0, "first_call": None, "last_call": None}
        return self._data["days"][key]

    def calls_today(self) -> int:
        return self._today_entry()["calls"]

    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.calls_today())

    def _prune_rpm_window(self) -> None:
        """Remove timestamps older than 60 seconds from the sliding window."""
        cutoff = time.monotonic() - 60.0
        while self._recent_timestamps and self._recent_timestamps[0] < cutoff:
            self._recent_timestamps.popleft()

    def check_limit(self) -> None:
        """Raise APILimitExceeded if daily limit hit; sleep if RPM limit hit."""
        if self.daily_limit > 0 and self.calls_today() >= self.daily_limit:
            raise APILimitExceeded(
                f"Daily API call limit reached ({self.daily_limit} calls). "
                f"Reset tomorrow or increase AIMV_MAX_API_CALLS_PER_DAY."
            )

        if self.rpm_limit > 0:
            self._prune_rpm_window()
            if len(self._recent_timestamps) >= self.rpm_limit:
                oldest = self._recent_timestamps[0]
                wait = 60.0 - (time.monotonic() - oldest)
                if wait > 0:
                    print(f"Rate limit ({self.rpm_limit} RPM): waiting {wait:.1f}s...")
                    time.sleep(wait)
                    self._prune_rpm_window()

    def record_call(self) -> int:
        """Increment today's call count, track RPM timestamp, and return new total."""
        entry = self._today_entry()
        now = datetime.now().isoformat(timespec="seconds")
        entry["calls"] += 1
        if entry["first_call"] is None:
            entry["first_call"] = now
        entry["last_call"] = now
        self._recent_timestamps.append(time.monotonic())
        self._save()
        return entry["calls"]

    def reset_today(self) -> None:
        """Reset today's usage counter."""
        key = self._today_key()
        self._data["days"].pop(key, None)
        self._save()

    def get_summary(self, last_n_days: int = 7) -> str:
        """Return a human-readable usage summary."""
        today = self._today_key()
        entry = self._today_entry()
        used = entry["calls"]
        limit = self.daily_limit

        lines = [
            f"Daily limit:  {used}/{limit} calls ({self.remaining_today()} remaining)",
            f"RPM limit:    {self.rpm_limit} calls/minute"
            + (f" (0 = unlimited)" if self.rpm_limit <= 0 else ""),
            f"Date:         {today}",
        ]

        if entry["first_call"]:
            lines.append(f"  First call: {entry['first_call']}")
        if entry["last_call"]:
            lines.append(f"  Last call:  {entry['last_call']}")

        sorted_days = sorted(self._data["days"].keys(), reverse=True)
        history = [d for d in sorted_days if d != today][:last_n_days]
        if history:
            lines.append(f"\nRecent history:")
            for day_key in history:
                day_data = self._data["days"][day_key]
                lines.append(f"  {day_key}: {day_data['calls']} calls")

        return "\n".join(lines)


_tracker: Optional[APIUsageTracker] = None


def get_tracker(usage_path: str, daily_limit: int, rpm_limit: int = 0) -> APIUsageTracker:
    """Return a shared singleton tracker instance."""
    global _tracker
    if _tracker is None or _tracker.usage_path != usage_path:
        _tracker = APIUsageTracker(usage_path, daily_limit, rpm_limit)
    return _tracker
