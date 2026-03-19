"""Text utilities shared across application modules."""

from __future__ import annotations

from typing import List


def extract_keywords(text: str, max_keywords: int = 20) -> List[str]:
    """Extract keywords from text. Whitespace split + CJK bigrams.

    - Filters out words shorter than 3 characters (English stop-word proxy).
    - Generates bigrams from contiguous CJK characters.
    - Caps output at *max_keywords* entries.
    """
    if not text:
        return []
    words = text.split()
    keywords = [w for w in words if len(w) > 2]  # Skip very short words
    # Chinese bigrams: detect CJK characters
    cjk_chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    for i in range(len(cjk_chars) - 1):
        keywords.append(cjk_chars[i] + cjk_chars[i + 1])
    return keywords[:max_keywords]
