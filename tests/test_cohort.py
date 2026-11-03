"""Tests for each cohort rule (R1-R8) and the data generator."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cohort import (BRAND, INTAKE_START, IndexRule, Params, build_cohort,  # noqa: E402
                    continuously_enrolled, index_date, kaplan_meier, merge_segments,
                    summarise, survival_at, time_to_discontinuation)
from generate_data import GenConfig, generate  # noqa: E402

D = pd.Timestamp
IDX = INTAKE_START + pd.Timedelta(days=100)  # a safe index date for toy patients


def toy(fill_days, supply=30, enrol=(-500, 900), drug=BRAND, pid=1):
    """Build a one-patient dataset; days are relative to IDX."""
    f = pd.DataFrame({"patient_id": pid,
                      "fill_date": [IDX + pd.Timedelta(days=d) for d in fill_days],
                      "drug": drug, "days_supply": supply})
    e = pd.DataFrame({"patient_id": [pid], "enrol_start": [IDX + pd.Timedelta(days=enrol[0])],
                      "enrol_end": [IDX + pd.Timedelta(days=enrol[1])]})
    return f, e


# ---------------- R5 / R6: gap and carry-over ------------------------------ #
def test_gap_exactly_at_limit_is_allowed():
    # supply runs out at day 30, next fill on day 90 -> gap 60 -> still on therapy
    t, ev = time_to_discontinuation([(0, 30), (90, 30)], follow_end=400, max_gap=60)
    assert (t, ev) == (120, 1)   # stops later, after the second fill runs out


def test_gap_one_day_over_limit_discontinues():
    t, ev = time_to_discontinuation([(0, 30), (91, 30)], follow_end=400, max_gap=60)
    assert (t, ev) == (30, 1)    # event at the day supply ran out


def test_early_refill_carries_supply_forward():
    # refilled on day 20 -> covered until 60, then 60 more days of gap allowed
    t, ev = time_to_discontinuation([(0, 30), (20, 30), (120, 30)], 400, max_gap=60)
    assert t == 150 and ev == 1


def test_censored_when_follow_up_ends_inside_gap_window():
    t, ev = time_to_discontinuation([(0, 30)], follow_end=70, max_gap=60)
    assert (t, ev) == (70, 0)


def test_fills_after_follow_up_ignored():
    t, ev = time_to_discontinuation([(0, 30), (200, 30)], follow_end=100, max_gap=60)
    assert ev == 1 and t == 30


# ---------------- R3 / R4: enrolment -------------------------------------- #
def test_back_to_back_segments_merge():
    segs = [(D("2022-01-01"), D("2022-06-30")), (D("2022-07-01"), D("2022-12-31"))]
    assert merge_segments(segs) == [(D("2022-01-01"), D("2022-12-31"))]
    assert continuously_enrolled(segs, D("2022-02-01"), D("2022-11-01"))


def test_break_in_coverage_fails_continuous_enrolment():
    segs = [(D("2022-01-01"), D("2022-06-30")), (D("2022-08-01"), D("2022-12-31"))]
    assert not continuously_enrolled(segs, D("2022-02-01"), D("2022-11-01"))


def test_lookback_excludes_recent_joiner():
    f, e = toy([0, 30, 60], enrol=(-100, 900))
    c = build_cohort(f, e, Params())
    assert c.loc[0, "reason"].startswith("R3")
    assert build_cohort(f, e, Params(lookback_days=0)).loc[0, "included"]


def test_lookforward_excludes_coverage_loss():
    f, e = toy([0, 30, 60], enrol=(-500, 200))
    assert build_cohort(f, e, Params()).loc[0, "reason"].startswith("R4")
    c = build_cohort(f, e, Params(lookforward_days=0))
    assert c.loc[0, "included"]


# ---------------- R1 / R2: index date ------------------------------------- #
def test_index_ignores_other_drugs():
    f, e = toy([0, 30])
    other = toy([-60], drug="SERTRALINE")[0]
    c = build_cohort(pd.concat([other, f]), e, Params())
    assert c.loc[0, "index_date"] == IDX


def test_first_in_window_ignores_earlier_fills():
    early = INTAKE_START - pd.Timedelta(days=10)
    dates = [early, INTAKE_START + pd.Timedelta(days=5)]
    assert index_date(dates, IndexRule.FIRST_EVER) == early
    assert index_date(dates, IndexRule.FIRST_IN_WINDOW) == dates[1]


def test_index_before_intake_window_excluded():
    f, e = toy([-200, -170])          # first fill is before INTAKE_START
    assert build_cohort(f, e, Params()).loc[0, "reason"].startswith("R2")


# ---------------- R7 / R8: results ---------------------------------------- #
def test_persistence_flag_at_six_months():
    monthly = list(range(0, 400, 30))
    f1, e1 = toy(monthly, pid=1)
    f2, e2 = toy([0, 30, 60], pid=2)
    c = build_cohort(pd.concat([f1, f2]), pd.concat([e1, e2]), Params())
    s = summarise(c, Params())
    assert s["cohort_n"] == 2 and s["pct_persistent_6m"] == 50.0


def test_kaplan_meier_matches_hand_calculation():
    # times 1,2,3,4 ; events 1,0,1,1 -> S = 3/4, then 3/4*1/2, then 0
    ts, s = kaplan_meier([1, 2, 3, 4], [1, 0, 1, 1])
    assert np.allclose(s, [1, 0.75, 0.375, 0.0])
    assert survival_at(ts, s, 2.5) == 0.75


# ---------------- generator ----------------------------------------------- #
@pytest.fixture(scope="module")
def small_data():
    return generate(GenConfig(n_patients=1500, seed=7))


def test_generator_is_reproducible():
    a = generate(GenConfig(n_patients=200, seed=1))[0]
    b = generate(GenConfig(n_patients=200, seed=1))[0]
    pd.testing.assert_frame_equal(a, b)


def test_generator_fills_only_inside_coverage(small_data):
    f, e, _ = small_data
    m = f.merge(e, on="patient_id")
    inside = (m.fill_date >= m.enrol_start) & (m.fill_date <= m.enrol_end)
    assert inside.groupby([m.patient_id, m.fill_date]).any().all()


def test_original_rules_close_to_reported_68(small_data):
    f, e, _ = small_data
    pct = summarise(build_cohort(f, e, Params()), Params())["pct_persistent_6m"]
    assert 62 <= pct <= 74


def test_stricter_gap_lowers_persistence(small_data):
    f, e, _ = small_data
    pcts = [summarise(build_cohort(f, e, Params(max_gap=g)), Params(max_gap=g))
            ["pct_persistent_6m"] for g in (30, 60, 90)]
    assert pcts[0] < pcts[1] < pcts[2]
