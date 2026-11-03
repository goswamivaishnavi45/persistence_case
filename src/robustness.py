"""How much should we trust the sensitivity results? Sampling and generator checks.

Writes to outputs/:
  robustness.csv   one row per seed/generator variant and scenario
  robustness.md    95% confidence intervals, look-forward decomposition, seed spread,
                   and a stress test where coverage loss is unrelated to patient risk
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cohort import DATA_END, Params, build_cohort, summarise  # noqa: E402
from generate_data import GenConfig, generate  # noqa: E402
from sensitivity import truth_benchmark  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "outputs"
SEEDS = [42, 1, 2, 3, 4, 5, 6, 7, 8, 9]
SCENARIOS = {"original": Params(), "gap_30": Params(max_gap=30), "gap_90": Params(max_gap=90),
             "no_lookforward": Params(lookforward_days=0)}


def wilson(p: float, n: int, z: float = 1.96):
    """95% Wilson interval for a proportion (p in 0-1), returned in percent."""
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(100 * (centre - half), 1), round(100 * (centre + half), 1)


def km_ci(time, event, day: float, z: float = 1.96):
    """Kaplan-Meier survival at `day` with a 95% Greenwood interval, in percent."""
    time, event = np.asarray(time, float), np.asarray(event, int)
    s, var = 1.0, 0.0
    for t in np.unique(time[time <= day]):
        at_risk = int((time >= t).sum())
        d = int(event[time == t].sum())
        if d:
            s *= 1 - d / at_risk
            if at_risk > d:
                var += d / (at_risk * (at_risk - d))
    half = z * s * math.sqrt(var)
    return round(100 * s, 1), round(100 * (s - half), 1), round(100 * (s + half), 1)


def scenario_rows(fills, enrol, truth, label, seed):
    rows = []
    for name, p in SCENARIOS.items():
        c = build_cohort(fills, enrol, p)
        s = summarise(c, p)
        rows.append({"variant": label, "seed": seed, "scenario": name, "cohort_n": s["cohort_n"],
                     "pct_persistent_6m": s["pct_persistent_6m"], "km_6m": s["km_6m"],
                     "worst_case_6m": s["worst_case_6m"], "truth_6m": truth_benchmark(truth)})
    return rows


def decomposition(fills, enrol):
    """Dropping R4 also lengthens the R2 intake window, so split the two effects."""
    p = Params(lookforward_days=0)
    c = build_cohort(fills, enrol, p)
    inc = c[c["included"]]
    same = inc[inc["index_date"] <= DATA_END - pd.Timedelta(days=365)]
    later = inc[inc["index_date"] > DATA_END - pd.Timedelta(days=365)]
    known = same[(same["event"] == 1) | (same["time"] >= 182)]
    persistent = int(((known["event"] == 0) | (known["time"] >= 182)).sum())
    return {"same_window_n": len(same), "later_index_n": len(later),
            "same_window_km": km_ci(same["time"], same["event"], 181.5),
            "same_window_worst": round(100 * persistent / len(same), 1)}


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for seed in SEEDS:
        fills, enrol, truth = generate(GenConfig(seed=seed))
        rows += scenario_rows(fills, enrol, truth, "base", seed)
        if seed == 42:
            base = (fills, enrol)
        print("seed", seed, "done")

    # Stress test: same average coverage loss (0.3*0.6 + 0.7*0.1 = 0.25), unrelated to risk.
    fills, enrol, truth = generate(GenConfig(seed=42, p_coverage_loss_stable=0.25,
                                             p_coverage_loss_high=0.25))
    rows += scenario_rows(fills, enrol, truth, "churn_unrelated_to_risk", 42)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "robustness.csv", index=False)

    fills, enrol = base
    c = build_cohort(fills, enrol, Params())
    inc = c[c["included"]]
    n = len(inc)
    pct = float(df[(df.seed == 42) & (df.variant == "base") & (df.scenario == "original")].pct_persistent_6m.iloc[0])
    wl = wilson(((inc["time"] >= 182) | (inc["event"] == 0)).mean(), n)
    nolf = build_cohort(fills, enrol, SCENARIOS["no_lookforward"])
    nolf = nolf[nolf["included"]]
    km3 = km_ci(inc["time"], inc["event"], 90.5)
    km6_nolf = km_ci(nolf["time"], nolf["event"], 181.5)
    d = decomposition(fills, enrol)

    base_df = df[df.variant == "base"]
    spread = base_df.groupby("scenario")[["pct_persistent_6m", "km_6m"]].agg(["mean", "min", "max"]).round(1)
    gaps = (base_df[base_df.scenario == "original"].set_index("seed").pct_persistent_6m
            - base_df[base_df.scenario == "original"].set_index("seed").truth_6m)
    stress = df[df.variant == "churn_unrelated_to_risk"].set_index("scenario")

    lines = ["# Robustness checks (synthetic data)", "",
             "## Sampling uncertainty, seed 42",
             f"- Original rules: {pct}% of {n} patients, 95% Wilson interval {wl[0]}-{wl[1]}%.",
             f"- Original rules at 3 months (Kaplan-Meier): {km3[0]}%, 95% Greenwood interval {km3[1]}-{km3[2]}%.",
             f"- No look-forward at 6 months (Kaplan-Meier, n={len(nolf)}): {km6_nolf[0]}%, "
             f"95% Greenwood interval {km6_nolf[1]}-{km6_nolf[2]}%.", "",
             "## What dropping the look-forward actually changes, seed 42",
             f"The cohort grows from {n} to {len(nolf)} patients, but only part of that is R4. "
             f"{d['same_window_n']} patients have index dates inside the original intake window "
             f"({n} plus the patients R4 excluded). The other {d['later_index_n']} enter because R2 "
             f"no longer needs 12 months of follow-up, so later index dates qualify.",
             f"Keeping only the same intake window gives {d['same_window_km'][0]}% "
             f"(95% interval {d['same_window_km'][1]}-{d['same_window_km'][2]}%), or "
             f"{d['same_window_worst']}% if every patient lost before 6 months counts as stopped.", "",
             f"## Spread across {len(SEEDS)} generator seeds (mean, min-max)", "",
             "| Scenario | 6-month persistence |", "|---|---|"]
    for name in SCENARIOS:
        col = "km_6m" if name == "no_lookforward" else "pct_persistent_6m"
        r = spread.loc[name, col]
        lines.append(f"| {name} | {r['mean']}% ({r['min']}-{r['max']}%) |")
    lines += ["",
              f"Original rules minus synthetic truth: mean {gaps.mean():.1f} points "
              f"(range {gaps.min():.1f} to {gaps.max():.1f}).", "",
              "## Stress test: coverage loss unrelated to patient risk (seed 42)",
              "Same average coverage loss (25%), but high-risk patients are no more likely to lose it.",
              f"- Original rules: {stress.loc['original', 'pct_persistent_6m']}% "
              f"(n={stress.loc['original', 'cohort_n']}).",
              f"- No look-forward, Kaplan-Meier: {stress.loc['no_lookforward', 'km_6m']}% "
              f"(n={stress.loc['no_lookforward', 'cohort_n']}).",
              f"- Synthetic truth: {stress.loc['original', 'truth_6m']}%."]
    (OUT / "robustness.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
