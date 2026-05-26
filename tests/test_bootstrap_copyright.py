"""bootstrap copyright_acknowledgement check (ADR-0003)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.bootstrap import check_copyright_acknowledgement


def test_copyright_ack_warns_when_absent(capsys):
    cfg = MagicMock()
    cfg.copyright_acknowledgement = None
    assert check_copyright_acknowledgement(cfg) is True
    out = capsys.readouterr().out
    assert "WARN copyright-ack" in out


def test_copyright_ack_passes_with_hybrid_value(capsys):
    cfg = MagicMock()
    cfg.copyright_acknowledgement = "hybrid_real_image_v1"
    assert check_copyright_acknowledgement(cfg) is True
    out = capsys.readouterr().out
    assert "OK" in out
    assert "hybrid_real_image_v1" in out
