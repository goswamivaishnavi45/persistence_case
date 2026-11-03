"""Build outputs/explorer.html: one self-contained file (engine + data inlined)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from export_data import compact  # noqa: E402
from generate_data import GenConfig, generate  # noqa: E402
from sensitivity import truth_benchmark  # noqa: E402

SRC = Path(__file__).parent
OUT = SRC.parent / "outputs"

if __name__ == "__main__":
    f, e, t = generate(GenConfig())
    data = compact(f, e)
    html = (SRC / "explorer_template.html").read_text()
    html = html.replace("/*ENGINE*/", (SRC / "engine.js").read_text())
    html = html.replace("/*DATA*/", json.dumps(data, separators=(",", ":")))
    html = html.replace("/*TRUTH*/", str(truth_benchmark(t)))
    OUT.mkdir(exist_ok=True)
    (OUT / "explorer.html").write_text(html)
    print(f"wrote {OUT / 'explorer.html'} ({len(html) / 1e6:.1f} MB)")
