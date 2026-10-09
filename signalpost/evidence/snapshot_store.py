"""Immutable snapshot storage."""
import hashlib, json, uuid
from datetime import datetime
from pathlib import Path
from signalpost.config import SNAPSHOTS_DIR

class SnapshotStore:
    def __init__(self, base_dir=SNAPSHOTS_DIR):
        self.base_dir = Path(base_dir); self.base_dir.mkdir(parents=True, exist_ok=True)
    def save(self, url, content, metadata=None):
        sid = f"snap_{uuid.uuid4().hex[:12]}"
        chash = hashlib.sha256(content).hexdigest()
        snap = {"snapshot_id":sid, "url":url, "retrieved_at":datetime.utcnow().isoformat()+"Z",
                "content_hash":chash, "size":len(content), **(metadata or {})}
        d = self.base_dir/sid; d.mkdir(exist_ok=True)
        (d/"metadata.json").write_text(json.dumps(snap, indent=2))
        (d/"content.raw").write_bytes(content)
        return sid
