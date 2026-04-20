import chardet
from typing import Tuple


def detect_and_convert(path: str) -> Tuple[str, str]:
    """Read a file, detect encoding, return (utf-8 string, detected encoding)."""
    with open(path, "rb") as f:
        raw = f.read()
    detected = chardet.detect(raw)
    enc = detected.get("encoding") or "utf-8"
    try:
        text = raw.decode(enc, errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")
    return text, enc


def fix_encoding_str(s: str) -> str:
    """Attempt to fix mojibake by re-encoding latin-1 as utf-8."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except Exception:
        return s
