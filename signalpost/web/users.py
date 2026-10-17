"""User management for Signalpost AI (email, username, password, age, gender)."""
import json
import re
from datetime import datetime
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


def _load() -> dict:
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"users": {}, "usernames": {}}
    return {"users": {}, "usernames": {}}


def _save(data: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def register_user(email, username, password, age=None, gender=None):
    """Register with email, username, password, age, gender. Returns (ok, msg, user)."""
    email = (email or "").strip().lower()
    username = (username or "").strip().lower()
    password = (password or "").strip()

    if not email or not EMAIL_RE.match(email):
        return False, "Please enter a valid email (e.g. name@gmail.com).", None
    if not username or not USERNAME_RE.match(username):
        return False, "Username must be 3-20 characters (letters, numbers, underscore only).", None
    if not password or len(password) < 4:
        return False, "Password must be at least 4 characters.", None

    data = _load()
    users = data.setdefault("users", {})
    unames = data.setdefault("usernames", {})

    if email in users:
        return False, "This email is already registered. Please sign in.", None
    if username in unames:
        return False, "This username is taken. Try another one.", None

    now = datetime.now().isoformat()
    user = {
        "email": email,
        "username": username,
        "password_hash": generate_password_hash(password),
        "age": age,
        "gender": gender,
        "created_at": now,
        "last_login": now,
    }
    users[email] = user
    unames[username] = email
    _save(data)
    return True, "Account created!", user


def login_user(identifier, password):
    """Login with email or username + password. Returns (ok, msg, user)."""
    identifier = (identifier or "").strip().lower()
    password = (password or "").strip()

    if not identifier:
        return False, "Please enter your email or username.", None
    if not password:
        return False, "Please enter your password.", None

    data = _load()
    users = data.get("users", {})
    unames = data.get("usernames", {})

    # Find user by email or username
    user = None
    if "@" in identifier:
        user = users.get(identifier)
    else:
        mapped_email = unames.get(identifier)
        if mapped_email:
            user = users.get(mapped_email)

    if not user:
        return False, "No account found. Please register first.", None

    # Check if user has password_hash (old email-only users won't)
    ph = user.get("password_hash")
    if not ph:
        # Legacy user without password - allow login and prompt to set password
        user["last_login"] = datetime.now().isoformat()
        _save(data)
        return True, "Welcome back!", user

    if not check_password_hash(ph, password):
        return False, "Incorrect password. Please try again.", None

    user["last_login"] = datetime.now().isoformat()
    _save(data)
    return True, "Welcome back!", user


def find_user(email):
    if not email:
        return None
    data = _load()
    return data.get("users", {}).get(email.strip().lower())
