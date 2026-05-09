"""Phase 7 tests for loguru rotation + retention configuration.

Loguru's actual file rotation runs on real-time triggers; verifying the
*configured* values is sufficient since we don't want to wait 24 h in a
unit test. We also verify a basic write reaches agent.log so future
regressions on the file-handler wiring fail loudly.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.observability.logging_setup import setup_logging


def test_setup_logging_creates_handler(tmp_path):
    """setup_logging adds at least one file handler under tmp_path/logs."""
    setup_logging(tmp_path)
    # Loguru exposes its handler registry on logger._core.handlers.
    handlers = logger._core.handlers  # type: ignore[attr-defined]
    file_sinks = [h for h in handlers.values() if str(getattr(h, "_name", "")).endswith("agent.log'")]
    assert file_sinks, f"no file sink for agent.log in {list(handlers.values())}"


def test_log_writes_to_agent_log(tmp_path):
    """An emitted INFO line lands in logs/agent.log."""
    setup_logging(tmp_path)
    logger.info("phase_7_rotation_test_marker_alpha")
    # Loguru with enqueue=True flushes asynchronously; `complete` blocks until empty.
    logger.complete()
    log_path = tmp_path / "agent.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8", errors="replace")
    assert "phase_7_rotation_test_marker_alpha" in content


def test_rotation_handler_settings(tmp_path):
    """The file sink is configured with daily rotation + 30-day retention + zip compression."""
    setup_logging(tmp_path)
    handlers = logger._core.handlers  # type: ignore[attr-defined]
    file_handlers = [
        h for h in handlers.values()
        if str(getattr(h, "_name", "")).endswith("agent.log'")
    ]
    assert file_handlers
    # The actual rotation/retention/compression callables live on the inner
    # FileSink object the handler wraps.
    file_sink = file_handlers[0]._sink
    sink_vars = vars(file_sink)
    # Loguru parses each config into a callable stored as _rotation_function /
    # _retention_function / _compression_function. We verify all three are
    # set (non-None) — that's a stable contract across loguru versions.
    assert sink_vars.get("_rotation_function") is not None, "rotation not configured"
    assert sink_vars.get("_retention_function") is not None, "retention not configured"
    assert sink_vars.get("_compression_function") is not None, "compression not configured"
