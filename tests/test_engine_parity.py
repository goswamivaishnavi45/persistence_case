"""The HTML explorer's JavaScript engine must give the same numbers as Python."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cohort import IndexRule, Params, build_cohort, summarise  # noqa: E402
from export_data import compact  # noqa: E402
from generate_data import GenConfig, generate  # noqa: E402

CASES = [Params(), Params(max_gap=30), Params(lookforward_days=0),
         Params(lookback_days=0, index_rule=IndexRule.FIRST_IN_WINDOW, max_gap=90)]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_engine_matches_python(tmp_path):
    f, e, _ = generate(GenConfig(n_patients=1500, seed=3))
    (tmp_path / "data.json").write_text(json.dumps(compact(f, e)))
    js_params = [{"maxGap": p.max_gap, "lookback": p.lookback_days, "lookforward": p.lookforward_days,
                  "persistenceDay": p.persistence_day, "indexRule": p.index_rule.value} for p in CASES]
    script = f"""
      const E = require({json.dumps(str(ROOT / 'src' / 'engine.js'))});
      const D = require({json.dumps(str(tmp_path / 'data.json'))});
      const out = {json.dumps(js_params)}.map(p => {{ const s = E.summarise(E.buildCohort(D.patients, p, D.C), p);
        return [s.cohort_n, s.pct_persistent_6m, s.km_6m]; }});
      console.log(JSON.stringify(out));"""
    js = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    for p, (n, pct, km) in zip(CASES, js):
        py = summarise(build_cohort(f, e, p), p)
        assert (py["cohort_n"], py["pct_persistent_6m"], py["km_6m"]) == (n, pct, km), p
