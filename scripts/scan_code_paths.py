import os

forbidden = [r"C:\Users", "C:/Users", "Downloads", "signalpost-starter-kit"]
dirs_to_check = ["signalpost", "scripts", "tests"]
hits = []
for d in dirs_to_check:
    for root, _, files in os.walk(d):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith((".py", ".sh", ".yaml", ".yml", ".toml", ".txt")):
                p = os.path.join(root, f)
                try:
                    content = open(p, encoding="utf-8", errors="ignore").read()
                    for term in forbidden:
                        if term.lower() in content.lower():
                            hits.append((p, term))
                except Exception:
                    pass

for h in hits:
    print(f'{h[0]} contains "{h[1]}"')
print(f"Total occurrences found in code & tests: {len(hits)}")
