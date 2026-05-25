"""Issue 10 — clean_mojibake utility.

Tests verify observable behaviour of clean_mojibake through its public interface.
No network, no DB, no GPU required.
"""

from __future__ import annotations

from src.scripter.sanitize import clean_mojibake


def test_empty_string_returns_empty():
    assert clean_mojibake("") == ""


def test_no_mojibake_returns_input_unchanged():
    text = "Corti's Symphony beats OpenAI at medical speech recognition."
    assert clean_mojibake(text) == text


def test_single_replacement_character_becomes_apostrophe():
    assert clean_mojibake("Corti�S Symphony") == "Corti'S Symphony"


def test_multiple_replacement_characters_all_replaced():
    assert clean_mojibake("OpenAI�s score vs Corti�s score") == "OpenAI's score vs Corti's score"


def test_surrounding_content_preserved_exactly():
    text = "  \t数字AI「Corti」� s score: 1.4% vs OpenAI� s 17.7%.\n"
    expected = "  \t数字AI「Corti」' s score: 1.4% vs OpenAI' s 17.7%.\n"
    assert clean_mojibake(text) == expected
