from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

ALERTS_HEADER = (
    "| timestamp_utc | kind | message |\n"
    "| --- | --- | --- |\n"
)


def append_alert(logs_dir: str | Path, kind: str, message: str) -> None:
    """Append a row to logs/alerts.md. Creates the file with a header if missing."""
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    alerts_path = logs_dir / "alerts.md"
    if not alerts_path.exists():
        alerts_path.write_text("# Alerts\n\n" + ALERTS_HEADER, encoding="utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    safe_msg = message.replace("|", "\\|").replace("\n", " ")
    with alerts_path.open("a", encoding="utf-8") as f:
        f.write(f"| {ts} | {kind} | {safe_msg} |\n")
