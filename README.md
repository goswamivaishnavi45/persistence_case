# Rebuilding the 68% persistence figure

Case 2: Stakeholder Transition and Trust. A transparent, testable rebuild of the
6-month persistence analysis, so the interim VP can inspect it, test its
assumptions and explain it herself.

## Run it on your computer

Needs Python 3.10+ (and Node.js only for the optional JS parity test).

```bash
cd persistence_case
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then:

```bash
pip install numpy pandas scikit-learn pytest
python src/generate_data.py --out data      # synthetic claims + enrolment (seed 42)
python src/sensitivity.py                   # original result, sensitivity grid, results.md
python src/build_explorer.py                # outputs/explorer.html (open in any browser)
python -m pytest -q                         # 19 tests: every cohort rule + JS/Python parity
python assistant/run_eval.py                # assistant evaluation -> outputs/eval_report.md
python assistant/assistant.py "Why does the look-forward rule matter?"
```

The assistant picks its LLM from the key you set:

| Key set | LLM used | Model setting |
|---|---|---|
| `GEMINI_API_KEY` (free at aistudio.google.com) | Google Gemini | `GEMINI_MODEL`, default `gemini-3.5-flash` |
| `ANTHROPIC_API_KEY` | Claude | `ASSISTANT_MODEL`, default `claude-sonnet-5-5` |
| none | offline retrieval-only mode | — |

```bash
export GEMINI_API_KEY=your_key_here          # Windows PowerShell: $env:GEMINI_API_KEY="your_key_here"
python assistant/run_eval.py gemini
```
Never commit your key to the repo.

## What's in the box

| Path | What it is |
|---|---|
| `src/generate_data.py` | Synthetic pharmacy claims + enrolment generator |
| `src/cohort.py` | Exhibit 1 rules as small functions, tagged R1-R8 |
| `src/sensitivity.py` | Original result, 27-scenario grid, KM curves, plain-language results |
| `src/engine.js` | Same logic in JavaScript for the explorer (tested against Python) |
| `outputs/explorer.html` | Interactive explorer: sliders for gap, look-back, look-forward, first-fill rule |
| `assistant/` | Methodology doc, grounded assistant, eval question set, eval runner |
| `outputs/` | `sensitivity.csv`, `results.md`, `km_curves.json`, `eval_report.md` |
| `tests/` | Rule-level unit tests, generator tests, JS/Python parity test |

## Assumptions (confirm with the client)

1. **Gap** is measured from the day supply runs out to the next fill (confirmed). A gap of exactly 60 days is allowed; 61 is a discontinuation.
2. **Discontinuation date** is the day supply ran out, not the day the gap limit was crossed.
3. **Early refills** carry leftover days forward.
4. **Persistent at 6 months** means not discontinued before day 182.
5. **Switching / adding** another antidepressant does not count as stopping; other drugs are ignored for the index date.
6. **Continuous enrolment** allows back-to-back segments; any break fails.

## Findings

| Scenario | Cohort | 6-mo persistence |
|---|---|---|
| Original rules (R1-R7) | 3,010 | **68.2%** |
| Gap 30 days | 3,010 | 41.5% |
| Gap 90 days | 3,010 | 81.2% |
| No look-forward, Kaplan-Meier with censoring | 4,446 | 64.5% |
| No look-forward, lost-coverage counted as stopped (worst case) | 4,446 | 57.8% |
| No look-back, first fill in window | 3,840 | 69.8% |
| Synthetic truth: all real new starters, every fill seen | — | 61.3% |

What explains the gap between 68% and what the field sees:

1. **The 60-day gap is the biggest lever.** 30 days gives 41.5%, 90 days gives 81.2%. The number is mostly a statement about how forgiving the definition is.
2. **The 12-month look-forward removes 833 patients who lost coverage.** In this data they stop more often, so removing them inflates the figure. Keeping them via Kaplan-Meier gives 64.5% (57.8% worst case).
3. **The single 6-month point hides early drop-off.** 17% have stopped by month 3, about half of all stopping before month 6.
4. **Claims can't see** prescriptions never filled, cash payments or samples. The field sees these patients; no rule change recovers them.
5. **The first-fill definition** matters little here, because the 12-month look-back already blocks existing users.

**Message for the VP:** 68% is a correct answer to a narrow question: *of continuously insured new starters, how many had no break longer than 60 days by month 6?* It is not the share of all patients who start therapy and keep going. Present it with the curve and the range (roughly 58-65% under less selective rules), not as one number.

## Methodology assistant

* Sources: `assistant/methodology.md` (rules R1-R8, assumptions A1-A2) and `outputs/results.md` (results O1-O8).
* Retrieval: TF-IDF over sections; an explicitly named ID (e.g. "R4") is always retrieved.
* The LLM is instructed to answer only from retrieved sections, cite IDs, and decline otherwise. Citations not matching a real ID are dropped, and an uncited answer becomes a refusal.
* Out-of-scope guard: clinical advice, pricing, competitors, individual patients, forecasts and blame are declined before any LLM call.

**Evaluation** (`assistant/eval_questions.json`, 14 answerable + 7 should-decline): offline mode scores **20/21** (13/14 correct citation, 7/7 correctly declined). The miss (Q12, "how many had stopped by 3 months") retrieves the wrong section; it is left in as a known retrieval weakness. The full question set has not been scored in LLM mode, because the Gemini free tier allows only 20 requests per model per day. Gemini was spot-checked by hand on a few questions: cited answers and declines behaved as intended, and it answered the Q12 question correctly from O6. Run `python assistant/run_eval.py gemini` to score it (set `GEMINI_MODEL=gemini-3.5-flash-lite` if the default model's daily quota is used up).

Limitations: the decline patterns and questions were written together, so a held-out question set is needed for a fair score; citation correctness is checked, but answer faithfulness in LLM mode should also be spot-checked by a human.

## Limits of this rebuild

The data is synthetic and the generator was built to contain the mechanisms above (coverage churn linked to early stopping, late refills, existing users joining the plan). The sizes of the effects come from those choices. On the client's real claims, the same code and explorer would show how large each effect really is.
