"""Export claims + enrolment as compact JSON (integer days) for the HTML explorer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cohort import BRAND, DATA_END, DATA_START, INTAKE_START  # noqa: E402


def compact(fills: pd.DataFrame, enrol: pd.DataFrame) -> dict:
    b = fills[fills["drug"] == BRAND].copy()
    b["d"] = (b["fill_date"] - DATA_START).dt.days
    e = enrol.copy()
    e["s"] = (e["enrol_start"] - DATA_START).dt.days
    e["e"] = (e["enrol_end"] - DATA_START).dt.days
    segs = {pid: g[["s", "e"]].values.tolist() for pid, g in e.groupby("patient_id")}
    pts = [[int(pid), sorted(g[["d", "days_supply"]].astype(int).values.tolist()), segs.get(pid, [])]
           for pid, g in b.groupby("patient_id")]
    return {"C": {"INTAKE_START": (INTAKE_START - DATA_START).days,
                  "DATA_END": (DATA_END - DATA_START).days},
            "patients": pts}
