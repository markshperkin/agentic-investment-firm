def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """Paragraph-aware splitting with a hard size cap and small overlap."""
    text = " ".join(text.split())
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
