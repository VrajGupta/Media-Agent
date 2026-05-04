"""Phase 5 — title / description / tag templating."""

from __future__ import annotations

from src.uploader.templater import build_description, build_tags, build_title


def test_short_hook_appends_shorts_suffix():
    assert build_title("Iconic line") == "Iconic line #Shorts"


def test_hook_exactly_100_chars_with_suffix_kept_intact():
    # 92-char hook + " #Shorts" (8) = 100 exactly.
    hook = "x" * 92
    title = build_title(hook)
    assert len(title) == 100
    assert title.endswith(" #Shorts")


def test_hook_too_long_truncates_at_word_boundary_keeping_shorts():
    hook = (
        "This is an extremely long hook that absolutely will not fit "
        "within the YouTube one hundred character title limit when we "
        "tack on the shorts hashtag suffix."
    )
    title = build_title(hook)
    assert len(title) <= 100
    assert title.endswith(" #Shorts")
    # Verify we trimmed at a word boundary, not mid-word.
    body = title[: -len(" #Shorts")]
    assert not body.endswith("-") and not body.endswith(" ")


def test_empty_hook_falls_back_to_suggested_title():
    assert build_title("", "Backup title") == "Backup title #Shorts"


def test_description_includes_source_url_and_channel():
    desc = build_description(
        hook="The line",
        suggested_title="",
        video_id="abc123",
        channel="MovieClipsChannel",
        keyword="best movie scenes",
    )
    assert "Source: https://youtube.com/watch?v=abc123" in desc
    assert "Original channel: MovieClipsChannel" in desc
    assert "#Shorts" in desc
    assert "#bestmoviescenes" in desc       # keyword slug


def test_tags_lowercase_deduped_and_keyword_first():
    tags = build_tags("Best Movie Scenes")
    assert tags[0] == "best movie scenes"
    assert "shorts" in tags
    assert "viral" in tags
    assert len(tags) == len(set(tags))      # no duplicates


def test_tags_total_length_capped_at_500_chars():
    huge = "x" * 600
    tags = build_tags(huge)
    joined_with_seps = ",".join(tags)
    assert len(joined_with_seps) <= 500
