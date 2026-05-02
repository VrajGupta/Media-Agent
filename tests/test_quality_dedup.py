"""Perceptual-hash dedup matcher and frame timestamp computation."""

from __future__ import annotations

from src.quality_screen import dedup as dedup_mod
from src.quality_screen.dedup import FRAME_PERCENTS, find_phash_match


# ---- frame timestamp policy -------------------------------------------------


def test_frame_percents_avoid_endpoints():
    """Per the plan: 10/30/50/70/90% — never 0% or 100%."""
    assert FRAME_PERCENTS == (0.10, 0.30, 0.50, 0.70, 0.90)
    assert 0.0 not in FRAME_PERCENTS
    assert 1.0 not in FRAME_PERCENTS


# ---- phash matcher ----------------------------------------------------------


def _row(clip_id: str, phash_hex: str, audio_fp: str | None = None) -> dict:
    return {"clip_id": clip_id, "phash": phash_hex, "audio_fp": audio_fp}


# Two valid 16-hex-char (64-bit) phashes, identical → distance 0.
_PHASH_A = "abcdef0123456789"
# Same except last hex character — Hamming distance 4 bits.
_PHASH_A_NEAR = "abcdef012345678a"


def test_no_stored_rows_returns_no_match():
    assert find_phash_match([_PHASH_A], [], min_hamming=8) is None
    assert find_phash_match([], [_row("c1", _PHASH_A)], min_hamming=8) is None


def test_identical_phash_matches_with_zero_distance():
    match = find_phash_match(
        [_PHASH_A],
        [_row("c1", _PHASH_A)],
        min_hamming=8,
    )
    assert match is not None
    assert match.matching_clip_id == "c1"
    assert match.hamming_distance == 0


def test_close_phash_under_threshold_matches():
    match = find_phash_match(
        [_PHASH_A_NEAR],
        [_row("c1", _PHASH_A)],
        min_hamming=8,
    )
    assert match is not None
    assert match.hamming_distance < 8


def test_distance_at_threshold_does_not_match():
    """min_hamming=8 means distance<8 rejects; distance>=8 passes."""
    # Build a hash that flips many bits relative to A.
    distant = "ffff0000ffff0000"
    match = find_phash_match([distant], [_row("c1", _PHASH_A)], min_hamming=8)
    # Distance is 32 (way above 8); no match.
    assert match is None


def test_invalid_hex_in_stored_row_is_skipped():
    """Bad data in dup_hashes shouldn't crash the matcher."""
    rows = [_row("c1", "not-hex"), _row("c2", _PHASH_A)]
    match = find_phash_match([_PHASH_A], rows, min_hamming=8)
    assert match is not None
    assert match.matching_clip_id == "c2"


def test_min_distance_picked_when_multiple_matches():
    """When multiple stored rows are below threshold, return the closest."""
    rows = [
        _row("far", _PHASH_A_NEAR),    # distance ~4
        _row("close", _PHASH_A),       # distance 0
    ]
    match = find_phash_match([_PHASH_A], rows, min_hamming=8)
    assert match is not None
    assert match.matching_clip_id == "close"
    assert match.hamming_distance == 0


# ---- compute_signals deduplicates frame phashes -----------------------------


def test_compute_signals_dedupes_identical_frames(monkeypatch, tmp_path):
    """If 5 frames produce the same phash (low-motion clip), the resulting
    list collapses to a single hash. Belt-and-suspenders against the
    dup_hashes (clip_id, phash) PK collision."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 4096)

    # All 5 frame extracts return the same phash.
    extract_calls = {"n": 0}
    def fake_extract(video_path, t, work_dir):
        extract_calls["n"] += 1
        return _PHASH_A
    monkeypatch.setattr(dedup_mod, "_extract_frame_phash", fake_extract)
    # Avoid needing fpcalc / network in the unit test.
    monkeypatch.setattr(dedup_mod, "_compute_audio_fingerprint", lambda v: None)

    signals = dedup_mod.compute_signals(video, duration_s=33.6)
    assert extract_calls["n"] == 5  # all 5 percents tried
    assert signals.phashes == [_PHASH_A]  # but only 1 unique
    assert signals.audio_fp is None


def test_compute_signals_skips_failed_frame_extracts(monkeypatch, tmp_path):
    """A None return from _extract_frame_phash (extract failure) is dropped."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 4096)

    sequence = [_PHASH_A, None, "fedcba9876543210", None, _PHASH_A]
    idx = {"i": 0}
    def fake_extract(video_path, t, work_dir):
        i = idx["i"]
        idx["i"] += 1
        return sequence[i]
    monkeypatch.setattr(dedup_mod, "_extract_frame_phash", fake_extract)
    monkeypatch.setattr(dedup_mod, "_compute_audio_fingerprint", lambda v: None)

    signals = dedup_mod.compute_signals(video, duration_s=33.6)
    # Two unique phashes survive: _PHASH_A (twice, deduped) + the other one.
    assert sorted(signals.phashes) == sorted([_PHASH_A, "fedcba9876543210"])
