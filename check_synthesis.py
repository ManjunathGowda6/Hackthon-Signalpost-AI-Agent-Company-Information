import json
d = json.load(open('out/signalpost_1000.json', 'r', encoding='utf-8'))
# Show synthesis examples for different types
count = 0
for p in d:
    syn = p.get('synthesis', {})
    if isinstance(syn, dict):
        s = syn.get('summary', '')
        if s and count < 5:
            print(f"=== {p['name']} ===")
            print(s[:400])
            print()
            count += 1
# Show one with financials
for p in d:
    aa = p.get('annual_accounts', {})
    if aa.get('status') == 'available' and aa.get('revenue', {}).get('value'):
        syn = p.get('synthesis', {})
        if isinstance(syn, dict):
            s = syn.get('summary', '')
            print(f"=== {p['name']} (WITH FINANCIALS) ===")
            print(s[:500])
            print()
            break
# Show one without website
for p in d:
    if not p.get('website'):
        syn = p.get('synthesis', {})
        if isinstance(syn, dict):
            s = syn.get('summary', '')
            print(f"=== {p['name']} (NO WEBSITE) ===")
            print(s[:400])
            print()
            break
