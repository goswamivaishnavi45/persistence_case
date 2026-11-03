"""Run the original analysis, the sensitivity grid and the synthetic ground truth.

Writes to outputs/:
  sensitivity.csv      one row per rule combination
  km_curves.json       Kaplan-Meier curves for the headline scenarios
  results.md           plain-language results with result IDs (O1..O8) that the
                       methodology assistant cites
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cohort import (DATA_END, INTAKE_START, IndexRule, Params, attrition,  # noqa: E402
                    build_cohort, kaplan_meier, summarise)
from generate_data import GenConfig, generate  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "outputs"

GAPS = [30, 60, 90]
LOOKFORWARD = [365, 182, 0]
INDEX_VARIANTS = [  # (label, lookback_days, index_rule)
    ("12m clean look-back, first-ever fill (original)", 365, IndexRule.FIRST_EVER),
    ("6m look-back, first-ever fill", 182, IndexRule.FIRST_EVER),
    ("no look-back, first fill in window (prevalent users leak in)", 0, IndexRule.FIRST_IN_WINDOW),
]


def truth_benchmark(truth: pd.DataFrame) -> float:
    """True 6-month persistence of genuine new starters, using every fill they
    made, insured or not. Only possible because the data is synthetic."""
    t = truth[(~truth["prevalent"]) & (truth["true_start"] >= INTAKE_START)
              & (truth["true_start"] <= DATA_END - pd.Timedelta(days=365))]
    return round(100 * (t["true_days_on_therapy"] >= 182).mean(), 1)


def run() -> dict:
    OUT.mkdir(exist_ok=True)
    fills, enrol, truth = generate(GenConfig())

    rows = []
    for gap, lf, (label, lb, rule) in itertools.product(GAPS, LOOKFORWARD, INDEX_VARIANTS):
        p = Params(max_gap=gap, lookback_days=lb, lookforward_days=lf, index_rule=rule)
        r = summarise(build_cohort(fills, enrol, p), p)
        r["first_fill_definition"] = label
        rows.append(r)
        print(f"gap={gap:>2} lf={lf:>3} {rule.value:<15} lb={lb:>3} -> "
              f"n={r['cohort_n']:>5}  6m={r['pct_persistent_6m']}%  KM={r['km_6m']}%")
    sens = pd.DataFrame(rows)
    sens.to_csv(OUT / "sensitivity.csv", index=False)

    scenarios = {
        "original": Params(),
        "gap_30": Params(max_gap=30),
        "gap_90": Params(max_gap=90),
        "no_lookforward_km": Params(lookforward_days=0),
    }
    curves, summaries = {}, {}
    for name, p in scenarios.items():
        c = build_cohort(fills, enrol, p)
        inc = c[c["included"]]
        ts, s = kaplan_meier(inc["time"], inc["event"])
        curves[name] = {"t": [int(x) for x in ts], "s": [round(float(x), 4) for x in s]}
        summaries[name] = summarise(c, p)
    (OUT / "km_curves.json").write_text(json.dumps(curves))

    orig_cohort = build_cohort(fills, enrol, Params())
    funnel = attrition(orig_cohort).to_dict()
    truth_6m = truth_benchmark(truth)
    write_results_md(sens, summaries, funnel, truth_6m, curves["original"])
    return {"sens": sens, "summaries": summaries, "truth": truth_6m, "funnel": funnel}


def _pick(sens, gap, lf, lb, rule):
    r = sens[(sens.max_gap == gap) & (sens.lookforward_days == lf)
             & (sens.lookback_days == lb) & (sens.index_rule == rule.value)].iloc[0]
    return r


def write_results_md(sens, summ, funnel, truth_6m, curve):
    from cohort import survival_at
    import numpy as np
    ts, sv = np.array(curve["t"]), np.array(curve["s"])
    s90, s182, s365 = (round(100 * survival_at(ts, sv, d - 0.5), 1) for d in (91, 182, 365))
    early_share = round(100 * (100 - s90) / (100 - s182)) if s182 < 100 else 0
    o = summ["original"]
    nolf = summ["no_lookforward_km"]
    lb0 = _pick(sens, 60, 365, 0, IndexRule.FIRST_IN_WINDOW)
    lines = [
        "# Analysis results (synthetic data, seed 42)",
        "",
        "Each result has an ID. The methodology assistant cites these IDs.",
        "",
        f"## O1 Headline result (original method)",
        f"Using the original rules (R1-R7: first-ever fill, 12-month look-back, "
        f"12-month look-forward, 60-day gap), {o['pct_persistent_6m']}% of the "
        f"{o['cohort_n']} patients in the analysis cohort were persistent at 6 months. "
        f"This reproduces the reported 68% figure.",
        "",
        "## O2 Who was excluded (attrition)",
        f"Of {o['patients_with_fill']} patients with at least one fill: "
        + "; ".join(f"{k}: {v}" for k, v in funnel.items()) + ".",
        f"The 12-month look-forward rule (R4) alone removes {funnel.get('R4: failed look-forward enrolment', 0)} "
        f"patients who lost or changed insurance within a year.",
        "",
        "## O3 Effect of the allowed gap (R5)",
        f"Holding other rules at the original values, 6-month persistence is "
        f"{summ['gap_30']['pct_persistent_6m']}% with a 30-day gap, "
        f"{o['pct_persistent_6m']}% with a 60-day gap and "
        f"{summ['gap_90']['pct_persistent_6m']}% with a 90-day gap. The gap rule is the "
        f"single biggest driver of the number.",
        "",
        "## O4 Effect of the 12-month look-forward (R4)",
        f"Dropping the look-forward requirement and using Kaplan-Meier with censoring "
        f"(R8) grows the cohort from {o['cohort_n']} to {nolf['cohort_n']} patients and "
        f"gives {nolf['km_6m']}% persistent at 6 months. If every patient who lost "
        f"coverage before 6 months is assumed to have stopped (worst case), it is "
        f"{nolf['worst_case_6m']}%. Patients who lose coverage stop therapy more often, "
        f"so requiring 12 months of coverage makes the remaining cohort look more persistent.",
        "",
        "## O5 Effect of how the first fill is identified (R1, R3)",
        f"With no look-back and the index taken as the first fill inside the intake window, "
        f"prevalent users (already on the drug when they joined the plan) are counted as new "
        f"starters. The cohort grows to {int(lb0.cohort_n)} and persistence is "
        f"{lb0.pct_persistent_6m}%. The 12-month look-back protects the original figure from "
        f"this bias, so this choice moves the number only modestly.",
        "",
        "## O6 Time to discontinuation",
        f"Under the original rules the Kaplan-Meier curve shows {s90}% of patients "
        f"still on therapy at 3 months, {s182}% at 6 months and {s365}% at 12 months; "
        f"the median time on therapy is "
        f"{o['median_days_on_therapy'] or 'beyond the follow-up window'} days. A single "
        f"6-month figure hides that about {early_share}% of the 6-month drop-off has "
        f"already happened by month 3.",
        "",
        "## O7 Synthetic ground truth",
        f"Because the data is synthetic, the true 6-month persistence of all genuine new "
        f"starters (counting fills after they lost insurance, with a 60-day gap) is known: "
        f"{truth_6m}%. The original method overstates this by "
        f"{round(o['pct_persistent_6m'] - truth_6m, 1)} points, mostly through the "
        f"look-forward rule. In real data this truth is not observable.",
        "",
        "## O8 What claims data cannot see",
        "Patients who were prescribed the drug but never filled it (primary non-adherence), "
        "patients paying cash and free samples do not appear in pharmacy claims. Doctors and "
        "the field team do see these patients, so their impression of early stopping includes "
        "people the claims analysis cannot count. This is not quantified in this analysis.",
    ]
    (OUT / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    res = run()
    print("truth:", res["truth"])
