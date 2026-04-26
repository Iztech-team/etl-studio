import chardet
from typing import Tuple


def detect_and_convert(path: str) -> Tuple[str, str]:
    """Read a file, detect encoding, return (utf-8 string, detected encoding).

    Fast path: try utf-8 first. chardet.detect is a statistical scan over
    the entire file's bytes — on the AlArabi 257-CSV dataset it
    contributes ~40s of pure waste, because every CSV in that path was
    written by our own extraction pipeline as utf-8 anyway. Only fall
    through to chardet when utf-8 actually fails to decode (i.e. it's a
    non-utf-8 file the user uploaded directly).
    """
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
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


# Build the translation table once at import time. str.translate is
# implemented in C and runs ~100x faster than a Python per-character
# generator, which matters when this is called on every cell of every
# row across 257 CSVs during a project resume.
_DIRECTIONAL_MARKS_TABLE = {
    ord(ch): None
    for ch in (
        "‎"  # LEFT-TO-RIGHT MARK
        "‏"  # RIGHT-TO-LEFT MARK
        "‪"  # LEFT-TO-RIGHT EMBEDDING
        "‫"  # RIGHT-TO-LEFT EMBEDDING
        "‬"  # POP DIRECTIONAL FORMATTING
        "‭"  # LEFT-TO-RIGHT OVERRIDE
        "‮"  # RIGHT-TO-LEFT OVERRIDE
        "؜"  # ARABIC LETTER MARK
        "‌"  # ZERO WIDTH NON-JOINER
        "‍"  # ZERO WIDTH JOINER
    )
}


def strip_directional_marks(s: str) -> str:
    """Remove invisible Unicode directional formatting marks."""
    if not isinstance(s, str):
        return s
    return s.translate(_DIRECTIONAL_MARKS_TABLE)


def normalize_arabic_digits(s: str) -> str:
    """Convert Arabic-Indic and Persian digits/separators to ASCII equivalents."""
    if not isinstance(s, str):
        return s
    replacements = {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٫": ".",
        "٬": ",",
    }
    return "".join(replacements.get(ch, ch) for ch in s)
