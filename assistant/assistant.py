"""Methodology assistant: answers questions about the cohort rules and results,
grounded ONLY in assistant/methodology.md and outputs/results.md, citing the
rule (R*), assumption (A*) or result (O*) IDs it used.

Modes (chosen automatically from which API key is set, or with --mode):
  gemini   - Google Gemini (free tier). Needs GEMINI_API_KEY.
             Model via GEMINI_MODEL (default gemini-3.5-flash).
  claude   - Anthropic Claude. Needs ANTHROPIC_API_KEY.
             Model via ASSISTANT_MODEL (default claude-sonnet-5-5).
  offline  - no LLM: returns the best-matching sections verbatim. Used as a
             deterministic baseline and so the evaluation runs without a key.

Usage:
  python assistant/assistant.py "Why is the gap 60 days?"
  python assistant/assistant.py --mode offline "What does R4 do?"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "assistant" / "methodology.md", ROOT / "outputs" / "results.md"]
MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DECLINE = ("I can't answer that from the methodology or the analysis outputs. "
           "I can only explain the cohort rules (R1-R8), assumptions (A1-A2) and results (O1-O8).")

# Questions that are out of scope however well they match the text.
OUT_OF_SCOPE = [
    r"\b(dose|dosage|prescribe|side effect|safe for|should (i|a patient|patients) take)\b",
    r"\b(price|pricing|discount|budget|revenue|forecast|sales target|roi)\b",
    r"\b(competitor|other brands?|market share)\b",
    r"\b(patient (id|number)|patient \d+|name of (a|the) patient)\b",
    r"\b(next year|will .* be in 20\d\d|predict)\b",
    r"\b(fire|blame|whose fault|vp (was|is) (wrong|lying))\b",
]

SYSTEM = """You are the methodology assistant for a pharmacy-claims persistence analysis.
Answer ONLY from the numbered source sections provided. Rules:
- Every factual sentence must be supported by a section; cite section IDs like [R4] or [O3].
- If the sections do not contain the answer, or the question asks for clinical advice,
  commercial strategy, pricing, forecasts, individual patients, or opinions about people,
  set "declined": true and explain briefly what you can help with instead.
- Do not use outside knowledge, even if you believe it is true. Do not invent numbers.
- Plain language for a non-technical commercial leader. Max 120 words.
Return JSON only: {"answer": str, "citations": [ids], "declined": bool}"""


@dataclass
class Section:
    sid: str
    title: str
    text: str


@dataclass
class Answer:
    answer: str
    citations: list[str] = field(default_factory=list)
    declined: bool = False
    retrieved: list[str] = field(default_factory=list)


def load_sections() -> list[Section]:
    out = []
    for path in SOURCES:
        for block in re.split(r"^## ", path.read_text(), flags=re.M)[1:]:
            head, _, body = block.partition("\n")
            sid, _, title = head.partition(" ")
            out.append(Section(sid.strip(), title.strip(), body.strip()))
    return out


class Assistant:
    def __init__(self, mode: str = "auto", min_score: float = 0.10, k: int = 3):
        self.sections = load_sections()
        self.ids = {s.sid for s in self.sections}
        self.vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.mat = self.vec.fit_transform([f"{s.sid} {s.title} {s.title} {s.text}" for s in self.sections])
        self.min_score, self.k = min_score, k
        if mode == "auto":
            mode = ("gemini" if os.environ.get("GEMINI_API_KEY")
                    else "claude" if os.environ.get("ANTHROPIC_API_KEY") else "offline")
        self.mode = mode

    # ---- retrieval -------------------------------------------------------- #
    def retrieve(self, q: str) -> list[tuple[Section, float]]:
        explicit = [s for s in self.sections if re.search(rf"\b{s.sid}\b", q, re.I)]
        scores = cosine_similarity(self.vec.transform([q]), self.mat)[0]
        ranked = sorted(zip(self.sections, scores), key=lambda x: -x[1])
        hits = [(s, 1.0) for s in explicit] + [x for x in ranked if x[0] not in explicit]
        return hits[: self.k]

    @staticmethod
    def out_of_scope(q: str) -> bool:
        return any(re.search(p, q, re.I) for p in OUT_OF_SCOPE)

    # ---- answering -------------------------------------------------------- #
    def ask(self, q: str) -> Answer:
        hits = self.retrieve(q)
        retrieved = [s.sid for s, _ in hits]
        if self.out_of_scope(q) or not hits or hits[0][1] < self.min_score:
            return Answer(DECLINE, [], True, retrieved)
        if self.mode == "offline":
            top = [s for s, sc in hits if sc >= self.min_score][:2]
            text = " ".join(f"[{s.sid}] {s.text}" for s in top)
            return Answer(text, [s.sid for s in top], False, retrieved)
        return self._ask_llm(q, hits, retrieved)

    @staticmethod
    def _post(url, body, headers):
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json", **headers})
        # Retry rate limits, overload and timeouts; other errors fail immediately.
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 503) or attempt == 4:
                    raise
            except TimeoutError:
                if attempt == 4:
                    raise
            time.sleep(2 ** attempt * 2)

    def _call_claude(self, prompt: str) -> str:
        body = {"model": MODEL, "max_tokens": 600, "system": SYSTEM,
                "messages": [{"role": "user", "content": prompt}]}
        out = self._post("https://api.anthropic.com/v1/messages", body,
                         {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                          "anthropic-version": "2023-06-01"})
        return out["content"][0]["text"]

    def _call_gemini(self, prompt: str) -> str:
        # Gemini's OpenAI-compatible endpoint
        body = {"model": GEMINI_MODEL, "temperature": 0,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": prompt}]}
        out = self._post(GEMINI_URL, body,
                         {"authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"})
        return out["choices"][0]["message"]["content"]

    def _ask_llm(self, q, hits, retrieved) -> Answer:
        context = "\n\n".join(f"[{s.sid}] {s.title}\n{s.text}" for s, _ in hits)
        prompt = f"Sources:\n{context}\n\nQuestion: {q}"
        try:
            text = self._call_gemini(prompt) if self.mode == "gemini" else self._call_claude(prompt)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{self.mode} API call failed (HTTP {e.code}): "
                               f"{e.read()[:300]!r}. Check the API key and model name.") from e
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {"answer": text, "citations": [], "declined": False}
        # Grounding check: drop any citation that is not a real section ID.
        cites = [c.strip("[]") for c in data.get("citations", []) if c.strip("[]") in self.ids]
        if not data.get("declined") and not cites:
            return Answer(DECLINE, [], True, retrieved)   # uncited answer -> refuse
        return Answer(data.get("answer") or DECLINE, cites, bool(data.get("declined")), retrieved)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--mode", default="auto", choices=["auto", "gemini", "claude", "offline"])
    a = ap.parse_args()
    ans = Assistant(a.mode).ask(a.question)
    print(json.dumps(ans.__dict__, indent=2))


if __name__ == "__main__":
    main()
