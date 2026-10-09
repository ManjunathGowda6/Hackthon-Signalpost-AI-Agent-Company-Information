"""Report generator."""
import json, sys
from pathlib import Path
def main():
    f = sys.argv[1] if len(sys.argv)>1 else "out/results.json"
    data = json.loads(Path(f).read_text())
    t = len(data)
    a = sum(1 for d in data if d.get("status")=="available")
    print(f"Total: {t}, Available: {a}, Rate: {a/t*100:.1f}%" if t else "No data")
if __name__=="__main__": main()
