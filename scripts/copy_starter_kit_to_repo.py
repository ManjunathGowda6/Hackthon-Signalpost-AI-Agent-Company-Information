import shutil
from pathlib import Path

ROOT = Path(".").resolve()
SRC_SK = Path(r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit")
if not SRC_SK.exists():
    SRC_SK = ROOT / "data" / "starter_kit" / "signalpost-starter-kit"

print(f"Source Starter Kit: {SRC_SK}")

# 1. Copy src/norway_company_agent to ROOT / src / norway_company_agent
src_dest = ROOT / "src" / "norway_company_agent"
src_dest.parent.mkdir(parents=True, exist_ok=True)
if src_dest.exists():
    shutil.rmtree(src_dest)
shutil.copytree(SRC_SK / "src" / "norway_company_agent", src_dest)
print(f"Copied {src_dest}")

# 2. Copy all scripts from starter kit to ROOT / scripts
for script_file in (SRC_SK / "scripts").glob("*.py"):
    target = ROOT / "scripts" / script_file.name
    shutil.copy2(script_file, target)
    print(f"Copied script {script_file.name} to {target}")

# 3. Copy all fixtures from starter kit to ROOT / tests / fixtures
fixtures_dest = ROOT / "tests" / "fixtures"
fixtures_dest.mkdir(parents=True, exist_ok=True)
for fix_file in (SRC_SK / "tests" / "fixtures").iterdir():
    if fix_file.is_file():
        shutil.copy2(fix_file, fixtures_dest / fix_file.name)
        print(f"Copied fixture {fix_file.name} to {fixtures_dest}")

# 4. Copy test_poc.py to ROOT / tests / test_poc.py
test_poc_src = SRC_SK / "tests" / "test_poc.py"
if test_poc_src.exists():
    shutil.copy2(test_poc_src, ROOT / "tests" / "test_poc.py")
    print("Copied test_poc.py to ROOT / tests / test_poc.py")

print("Done copying all starter kit assets to self-contained repo structure!")
