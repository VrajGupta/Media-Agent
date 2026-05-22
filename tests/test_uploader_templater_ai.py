"""Slice 9 — AI-gen description and tags templating."""

from __future__ import annotations

from src.uploader.templater import build_description_ai, build_tags_ai


# ---------------------------------------------------------------------------
# build_description_ai
# ---------------------------------------------------------------------------

def test_ai_description_layout_hook_footer_hashtag():
    desc = build_description_ai(
        hook="Why GPT-5 will change coding forever",
        suggested_title="GPT-5 Analysis",
        category="ai-models",
    )
    hook_pos = desc.index("Why GPT-5 will change coding forever")
    footer_pos = desc.index("Made with AI. For entertainment / educational use.")
    hashtag_pos = desc.index("#Shorts")
    assert hook_pos < footer_pos < hashtag_pos
    assert "#aimodels" in desc


def test_ai_description_null_category_falls_back_to_suggested_title_slug():
    desc = build_description_ai(
        hook="",
        suggested_title="AI Models Explained",
        category=None,
    )
    assert "#aimodelsexplained" in desc
    assert "Made with AI." in desc


def test_ai_description_never_contains_source_or_channel():
    for category, hook in [("ai-models", "Big hook"), (None, ""), ("", "")]:
        desc = build_description_ai(
            hook=hook,
            suggested_title="Some Title",
            category=category,
        )
        assert "Source:" not in desc
        assert "Original channel:" not in desc


# ---------------------------------------------------------------------------
# build_tags_ai
# ---------------------------------------------------------------------------

def test_ai_tags_category_slug_first_then_static_set():
    tags = build_tags_ai(category="ai-models", suggested_title="")
    assert tags[0] == "aimodels"
    assert "shorts" in tags
    assert "viral" in tags


def test_ai_tags_no_duplicates():
    tags = build_tags_ai(category="shorts", suggested_title="")
    assert tags.count("shorts") == 1


def test_ai_tags_null_category_falls_back_to_suggested_title_slug():
    tags = build_tags_ai(category=None, suggested_title="AI Policy News")
    assert tags[0] == "aipolicynews"
    assert "shorts" in tags


def test_ai_tags_500_char_budget_honored():
    huge = "x" * 600
    tags = build_tags_ai(category=huge, suggested_title="")
    joined = ",".join(tags)
    assert len(joined) <= 500
