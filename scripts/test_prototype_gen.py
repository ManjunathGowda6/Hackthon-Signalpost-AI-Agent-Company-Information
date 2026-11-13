import sys
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit")
from scripts.build_prototype import build
from scripts.test_research_suite import map_profile_for_eval

data = json.load(open("out/signalpost_1000.json", encoding="utf-8"))
mapped = [map_profile_for_eval(p) for p in data]
html_out = build(mapped[:100], None)
print(f"Generated prototype HTML length: {len(html_out):,} characters")
assert '<div class="brand"><i></i>Signalpost laboratory</div>' in html_out
assert 'id="q"' in html_out
assert 'id="agent-form"' in html_out
assert 'id="score-grid"' in html_out
assert 'id="list"' in html_out
assert 'id="profile"' in html_out
assert 'id="stats"' in html_out
print("All core DOM elements verified in generated prototype!")
