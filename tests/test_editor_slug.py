"""Slug derivation tests."""

from __future__ import annotations

from src.editor.slug import MAX_SLUG_LENGTH, title_slug


def test_short_title_lowercased_and_underscored():
    s = title_slug("Joe Rogan Stoicism", "v1_0_30")
    # ends with a 4-char hash suffix.
    assert s.startswith("joe_rogan_stoicism_")
    assert len(s.split("_")[-1]) == 4


def test_special_chars_collapsed():
    s = title_slug('Joe Rogan: "AI Will Kill Us!"', "v1_0_30")
    assert s.startswith("joe_rogan_ai_will_kill_us_")


def test_truncation_at_word_boundary():
    long_title = "the quick brown fox jumps over the lazy dog and runs through forests of tall green trees"
    s = title_slug(long_title, "v1_0_30")
    assert len(s) <= MAX_SLUG_LENGTH
    # Truncated at an underscore (word boundary), not mid-word.
    base = s.rsplit("_", 1)[0]
    assert "_" in base


def test_distinct_clip_ids_get_distinct_suffixes():
    s1 = title_slug("Same Title", "video1_0_30")
    s2 = title_slug("Same Title", "video2_0_30")
    assert s1 != s2
    # Same prefix.
    assert s1.rsplit("_", 1)[0] == s2.rsplit("_", 1)[0]


def test_same_clip_id_gives_stable_suffix():
    s1 = title_slug("Some Title", "v1_0_30")
    s2 = title_slug("Some Title", "v1_0_30")
    assert s1 == s2


def test_empty_title_falls_back_to_untitled():
    s = title_slug("", "v1_0_30")
    assert s.startswith("untitled_")


def test_only_special_chars_falls_back_to_untitled():
    s = title_slug("!@#$%^&*()", "v1_0_30")
    assert s.startswith("untitled_")
