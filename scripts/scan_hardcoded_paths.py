import os

forbidden = [r"C:\Users", "C:/Users", "Downloads", "signalpost-starter-kit"]
hits = []
for root, dirs, files in os.walk("."):
    if any(ignore in root for ignore in [".git", "__pycache__", ".pytest_cache", "signalpost-starter-kit.tar.gz"]):
        continue
    for f in files:
        if f.endswith((".py", ".json", ".jsonl", ".sh", ".yaml", ".yml", ".toml", ".txt", ".md", ".html")):
            p = os.path.join(root, f)
            try:
                content = open(p, encoding="utf-8", errors="ignore").read()
                for term in forbidden:
                    if term.lower() in content.lower():
                        hits.append((p, term))
            except Exception:
                pass

for h in hits[:60]:
    print(f'{h[0]} contains "{h[1]}"')
print(f"Total occurrences found: {len(hits)}")
