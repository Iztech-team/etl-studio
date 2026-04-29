import chardet
from typing import Tuple


def detect_and_convert(path: str) -> Tuple[str, str]:
    """Read a file, detect encoding, return (utf-8 string, detected encoding).

    NOTE: this function loads the entire file into memory. Prefer
    `detect_encoding(path)` + streaming `open(path, encoding=...)` for
    large CSVs — see _extract_csv in core/extract/extractor.py for the
    streaming path. Kept here for SQL / SQL-dump callers that need the
    whole text for parsing.
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


def detect_encoding(path: str, sample_bytes: int = 1_048_576) -> str:
    """Sample-based encoding detection for files too large to fit in RAM.

    Reads the first 1 MiB and tries utf-8 first; falls back to chardet
    on the same sample. Avoids the multi-GB ballooning that
    `detect_and_convert` causes for large CSV uploads.
    """
    with open(path, "rb") as f:
        sample = f.read(sample_bytes)
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    detected = chardet.detect(sample)
    return detected.get("encoding") or "utf-8"


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
