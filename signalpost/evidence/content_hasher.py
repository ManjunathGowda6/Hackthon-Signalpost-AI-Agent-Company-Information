"""Content hashing for deduplication and verification."""
import hashlib


def hash_content(content: bytes) -> str:
    """SHA-256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def hash_text(text: str) -> str:
    """SHA-256 hash of text content."""
    return hash_content(text.encode("utf-8"))
