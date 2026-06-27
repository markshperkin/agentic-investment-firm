import re

# Untrusted corpus/news text must never issue instructions. Chunks matching these
# imperative / tool-directive patterns are quarantined before reaching any agent.
_PATTERNS = [
    r"ignore (all |the )?(previous|prior|above) (instructions|prompt)",
    r"disregard (the |all )?(previous|prior|above)",
    r"system\s*:",
    r"you are now",
    r"new instructions?:",
    r"(buy|sell|purchase) (now|immediately|at any price)",
    r"transfer (funds|money|all)",
    r"override (the )?(risk|limits|engine)",
]
_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def is_injection(text: str) -> bool:
    return bool(_RE.search(text))


def scan(chunks: list) -> tuple[list, list]:
    """Split chunks into (clean, quarantined). `chunks` is any object exposing a
    `.text` attribute."""
    clean, quarantined = [], []
    for c in chunks:
        (quarantined if is_injection(c.text) else clean).append(c)
    return clean, quarantined
