from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RESEARCH_DIR = Path(__file__).resolve().parent.parent / "research"
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)


def session_path(session_id: str) -> Path:
    return RESEARCH_DIR / f"{session_id}.json"


def save_session(session_data: dict[str, Any]) -> None:
    sid = session_data["session_id"]
    path = session_path(sid)
    path.write_text(json.dumps(session_data, indent=2, ensure_ascii=True), encoding="utf-8")


def load_session(session_id: str) -> dict[str, Any] | None:
    path = session_path(session_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(RESEARCH_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("session_id"):
                continue
            memo = data.get("memo") or {}
            rows.append(
                {
                    "session_id": data.get("session_id"),
                    "target": data.get("target"),
                    "mode": data.get("mode", "standard"),
                    "created_at": data.get("created_at"),
                    "status": data.get("status"),
                    "depth": data.get("depth", "standard"),
                    "verdict": memo.get("verdict"),
                    "confidence": memo.get("confidence"),
                    "overall_score": memo.get("overall_score"),
                    "agents_total": len(data.get("agent_ids", [])) or data.get("agents_total", 0),
                    "calls_used": data.get("budget_used", 0),
                }
            )
        except Exception:
            continue
    return rows


def delete_session(session_id: str) -> bool:
    path = session_path(session_id)
    if path.exists():
        path.unlink()
        return True
    return False
