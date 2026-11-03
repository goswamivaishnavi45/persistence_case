"""Evaluate the methodology assistant on assistant/eval_questions.json.

Scoring per question:
  answerable  -> PASS if not declined AND at least one expected ID is cited
                 AND every citation is a real section ID (grounding)
  decline     -> PASS if the assistant declined
Writes outputs/eval_report.md.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from assistant import Assistant  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(mode="auto"):
    a = Assistant(mode)
    qs = json.loads((ROOT / "assistant" / "eval_questions.json").read_text())
    rows, passed = [], 0
    for item in qs:
        if a.mode != "offline":
            time.sleep(13)   # stay inside free-tier per-minute limits
        ans = a.ask(item["q"])
        grounded = all(c in a.ids for c in ans.citations)
        if item.get("decline"):
            ok = ans.declined
        else:
            ok = (not ans.declined) and grounded and bool(set(ans.citations) & set(item["expect"]))
        passed += ok
        rows.append((item["id"], item["q"], "decline" if item.get("decline") else ",".join(item["expect"]),
                     "declined" if ans.declined else ",".join(ans.citations), "PASS" if ok else "FAIL"))
    n_ans = sum(1 for q in qs if not q.get("decline"))
    ok_ans = sum(1 for r, q in zip(rows, qs) if not q.get("decline") and r[4] == "PASS")
    ok_dec = sum(1 for r, q in zip(rows, qs) if q.get("decline") and r[4] == "PASS")
    lines = [f"# Assistant evaluation (mode: {a.mode})", "",
             f"Overall: {passed}/{len(qs)} | answerable with correct citation: {ok_ans}/{n_ans} | "
             f"correctly declined: {ok_dec}/{len(qs) - n_ans}", "",
             "| ID | Question | Expected | Got | Result |", "|---|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in rows]
    (ROOT / "outputs" / "eval_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "auto")
