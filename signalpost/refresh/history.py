"""Profile version history."""
import json
from pathlib import Path
from signalpost.config import PROFILES_DIR

class ProfileHistory:
    def __init__(self, base_dir=PROFILES_DIR):
        self.base_dir = Path(base_dir); self.base_dir.mkdir(parents=True, exist_ok=True)
    def save(self, org_number, profile, version=1):
        d = self.base_dir/org_number; d.mkdir(exist_ok=True)
        (d/f"v{version}.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False, default=str))
    def load_latest(self, org_number):
        d = self.base_dir/org_number
        if not d.exists(): return None
        vs = sorted(d.glob("v*.json"), reverse=True)
        return json.loads(vs[0].read_text()) if vs else None
