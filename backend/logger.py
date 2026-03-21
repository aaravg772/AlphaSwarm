from __future__ import annotations

import datetime as dt
import threading

RESET = "\033[0m"
COLORS = {
    "SYSTEM": "\033[96m",
    "API": "\033[94m",
    "BUDGET": "\033[93m",
    "AGENT": "\033[92m",
    "COMPOUND": "\033[36m",
    "INSTANT": "\033[35m",
    "CACHE": "\033[95m",
    "PHASE": "\033[1;97m",
    "MEMO": "\033[92m",
    "CONFIG": "\033[96m",
    "WARN": "\033[33m",
    "ERROR": "\033[31m",
    "GUARD": "\033[93m",
}


class AlphaLogger:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _emit(self, tag: str, message: str) -> None:
        ts = dt.datetime.now().strftime("%H:%M:%S")
        color = COLORS.get(tag, "")
        with self._lock:
            print(f"{color}[{tag:<9}] {ts} {message}{RESET}")

    def log_system(self, message: str) -> None:
        self._emit("SYSTEM", message)

    def log_api(self, message: str) -> None:
        self._emit("API", message)

    def log_budget(self, message: str) -> None:
        self._emit("BUDGET", message)

    def log_agent(self, message: str) -> None:
        self._emit("AGENT", message)

    def log_compound(self, message: str) -> None:
        self._emit("COMPOUND", message)

    def log_instant(self, message: str) -> None:
        self._emit("INSTANT", message)

    def log_cache(self, message: str) -> None:
        self._emit("CACHE", message)

    def log_phase(self, message: str) -> None:
        self._emit("PHASE", message)

    def log_memo(self, message: str) -> None:
        self._emit("MEMO", message)

    def log_config(self, message: str) -> None:
        self._emit("CONFIG", message)

    def log_warn(self, message: str) -> None:
        self._emit("WARN", message)

    def log_error(self, message: str) -> None:
        self._emit("ERROR", message)

    def log_hallucination_scan(
        self,
        *,
        agent_name: str,
        risk_level: str,
        unsourced_count: int,
        warning_count: int,
    ) -> None:
        self._emit(
            "GUARD",
            f"{agent_name}: risk={risk_level} unsourced={unsourced_count} warnings={warning_count}",
        )

    def log_hallucination_filtered(self, agent_name: str, reason: str) -> None:
        self._emit("GUARD", f"⚠ {agent_name} findings prefixed with risk warning before synthesis ({reason})")

    def log_memo_validation(self, *, issues_count: int, passed: bool) -> None:
        status = "✓ PASSED" if passed else "⚠ ISSUES FOUND"
        self._emit("GUARD", f"Memo validation: {issues_count} issues {status}")


logger = AlphaLogger()


def mask_key(key: str | None) -> str:
    if not key:
        return "missing"
    return f"...{key[-4:]}" if len(key) > 4 else "****"
