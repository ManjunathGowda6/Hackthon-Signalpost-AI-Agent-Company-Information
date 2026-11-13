import json
from signalpost.collectors.website_verification import verify_social_link

data = json.load(open('out/signalpost_1000.json', encoding='utf-8'))
for p in data:
    wp = p.get('website_profiles') or {}
    ow = wp.get('official_website') or {}
    orgnr_v = isinstance(ow, dict) and ow.get('orgnr_verified', False)
    for s in wp.get('social_profiles', []):
        url = s.get('url', '')
        keep, reason = verify_social_link(url, '', p.get('name', ''), '', orgnr_verified=orgnr_v)
        if not keep:
            print(f"{p.get('name')}: {url} -> {reason}")
