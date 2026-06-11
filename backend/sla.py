"""SLA evaluation for DAG runs.

A "breach" can be one of:
  - deadline_missed   — daily wall-clock deadline passed before run finished successfully
  - max_runtime       — single run exceeded its max_runtime_seconds budget

Logic is pure (no DB, no HTTP). Callers fetch runs + configs and pass them in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


@dataclass
class SlaBreach:
    kind: str           # "deadline_missed" | "max_runtime"
    message: str        # human-readable description
    target_seconds: float  # for max_runtime: the budget; for deadline: seconds past deadline


def _parse_hhmm(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except Exception:
        return None


def _resolve_tz(name: Optional[str]):
    if not name or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def todays_deadline(deadline_time: str, deadline_tz: Optional[str], now_utc: datetime) -> Optional[datetime]:
    """Return today's deadline as a UTC naive datetime, given an HH:MM in deadline_tz.

    "Today" is determined in the configured timezone — so a 09:00 America/Los_Angeles
    deadline always means 09:00 LA-time on the calendar day in LA, even when the user
    is checking from another tz.
    """
    t = _parse_hhmm(deadline_time)
    if t is None:
        return None
    tz = _resolve_tz(deadline_tz)
    # Move "now" into the deadline's timezone to find today's calendar date there
    aware_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    local_deadline = aware_now.replace(
        hour=t.hour, minute=t.minute, second=0, microsecond=0,
    )
    # Convert back to UTC and drop tzinfo to match how we store start_date
    return local_deadline.astimezone(timezone.utc).replace(tzinfo=None)


def evaluate_run(
    run,                  # DAGRun-like: state, start_date, end_date, duration_seconds
    config,               # DagSlaConfig-like, or None
    now_utc: datetime,
) -> Optional[SlaBreach]:
    """Returns a breach if this completed run violates its SLA, else None.

    Only evaluates terminal-state runs (success/failed). For success: only deadline_missed
    matters. For failed: both checks apply (a failed run that timed out or missed deadline
    breaches SLA, even though it's also a failure — these are distinct alerts).
    """
    if config is None or not config.enabled:
        return None

    # Max-runtime check applies to any completed run with a known duration
    if config.max_runtime_seconds and run.duration_seconds is not None:
        if run.duration_seconds > config.max_runtime_seconds:
            return SlaBreach(
                kind="max_runtime",
                message=(
                    f"ran {int(run.duration_seconds)}s, exceeds max "
                    f"{config.max_runtime_seconds}s"
                ),
                target_seconds=float(config.max_runtime_seconds),
            )

    # Deadline check: did a run that started "for today's deadline" fail to finish in time?
    if config.deadline_time and run.start_date and run.end_date:
        deadline = todays_deadline(config.deadline_time, config.deadline_timezone, now_utc)
        if deadline is not None:
            # The deadline that THIS run was racing against is the next deadline at-or-after
            # its start_date. If the run started at 04:00 UTC and deadline is 09:00 UTC,
            # they're racing today's. If it started at 10:00 UTC, they're racing tomorrow's.
            relevant_deadline = _relevant_deadline_for_run(
                config.deadline_time, config.deadline_timezone, run.start_date,
            )
            if relevant_deadline is not None and run.end_date > relevant_deadline:
                seconds_late = (run.end_date - relevant_deadline).total_seconds()
                return SlaBreach(
                    kind="deadline_missed",
                    message=(
                        f"finished {int(seconds_late)}s past deadline "
                        f"{config.deadline_time} {config.deadline_timezone or 'UTC'}"
                    ),
                    target_seconds=seconds_late,
                )

    return None


def _relevant_deadline_for_run(
    deadline_time: Optional[str],
    deadline_tz: Optional[str],
    run_start_utc_naive: datetime,
) -> Optional[datetime]:
    """The next deadline at or after the run's start, in UTC naive time."""
    t = _parse_hhmm(deadline_time)
    if t is None:
        return None
    tz = _resolve_tz(deadline_tz)
    aware_start = run_start_utc_naive.replace(tzinfo=timezone.utc).astimezone(tz)
    candidate = aware_start.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if candidate < aware_start:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc).replace(tzinfo=None)


def at_risk(
    config,               # DagSlaConfig
    last_run,             # most recent DAGRun for this DAG, or None
    now_utc: datetime,
) -> Optional[str]:
    """Returns a human-readable reason if this DAG is at risk of breaching today's deadline.

    "At risk" means: there is a deadline for today, today's deadline hasn't been met
    (no successful run today after the previous deadline), and the deadline is within
    the next 60 minutes (or has just passed).
    """
    if config is None or not config.enabled or not config.deadline_time:
        return None

    deadline = todays_deadline(config.deadline_time, config.deadline_timezone, now_utc)
    if deadline is None:
        return None

    # If today's deadline is more than 60 min away, not yet at-risk
    seconds_until = (deadline - now_utc).total_seconds()
    if seconds_until > 3600:
        return None

    # If we already have a successful run between (deadline - 24h) and deadline+grace, we're safe
    # (caller checks; here we only have last_run)
    if last_run is not None and last_run.state == "success" and last_run.end_date:
        # The previous deadline = today's - 24h
        previous_deadline = deadline - timedelta(days=1)
        if last_run.end_date > previous_deadline and last_run.end_date <= deadline:
            # successful run finished within the eligibility window — safe
            return None

    if seconds_until > 0:
        mins = int(seconds_until // 60)
        return f"deadline {config.deadline_time} {config.deadline_timezone or 'UTC'} in {mins} min, no success yet"
    else:
        mins = int(abs(seconds_until) // 60)
        return f"deadline {config.deadline_time} {config.deadline_timezone or 'UTC'} passed {mins} min ago, no success today"
