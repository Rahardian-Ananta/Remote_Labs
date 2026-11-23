"""Tokenization and inverted indexing helpers for Chord DHT."""

import re
from typing import List, Optional, Set


def extract_search_tokens(
    tags: Optional[List[str]],
    stdout: Optional[str],
    max_tokens: int = 20,
) -> List[str]:
    """Extract up to max_tokens unique lowercase keywords from job tags and stdout."""
    tokens: Set[str] = set()

    # Process tags
    if tags:
        for tag in tags:
            clean_tag = tag.strip().lower()
            if clean_tag and len(clean_tag) >= 2:
                tokens.add(clean_tag)
                if len(tokens) >= max_tokens:
                    return sorted(tokens)

    # Process stdout words
    if stdout:
        words = re.findall(r"[a-zA-Z0-9_\-]+", stdout.lower())
        for word in words:
            if len(word) >= 2 and not word.isdigit():
                tokens.add(word)
                if len(tokens) >= max_tokens:
                    break

    return sorted(tokens)[:max_tokens]

