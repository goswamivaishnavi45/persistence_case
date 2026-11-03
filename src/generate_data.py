"""Synthetic pharmacy claims + enrolment generator.

Produces two tables (CSV):
  fills.csv      patient_id, fill_date, drug, days_supply
  enrolment.csv  patient_id, enrol_start, enrol_end   (one row per coverage segment)

The generator deliberately builds in the real-world mechanisms that can make a
claims-based persistence figure differ from what the field sees:

  * Two latent patient types: "stable" and "high-risk". High-risk patients stop
    therapy earlier AND are more likely to lose / change insurance. Losing
    coverage makes later fills invisible, and the 12-month look-forward rule
    then drops them from the cohort entirely (selection bias).
  * Late refills: a share of refills arrive 30-80 days late, so the allowed-gap
    rule (30 / 60 / 90 days) moves the number.
  * Prevalent users who join the plan already on the drug. Their first fill in
    the data is not their true first fill; the 12-month look-back removes them.
  * Some fills of other antidepressants (noise the index rule must ignore).
  * Some coverage segments with a short break (tests continuous-enrolment logic).

Everything is driven by one seed, so the data is fully reproducible.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA_START = pd.Timestamp("2021-01-01")
DATA_END = pd.Timestamp("2025-12-31")
BRAND = "BRAND_TRD"
OTHER_DRUGS = ["SERTRALINE", "BUPROPION"]


@dataclass
class GenConfig:
    n_patients: int = 6000
    seed: int = 42
    p_high_risk: float = 0.30
    p_prevalent: float = 0.12          # join plan already on the drug
    mean_duration_stable: float = 1100  # intended days on therapy
    mean_duration_high: float = 110
    p_coverage_loss_stable: float = 0.10
    p_coverage_loss_high: float = 0.60
    p_enrol_break: float = 0.05        # short break in coverage


def _refill_delay(rng: np.random.Generator) -> int:
    """Days late a refill is relative to running out of supply."""
    r = rng.random()
    if r < 0.66:
        return int(rng.integers(-5, 8))      # on time / slightly early
    if r < 0.86:
        return int(rng.integers(8, 31))      # a bit late
    if r < 0.96:
        return int(rng.integers(31, 61))     # late: passes 60, fails 30
    return int(rng.integers(61, 91))         # very late: passes only 90


def generate(cfg: GenConfig = GenConfig()):
    """Return (fills, enrolment, truth). `truth` is only knowable because the data
    is synthetic: it holds every patient's real behaviour, including fills that
    never reach the claims data after coverage ends."""
    rng = np.random.default_rng(cfg.seed)
    fills, enrol, truth = [], [], []
    total_days = (DATA_END - DATA_START).days

    for pid in range(1, cfg.n_patients + 1):
        high = rng.random() < cfg.p_high_risk
        prevalent = rng.random() < cfg.p_prevalent

        # --- therapy start (true first fill) -------------------------------
        start_day = int(rng.integers(200, total_days - 120))

        # --- enrolment ------------------------------------------------------
        if prevalent:
            # joined the plan recently, already on therapy elsewhere
            enrol_start = start_day - int(rng.integers(10, 120))
            mean_dur = cfg.mean_duration_stable * 1.3
        else:
            enrol_start = int(rng.integers(-400, max(-399, start_day - 380)))
            mean_dur = cfg.mean_duration_high if high else cfg.mean_duration_stable
        enrol_start = max(enrol_start, -400)

        p_loss = cfg.p_coverage_loss_high if high else cfg.p_coverage_loss_stable
        duration = rng.exponential(mean_dur)
        if rng.random() < p_loss:
            # coverage ends (job change, plan switch). High-risk patients churn
            # sooner -- this is what the 12-month look-forward silently removes.
            if high:
                loss = start_day + int(rng.integers(20, 365))
            else:
                loss = start_day + int(rng.integers(30, 700))
            enrol_end = min(loss, total_days)
        else:
            enrol_end = total_days

        if rng.random() < cfg.p_enrol_break and enrol_end - enrol_start > 400:
            b = int(rng.integers(enrol_start + 100, enrol_end - 100))
            segs = [(enrol_start, b), (b + int(rng.integers(20, 60)), enrol_end)]
        else:
            segs = [(enrol_start, enrol_end)]
        enrol.extend((pid, s, e) for s, e in segs)

        def covered(d):  # a claim only exists while the patient is insured
            return 0 <= d <= total_days and any(s <= d <= e for s, e in segs)

        # --- brand fills ----------------------------------------------------
        day, used, all_fills = start_day, 0.0, []
        while used < duration and day <= total_days:
            supply = 90 if rng.random() < 0.08 else 30
            all_fills.append((day, supply))
            if covered(day):
                fills.append((pid, day, BRAND, supply))
            used += supply
            day = day + supply + _refill_delay(rng)
        truth.append((pid, high, prevalent, start_day, _true_days(all_fills, 60)))

        # --- unrelated antidepressant fills (noise) -------------------------
        if rng.random() < 0.25:
            d = start_day - int(rng.integers(30, 600))
            for _ in range(int(rng.integers(1, 5))):
                if covered(d):
                    fills.append((pid, d, rng.choice(OTHER_DRUGS), 30))
                d += 30

    f = pd.DataFrame(fills, columns=["patient_id", "day", "drug", "days_supply"])
    f["fill_date"] = DATA_START + pd.to_timedelta(f["day"], unit="D")
    f = f[["patient_id", "fill_date", "drug", "days_supply"]].sort_values(
        ["patient_id", "fill_date"]).reset_index(drop=True)

    e = pd.DataFrame(enrol, columns=["patient_id", "s", "e"])
    e["enrol_start"] = DATA_START + pd.to_timedelta(e["s"], unit="D")
    e["enrol_end"] = DATA_START + pd.to_timedelta(e["e"], unit="D")
    e = e[["patient_id", "enrol_start", "enrol_end"]].reset_index(drop=True)

    t = pd.DataFrame(truth, columns=["patient_id", "high_risk", "prevalent",
                                     "start_day", "true_days_on_therapy"])
    t["true_start"] = DATA_START + pd.to_timedelta(t["start_day"], unit="D")
    t = t.drop(columns="start_day")
    return f, e, t


def _true_days(all_fills, max_gap):
    """Days on therapy using every fill the patient really made (60-day gap)."""
    covered = all_fills[0][0] + all_fills[0][1]
    for d, s in all_fills[1:]:
        if d - covered > max_gap:
            break
        covered = max(covered, d) + s
    return covered - all_fills[0][0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    f, e, t = generate(GenConfig(n_patients=a.n, seed=a.seed))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f.to_csv(out / "fills.csv", index=False)
    e.to_csv(out / "enrolment.csv", index=False)
    t.to_csv(out / "truth.csv", index=False)  # synthetic ground truth, not "claims"
    print(f"wrote {len(f)} fills, {len(e)} enrolment rows for {a.n} patients -> {out}")


if __name__ == "__main__":
    main()
