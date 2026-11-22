"""Turns time phrases like 'last week' into exact date ranges based on the last complete day."""
from __future__ import annotations

from datetime import date, timedelta

from core.models import AnalysisIntent, Period, TimeSpec


class TimeResolutionError(ValueError):
    pass


def _parse(d: str | None, field: str) -> date:
    if not d:
        raise TimeResolutionError(f"Missing {field} date")
    try:
        return date.fromisoformat(d)
    except ValueError as e:
        raise TimeResolutionError(f"Invalid {field} date '{d}' (expected YYYY-MM-DD)") from e


def resolve_spec(spec: TimeSpec, last_complete: date, assumptions: list[str]) -> Period:
    if spec.kind == "last_full_week":
        # most recent Monday-Sunday week that ends on or before last_complete
        end = last_complete - timedelta(days=(last_complete.weekday() + 1) % 7)
        start = end - timedelta(days=6)
        rolling = (last_complete - timedelta(days=6), last_complete)
        same = rolling == (start, end)
        assumptions.append(
            f"'Last week' = last full calendar week Mon-Sun ({start:%d %b} - {end:%d %b})"
            + (" - identical to the last 7 complete days here." if same else
               f". Last 7 complete days would be {rolling[0]:%d %b} - {rolling[1]:%d %b}."))
        return Period("current", start, end)
    if spec.kind == "last_n_days":
        n = spec.n_days or 7
        p = Period("current", last_complete - timedelta(days=n - 1), last_complete)
        assumptions.append(f"Last {n} complete days ({p.pretty()}).")
        return p
    if spec.kind == "this_week":
        start = last_complete - timedelta(days=last_complete.weekday())
        assumptions.append(f"'This week' = {start:%d %b} up to the last complete day {last_complete:%d %b} (partial week).")
        return Period("current", start, last_complete)
    if spec.kind == "yesterday":
        assumptions.append(f"'Yesterday' = last complete day in the data ({last_complete:%d %b %Y}).")
        return Period("current", last_complete, last_complete)
    if spec.kind == "explicit":
        start = _parse(spec.start, "start")
        end = _parse(spec.end, "end") if spec.end else start + timedelta(days=6)
        if not spec.end:
            assumptions.append(f"Only a start date was given; used 7 days {start:%d %b} - {end:%d %b}.")
        if end < start:
            raise TimeResolutionError("End date is before start date")
        return Period("current", start, end)
    # unspecified
    p = Period("current", last_complete - timedelta(days=6), last_complete)
    assumptions.append(f"No time period given: used the last 7 complete days ({p.pretty()}).")
    return p


def requested_days(spec: TimeSpec) -> int | None:
    """How many days the user asked for, before trimming to the data range (used by the query limit)."""
    if spec.kind == "last_n_days":
        return spec.n_days or 7
    if spec.kind == "explicit" and spec.start:
        try:
            end = date.fromisoformat(spec.end) if spec.end else date.fromisoformat(spec.start) + timedelta(days=6)
            return (end - date.fromisoformat(spec.start)).days + 1
        except ValueError:
            return None
    return None


def resolve_periods(intent: AnalysisIntent, last_complete: date, data_start: date,
                    assumptions: list[str]) -> tuple[Period, Period | None]:
    current = resolve_spec(intent.current_period, last_complete, assumptions)
    if current.end > last_complete:
        assumptions.append(f"Period end moved from {current.end:%d %b} to last complete day {last_complete:%d %b}.")
        current = Period("current", current.start, last_complete)
    if current.start < data_start:
        assumptions.append(f"Data starts on {data_start:%d %b %Y}; period start moved accordingly.")
        current = Period("current", data_start, current.end)
    if current.end < current.start:
        raise TimeResolutionError("Requested period has no data")

    wants_comparison = intent.comparison != "none" or intent.analysis_type == "root_cause"
    if not wants_comparison:
        return current, None
    if intent.comparison == "explicit" and intent.comparison_period:
        prev = resolve_spec(intent.comparison_period, last_complete, assumptions)
        prev = Period("previous", prev.start, prev.end)
    else:
        prev = Period("previous", current.start - timedelta(days=current.days), current.start - timedelta(days=1))
        if intent.comparison == "none":
            assumptions.append("Root-cause analysis needs a baseline: compared with the immediately preceding period.")
        assumptions.append(f"Comparison period = the {current.days} days before ({prev.pretty()}).")
    if prev.start < data_start:
        raise TimeResolutionError(
            f"Comparison period starts {prev.start:%d %b} but data starts {data_start:%d %b}; choose a later period.")
    return current, prev
