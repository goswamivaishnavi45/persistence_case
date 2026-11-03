"""Cohort and persistence logic (Exhibit 1), written as small testable functions.

Rule IDs (used by the tests and cited by the methodology assistant):
  R1  Index event      first fill of BRAND_TRD (see IndexRule)
  R2  Intake window    index date between INTAKE_START and DATA_END - follow-up needed
  R3  Look-back        continuously enrolled for `lookback_days` before the index date
  R4  Look-forward     continuously enrolled for `lookforward_days` after the index date
  R5  Gap rule         a patient discontinues when supply runs out and no refill
                       arrives within `max_gap` days
  R6  Early refills    supply from early refills carries forward (no double counting)
  R7  Persistence      persistent if not discontinued before day `persistence_day` (182)
  R8  Time-to-event    Kaplan-Meier curve; patients who lose coverage are censored
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum

import numpy as np
import pandas as pd

BRAND = "BRAND_TRD"
DATA_START = pd.Timestamp("2021-01-01")
DATA_END = pd.Timestamp("2025-12-31")
INTAKE_START = DATA_START + pd.Timedelta(days=365)


class IndexRule(str, Enum):
    FIRST_EVER = "first_ever"          # original: first brand fill anywhere in the data
    FIRST_IN_WINDOW = "first_in_window"  # first fill on/after INTAKE_START, earlier fills ignored


@dataclass(frozen=True)
class Params:
    max_gap: int = 60
    lookback_days: int = 365
    lookforward_days: int = 365
    persistence_day: int = 182
    index_rule: IndexRule = IndexRule.FIRST_EVER

    def as_dict(self) -> dict:
        d = asdict(self)
        d["index_rule"] = self.index_rule.value
        return d


ORIGINAL = Params()


# --------------------------------------------------------------------------- #
# Enrolment helpers
# --------------------------------------------------------------------------- #
def merge_segments(segments: list[tuple[pd.Timestamp, pd.Timestamp]]):
    """Merge overlapping or back-to-back (next day) coverage segments."""
    segs = sorted(segments)
    merged: list[list[pd.Timestamp]] = []
    for s, e in segs:
        if merged and s <= merged[-1][1] + pd.Timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def covering_segment(segments, date: pd.Timestamp):
    """Return the merged segment containing `date`, or None."""
    for s, e in merge_segments(segments):
        if s <= date <= e:
            return s, e
    return None


def continuously_enrolled(segments, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    """R3/R4: True if one unbroken coverage segment spans [start, end]."""
    seg = covering_segment(segments, start)
    return seg is not None and seg[1] >= end


# --------------------------------------------------------------------------- #
# R1: index date
# --------------------------------------------------------------------------- #
def index_date(brand_fill_dates: list[pd.Timestamp], rule: IndexRule):
    dates = sorted(brand_fill_dates)
    if not dates:
        return None
    if rule is IndexRule.FIRST_EVER:
        return dates[0]
    later = [d for d in dates if d >= INTAKE_START]
    return later[0] if later else None


# --------------------------------------------------------------------------- #
# R5-R6: time to discontinuation
# --------------------------------------------------------------------------- #
def time_to_discontinuation(fills: list[tuple[int, int]], follow_end: int, max_gap: int):
    """fills: (day relative to index, days_supply), sorted, first fill at day 0.

    Returns (time, event). event=1 means discontinued at `time` (day supply ran
    out); event=0 means censored at `time` (end of observable follow-up).
    """
    covered_end = fills[0][0] + fills[0][1]
    for day, supply in fills[1:]:
        if day > follow_end:
            break
        if day - covered_end > max_gap:
            return covered_end, 1
        covered_end = max(covered_end, day) + supply   # R6 carry-over
    if follow_end - covered_end > max_gap:
        return covered_end, 1
    return follow_end, 0


# --------------------------------------------------------------------------- #
# Build the analysis cohort
# --------------------------------------------------------------------------- #
def build_cohort(fills: pd.DataFrame, enrol: pd.DataFrame, p: Params = ORIGINAL) -> pd.DataFrame:
    """One row per patient with a brand fill: inclusion status, reason, time, event."""
    brand = fills[fills["drug"] == BRAND]
    enrol_by = {pid: list(zip(g["enrol_start"], g["enrol_end"]))
                for pid, g in enrol.groupby("patient_id")}
    needed_follow = max(p.lookforward_days, p.persistence_day)
    intake_end = DATA_END - pd.Timedelta(days=needed_follow)

    rows = []
    for pid, g in brand.groupby("patient_id"):
        segs = enrol_by.get(pid, [])
        idx = index_date(list(g["fill_date"]), p.index_rule)
        row = {"patient_id": pid, "index_date": idx, "included": False,
               "reason": "", "time": np.nan, "event": np.nan}
        if idx is None or not (INTAKE_START <= idx <= intake_end):
            row["reason"] = "R2: index outside intake window"
            rows.append(row); continue
        if not continuously_enrolled(segs, idx - pd.Timedelta(days=p.lookback_days), idx):
            row["reason"] = "R3: failed look-back enrolment"
            rows.append(row); continue
        seg = covering_segment(segs, idx)
        follow_end_date = min(seg[1], DATA_END)
        if follow_end_date < idx + pd.Timedelta(days=p.lookforward_days):
            row["reason"] = "R4: failed look-forward enrolment"
            rows.append(row); continue

        g2 = g[g["fill_date"] >= idx]
        rel = [((d - idx).days, int(s)) for d, s in zip(g2["fill_date"], g2["days_supply"])]
        t, ev = time_to_discontinuation(rel, (follow_end_date - idx).days, p.max_gap)
        row.update(included=True, reason="included", time=t, event=ev)
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# R7-R8: results
# --------------------------------------------------------------------------- #
def kaplan_meier(time: np.ndarray, event: np.ndarray):
    """Return (times, survival) step function, starting at (0, 1.0)."""
    time, event = np.asarray(time, float), np.asarray(event, int)
    order = np.argsort(time)
    time, event = time[order], event[order]
    ts, surv, s, at_risk = [0.0], [1.0], 1.0, len(time)
    for t in np.unique(time):
        mask = time == t
        d = int(event[mask].sum())
        if d:
            s *= 1 - d / at_risk
            ts.append(float(t)); surv.append(s)
        at_risk -= int(mask.sum())
    return np.array(ts), np.array(surv)


def survival_at(ts, surv, day: float) -> float:
    i = np.searchsorted(ts, day, side="right") - 1
    return float(surv[max(i, 0)])


def summarise(cohort: pd.DataFrame, p: Params = ORIGINAL) -> dict:
    inc = cohort[cohort["included"]]
    P = p.persistence_day
    known = inc[(inc["event"] == 1) | (inc["time"] >= P)]
    persistent = known[(known["event"] == 0) | (known["time"] >= P)]
    ts, s = kaplan_meier(inc["time"], inc["event"]) if len(inc) else (np.array([0]), np.array([1]))
    lost = inc[(inc["event"] == 0) & (inc["time"] < P)]
    worst = (len(persistent)) / len(inc) if len(inc) else np.nan
    return {
        **p.as_dict(),
        "patients_with_fill": int(len(cohort)),
        "cohort_n": int(len(inc)),
        "pct_persistent_6m": round(100 * len(persistent) / len(known), 1) if len(known) else np.nan,
        "km_6m": round(100 * survival_at(ts, s, P - 0.5), 1),
        "censored_before_6m": int(len(lost)),
        "worst_case_6m": round(100 * worst, 1),
        "median_days_on_therapy": _median(ts, s),
    }


def _median(ts, s):
    below = np.where(s <= 0.5)[0]
    return int(ts[below[0]]) if len(below) else None


def attrition(cohort: pd.DataFrame) -> pd.Series:
    return cohort["reason"].value_counts()
