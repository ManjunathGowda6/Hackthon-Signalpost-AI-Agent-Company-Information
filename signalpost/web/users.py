"""User management module for Signalpost AI auth (email-only registration and login)."""
import json
import re
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _load_data() -> dict:
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading users file: {e}")
            return {"users": {}}
    return {"users": {}}


def _save_data(data: dict) -> bool:
    try:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving users file: {e}")
        return False


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def find_user(email: str) -> dict | None:
    if not email:
        return None
    email_clean = email.strip().lower()
    data = _load_data()
    return data.get("users", {}).get(email_clean)


def register_user(email: str) -> tuple[bool, str, dict | None]:
    if not email:
        return False, "Email address is required.", None
    email_clean = email.strip().lower()
    if not is_valid_email(email_clean):
        return False, "Please enter a valid email address (e.g. name@example.com).", None

    data = _load_data()
    users = data.setdefault("users", {})
    now_iso = datetime.now().isoformat()

    if email_clean in users:
        # User already exists - update last login and allow access
        users[email_clean]["last_login"] = now_iso
        _save_data(data)
        return True, "Email already registered. Signing you in...", users[email_clean]

    user_record = {
        "email": email_clean,
        "created_at": now_iso,
        "last_login": now_iso,
    }
    users[email_clean] = user_record
    _save_data(data)
    return True, "Account created successfully!", user_record


def login_user(email: str) -> tuple[bool, str, dict | None]:
    if not email:
        return False, "Email address is required.", None
    email_clean = email.strip().lower()
    if not is_valid_email(email_clean):
        return False, "Please enter a valid email address (e.g. name@example.com).", None

    data = _load_data()
    users = data.get("users", {})
    if email_clean not in users:
        return False, f"No account found for '{email_clean}'. Please register first.", None

    now_iso = datetime.now().isoformat()
    users[email_clean]["last_login"] = now_iso
    _save_data(data)
    return True, "Welcome back!", users[email_clean]
