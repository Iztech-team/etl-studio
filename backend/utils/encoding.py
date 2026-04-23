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


def strip_directional_marks(s: str) -> str:
    """Remove invisible Unicode directional formatting marks."""
    if not isinstance(s, str):
        return s
    invisible_chars = {
        "\u200E",  # LEFT-TO-RIGHT MARK
        "\u200F",  # RIGHT-TO-LEFT MARK
        "\u202A",  # LEFT-TO-RIGHT EMBEDDING
        "\u202B",  # RIGHT-TO-LEFT EMBEDDING
        "\u202C",  # POP DIRECTIONAL FORMATTING
        "\u202D",  # LEFT-TO-RIGHT OVERRIDE
        "\u202E",  # RIGHT-TO-LEFT OVERRIDE
        "\u061C",  # ARABIC LETTER MARK
        "\u200C",  # ZERO WIDTH NON-JOINER
        "\u200D",  # ZERO WIDTH JOINER
    }
    return "".join(ch for ch in s if ch not in invisible_chars)


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
