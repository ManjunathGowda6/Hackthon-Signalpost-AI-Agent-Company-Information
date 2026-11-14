with open("signalpost/web/app.py", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "def index(" in line or "@app.route(\"/\")" in line:
        print(f"Line {i+1}: {line}")
