"""URL validation and safety."""
from urllib.parse import urlparse
BLOCKED = {"linkedin.com","www.linkedin.com","facebook.com","www.facebook.com",
           "glassdoor.com","www.glassdoor.com","indeed.com","www.indeed.com"}
def is_safe_url(url):
    try:
        p = urlparse(url); d = (p.hostname or "").lower()
        return d not in BLOCKED and p.scheme in ("http","https")
    except: return False
def normalize_url(url):
    p = urlparse(url); return f"{p.scheme}://{p.hostname}{p.path}".rstrip("/")
