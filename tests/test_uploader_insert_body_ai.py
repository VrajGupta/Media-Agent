"""Slice 9 — AI-gen dispatch in build_insert_body + containsSyntheticMedia gate."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.uploader.insert_body import build_insert_body


_PUBLISH_AT = datetime(2026, 5, 22, 13, 0, 0, tzinfo=timezone.utc)


class _FakeRow(dict):
    pass


def _ai_clip_row(hook="GPT-5 is here", title="GPT-5 Analysis", script_id="s123"):
    r = _FakeRow()
    r["hook"] = hook
    r["suggested_title"] = title
    r["content_kind"] = "ai_generated"
    r["script_id"] = script_id
    return r


def _sourced_clip_row(hook="The line", title="Backup", keyword="best movie scenes",
                      video_id="abc123", channel="MovieClipsChannel"):
    r = _FakeRow()
    r["hook"] = hook
    r["suggested_title"] = title
    r["content_kind"] = "sourced"
    r["v_video_id"] = video_id
    r["v_channel"] = channel
    r["v_keyword"] = keyword
    return r


def _script_row(category="ai-models", narration="AI is wild", title="GPT-5 Analysis"):
    r = _FakeRow()
    r["category"] = category
    r["narration"] = narration
    r["title"] = title
    return r


def _cfg(ai_disclosure=True):
    cfg = MagicMock()
    cfg.compliance.ai_disclosure = ai_disclosure
    return cfg


def test_contains_synthetic_media_true_for_ai_gen_with_disclosure_on():
    body = build_insert_body(
        clip_row=_ai_clip_row(),
        video_row=_ai_clip_row(),
        script_row=_script_row(),
        cfg=_cfg(ai_disclosure=True),
        padded_publish_at_utc=_PUBLISH_AT,
    )
    assert body["status"]["containsSyntheticMedia"] is True


def test_contains_synthetic_media_absent_when_disclosure_off():
    body = build_insert_body(
        clip_row=_ai_clip_row(),
        video_row=_ai_clip_row(),
        script_row=_script_row(),
        cfg=_cfg(ai_disclosure=False),
        padded_publish_at_utc=_PUBLISH_AT,
    )
    assert "containsSyntheticMedia" not in body["status"]


def test_contains_synthetic_media_absent_for_sourced_clip():
    row = _sourced_clip_row()
    body = build_insert_body(
        clip_row=row,
        video_row=row,
        cfg=_cfg(ai_disclosure=True),
        padded_publish_at_utc=_PUBLISH_AT,
    )
    assert "containsSyntheticMedia" not in body["status"]


def test_sourced_clip_description_still_has_source_and_channel():
    row = _sourced_clip_row()
    body = build_insert_body(
        clip_row=row,
        video_row=row,
        cfg=_cfg(),
        padded_publish_at_utc=_PUBLISH_AT,
    )
    assert "Source:" in body["snippet"]["description"]
    assert "Original channel:" in body["snippet"]["description"]
    assert "Made with AI." not in body["snippet"]["description"]


def test_ai_gen_description_has_footer_not_source():
    body = build_insert_body(
        clip_row=_ai_clip_row(),
        video_row=_ai_clip_row(),
        script_row=_script_row(),
        cfg=_cfg(),
        padded_publish_at_utc=_PUBLISH_AT,
    )
    desc = body["snippet"]["description"]
    assert "Made with AI. For entertainment / educational use." in desc
    assert "Source:" not in desc
    assert "Original channel:" not in desc
