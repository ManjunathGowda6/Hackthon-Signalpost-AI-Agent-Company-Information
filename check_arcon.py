import json
d = json.load(open('out/signalpost_1000.json', 'r', encoding='utf-8'))
for p in d:
    name = p.get('name', '')
    if 'ARCON' in name.upper():
        org = p.get('organisation_number', '')
        web = p.get('website', '')
        muni = p.get('municipality', '')
        print(f"Found: {name} | org: {org} | website: {web} | muni: {muni}")
        wp = p.get('website_profiles', {})
        sp = wp.get('social_profiles', [])
        if sp:
            for s in sp:
                print(f"  Social: {s.get('platform')} {s.get('url')}")
        else:
            print("  No social profiles")
        ni = wp.get('news_items', [])
        print(f"  News items: {len(ni)}")
        ha = p.get('hiring_activity', {})
        jl = ha.get('job_listings', []) or ha.get('active_listings', [])
        print(f"  Job listings: {len(jl)}")
        syn = p.get('synthesis', {})
        summary = syn.get('summary', '') if isinstance(syn, dict) else ''
        print(f"  Summary: {summary[:200]}")
        print()
