"""Banlist substring match (case-insensitive, word-boundary).

Cheap. Runs first inside evaluate_clip_policy.
"""

from __future__ import annotations

import re
from typing import Optional


def find_banlisted_term(text: str, banlist: list[str]) -> Optional[str]:
    """Returns the first banlisted phrase found in text, or None.

    Match is case-insensitive and uses word boundaries so 'ass' doesn't fire
    on 'classic'. Multi-word phrases (e.g. 'racial slur') match as a single
    boundary-anchored substring; whitespace inside the phrase matches any
    whitespace in the text.
    """
    if not banlist or not text:
        return None
    haystack = text
    for term in banlist:
        term = term.strip()
        if not term:
            continue
        # \b around each end of the phrase. Internal whitespace becomes \s+
        # so 'racial slur' matches 'racial   slur' and 'racial\nslur'.
        pattern = r"\b" + r"\s+".join(re.escape(p) for p in term.split()) + r"\b"
        if re.search(pattern, haystack, flags=re.IGNORECASE):
            return term
    return None
