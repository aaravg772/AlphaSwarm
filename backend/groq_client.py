from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from groq import Groq

from .config import cfg
from .logger import logger, mask_key
from .session import RESEARCH_DIR

BUDGET_PATH = RESEARCH_DIR / "budget.json"
QUERY_CACHE_PATH = RESEARCH_DIR / "query_cache.json"
QUERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def extract_sources_from_response(response: Any) -> tuple[list[str], bool]:
    sources: list[str] = []
    method1 = False

    try:
        if hasattr(response, "x_groq"):
            xg = response.x_groq
            for attr in ["executed_tools", "tool_calls", "search_results"]:
                tools = getattr(xg, attr, None)
                if not tools:
                    continue
                for tool in tools:
                    output = str(getattr(tool, "output", ""))
                    if isinstance(tool, dict):
                        output = str(tool.get("output", output))
                    urls = re.findall(r"https?://[^\s'\"<>\]]+", output)
                    if urls:
                        method1 = True
                    sources.extend(urls[:5])
    except Exception as exc:
        logger.log_warn(f"executed_tools parse failed: {exc}")

    response_text = ""
    try:
        response_text = str(response.choices[0].message.content or "")
    except Exception:
        response_text = ""

    bracket_urls = re.findall(r"[〔\[](https?://[^\s〕\]]+)[〕\]]", response_text)
    sources.extend(bracket_urls)

    plain_urls = re.findall(r"(?<!\[)(https?://[^\s'\"<>\]〕]+)", response_text)
    sources.extend(plain_urls[:10])

    seen = set()
    cleaned: list[str] = []
    for url in sources:
        normalized = url.rstrip(".,;)")
        if normalized not in seen and len(normalized) > 15:
            seen.add(normalized)
            cleaned.append(normalized)

    return cleaned[:20], method1


class GroqClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is required")
        self.api_key = key
        self.client = Groq(api_key=key)
        self._load_query_cache()
        self._load_budget()

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def api_key_set(self) -> bool:
        return bool(self.api_key)

    def api_key_masked(self) -> str:
        return mask_key(self.api_key)

    def _default_budget(self) -> dict[str, Any]:
        return {
            "date": self._today(),
            "compound_calls_used": 0,
            "compound_calls_limit": int(cfg.daily_compound_limit),
            "sessions_today": [],
        }

    def _load_budget(self) -> None:
        if not BUDGET_PATH.exists():
            self._write_budget(self._default_budget())
            return
        self._maybe_reset_budget_day()

    def _maybe_reset_budget_day(self) -> None:
        if not BUDGET_PATH.exists():
            return
        data = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
        if data.get("date") != self._today():
            self._write_budget(self._default_budget())
            return
        data["compound_calls_limit"] = int(cfg.daily_compound_limit)
        self._write_budget(data)

    def _read_budget(self) -> dict[str, Any]:
        self._maybe_reset_budget_day()
        return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))

    def _write_budget(self, payload: dict[str, Any]) -> None:
        BUDGET_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def reset_budget_today(self) -> dict[str, Any]:
        current = self._read_budget()
        current["compound_calls_used"] = 0
        current["sessions_today"] = []
        current["compound_calls_limit"] = int(cfg.daily_compound_limit)
        self._write_budget(current)
        return self.get_budget_status()

    def get_budget_status(self) -> dict[str, Any]:
        data = self._read_budget()
        limit = int(data.get("compound_calls_limit", cfg.daily_compound_limit))
        used = int(data.get("compound_calls_used", 0))
        remaining = max(limit - used, 0)
        return {
            "date": data.get("date"),
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "remaining_pct": round((remaining / limit) * 100, 2) if limit else 0,
            "sessions_today": data.get("sessions_today", []),
        }

    def ensure_budget_for_run(self, *, required_calls: int) -> tuple[bool, str | None]:
        budget = self.get_budget_status()
        remaining = int(budget["remaining"])
        if cfg.budget_hard_floor > 0 and remaining < int(cfg.budget_hard_floor):
            return (
                False,
                f"Insufficient daily budget. Remaining {remaining} is below hard floor {cfg.budget_hard_floor}.",
            )
        if required_calls <= remaining:
            if remaining <= int(cfg.budget_warning_threshold):
                logger.log_warn(
                    f"Budget warning: remaining {remaining} is at/below warning threshold {cfg.budget_warning_threshold}"
                )
            return True, None
        msg = (
            f"Insufficient daily budget. Need {required_calls}, have {remaining}. "
            f"Try Quick depth ({cfg.quick_compound_calls} calls) or wait until midnight."
        )
        return False, msg

    def _increment_budget(self, *, session_id: str, target: str, calls: int = 1) -> dict[str, Any]:
        data = self._read_budget()
        data["compound_calls_used"] = int(data.get("compound_calls_used", 0)) + calls
        sessions_today = data.setdefault("sessions_today", [])
        existing = next((s for s in sessions_today if s.get("session_id") == session_id), None)
        if existing:
            existing["calls"] = int(existing.get("calls", 0)) + calls
        else:
            sessions_today.append({"session_id": session_id, "calls": calls, "target": target})
        self._write_budget(data)
        status = self.get_budget_status()
        logger.log_budget(f"Used: {status['used']}/{status['limit']} ({status['remaining']} remaining)")
        return status

    def _load_query_cache(self) -> None:
        global QUERY_CACHE
        if not cfg.cache_enabled:
            QUERY_CACHE = {}
            return
        if not cfg.cache_persist_to_disk:
            QUERY_CACHE = {}
            return
        if not QUERY_CACHE_PATH.exists():
            QUERY_CACHE = {}
            return

        raw = json.loads(QUERY_CACHE_PATH.read_text(encoding="utf-8"))
        now = time.time()
        ttl_sec = max(int(cfg.cache_ttl_hours), 1) * 3600
        cache: dict[str, tuple[float, dict[str, Any]]] = {}
        for key, payload in raw.items():
            cached_at = float(payload.get("cached_at", 0))
            if now - cached_at < ttl_sec:
                cache[key] = (cached_at, payload.get("result", {}))

        QUERY_CACHE = cache
        self._evict_cache_if_needed()

    def _save_query_cache(self) -> None:
        if not cfg.cache_enabled or not cfg.cache_persist_to_disk:
            return
        serial = {key: {"cached_at": ts, "result": result} for key, (ts, result) in QUERY_CACHE.items()}
        QUERY_CACHE_PATH.write_text(json.dumps(serial, indent=2), encoding="utf-8")

    def _evict_cache_if_needed(self) -> None:
        max_entries = max(int(cfg.cache_max_entries), 0)
        if max_entries <= 0:
            QUERY_CACHE.clear()
            return
        if len(QUERY_CACHE) <= max_entries:
            return
        ordered = sorted(QUERY_CACHE.items(), key=lambda item: item[1][0])
        remove_count = len(QUERY_CACHE) - max_entries
        for idx in range(remove_count):
            QUERY_CACHE.pop(ordered[idx][0], None)

    def clear_cache(self) -> dict[str, Any]:
        QUERY_CACHE.clear()
        if QUERY_CACHE_PATH.exists():
            QUERY_CACHE_PATH.unlink()
        return {"entries": 0}

    def cache_entries(self) -> int:
        return len(QUERY_CACHE)

    def get_cache_key(self, query: str) -> str:
        words = sorted(re.sub(r"[^a-z0-9 ]", "", query.lower()).split())
        return " ".join(words[:8])

    def _get_cached_result(self, query: str) -> dict[str, Any] | None:
        if not cfg.cache_enabled:
            return None
        key = self.get_cache_key(query)
        hit = QUERY_CACHE.get(key)
        if not hit:
            return None
        cached_at, result = hit
        age_hours = (time.time() - cached_at) / 3600
        if age_hours >= max(int(cfg.cache_ttl_hours), 1):
            QUERY_CACHE.pop(key, None)
            self._save_query_cache()
            return None
        logger.log_cache(
            f"Cache HIT for query '{query[:50]}' (age: {age_hours:.1f}h, saved 1 compound call)"
        )
        return result

    def _set_cached_result(self, query: str, result: dict[str, Any]) -> None:
        if not cfg.cache_enabled:
            return
        QUERY_CACHE[self.get_cache_key(query)] = (time.time(), result)
        self._evict_cache_if_needed()
        self._save_query_cache()

    def _extract_sources(self, response: Any) -> list[dict[str, str]]:
        urls, method1 = extract_sources_from_response(response)
        logger.log_system(
            f"Sources extracted: {len(urls)} URLs (method: {'executed_tools' if method1 else 'text_parsing'})"
        )
        return [{"url": url, "query": ""} for url in urls]

    def _call_with_retry(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        log_prefix: str,
    ) -> dict[str, Any]:
        attempts = max(int(cfg.max_retries_on_429), 0) + 3
        last_exc: Exception | None = None

        current_system = system_prompt
        current_user = user_prompt
        current_model = model

        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=current_model,
                    messages=[
                        {"role": "system", "content": current_system},
                        {"role": "user", "content": current_user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                token_in = int(getattr(usage, "prompt_tokens", 0) or 0)
                token_out = int(getattr(usage, "completion_tokens", 0) or 0)
                return {
                    "text": text,
                    "sources": self._extract_sources(response),
                    "token_in": token_in,
                    "token_out": token_out,
                }
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)

                # 413 Request Too Large: truncate prompts and retry with fallback model
                if "413" in exc_str or "request_too_large" in exc_str.lower():
                    fallback = cfg.research_fallback_model
                    if current_model != fallback or len(current_system) > 600:
                        logger.log_warn(
                            f"413 too large for {log_prefix} "
                            f"(sys={len(current_system)}ch, user={len(current_user)}ch) "
                            f"- truncating and retrying with fallback model {fallback}"
                        )
                        current_system = current_system[:800]
                        current_user = current_user[:600]
                        current_model = fallback
                        continue
                    raise

                delay = parse_retry_delay(exc_str)
                if delay is None or attempt + 1 >= attempts:
                    raise
                wait_for = delay + float(cfg.retry_delay_buffer_seconds)
                logger.log_warn(
                    f"Rate limited for {log_prefix}; waiting {wait_for:.2f}s ({attempt + 1}/{attempts - 1} retries)"
                )
                time.sleep(wait_for)

        raise RuntimeError(f"Unexpected retry exhaustion for {log_prefix}: {last_exc}")

    def compound_research(
        self,
        *,
        agent_id: str,
        agent_spec: Any,
        target: str,
        user_context: str,
        session_id: str,
        phase: int,
        query: str,
        system_prompt: str,
        user_prompt: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if phase != 1:
            raise RuntimeError("groq/compound is restricted to Phase 1 only")
        if agent_id == "synthesis_judge":
            raise RuntimeError("groq/compound cannot be used by synthesis_judge")

        if force_refresh:
            key = self.get_cache_key(query)
            QUERY_CACHE.pop(key, None)
            logger.log_cache("Cache BYPASS (force_refresh=True) - making fresh compound call")
            cached = None
        else:
            cached = self._get_cached_result(query)

        if cached is not None:
            return {
                **cached,
                "cached": True,
                "compound_calls": 0,
                "search_queries": [query],
            }

        logger.log_cache("Cache MISS - making compound call")
        budget = self.get_budget_status()
        if budget["remaining"] <= 0:
            raise RuntimeError("No compound budget remaining for today")

        model = cfg.social_model if agent_id == "social_sentiment" else cfg.research_model
        max_tokens = int(cfg.social_max_tokens) if agent_id == "social_sentiment" else int(cfg.research_max_tokens)

        logger.log_compound(f"-> compound call: {agent_spec.name}")
        logger.log_compound(f"   query: '{query[:120]}'")
        result = self._call_with_retry(
            model=model,
            system_prompt=system_prompt,
            user_prompt=f"{user_prompt}\n\nContext: {user_context[: cfg.max_context_chars]}",
            max_tokens=max_tokens,
            temperature=float(cfg.research_temperature),
            log_prefix=f"compound:{agent_id}",
        )

        logger.log_compound(
            f"<- Success: {len(result['text'])} chars | {len(result['sources'])} sources | "
            f"{result['token_in']}in/{result['token_out']}out tokens"
        )

        self._increment_budget(session_id=session_id, target=target, calls=1)

        payload = {
            "findings": result["text"],
            "sources": result["sources"],
            "tokens": {"in": result["token_in"], "out": result["token_out"]},
            "agent_id": agent_id,
        }
        self._set_cached_result(query, payload)

        return {
            "findings": result["text"],
            "sources": result["sources"],
            "search_queries": [query],
            "tokens": {"in": result["token_in"], "out": result["token_out"]},
            "cached": False,
            "compound_calls": 1,
        }

    def instant_analysis(
        self,
        *,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        session_id: str,
    ) -> dict[str, Any]:
        if purpose == "cross_examination":
            model = cfg.cross_exam_model
            max_tokens = int(cfg.cross_exam_max_tokens)
            temperature = float(cfg.cross_exam_temperature)
        elif purpose == "synthesis":
            model = cfg.synthesis_model
            max_tokens = int(cfg.synthesis_max_tokens)
            temperature = float(cfg.synthesis_temperature)
        elif purpose == "chat":
            model = cfg.synthesis_model
            max_tokens = 1024
            temperature = 0.4
        else:
            model = cfg.synthesis_model
            max_tokens = int(cfg.connection_test_max_tokens)
            temperature = float(cfg.synthesis_temperature)

        logger.log_instant(f"-> instant call: {purpose} | session:{session_id}")
        result = self._call_with_retry(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            log_prefix=f"instant:{purpose}",
        )
        logger.log_instant(
            f"<- Success: {len(result['text'])} chars | {result['token_in']}in/{result['token_out']}out tokens"
        )
        return result

    def test_model(self, model_name: str) -> tuple[bool, str]:
        try:
            self._call_with_retry(
                model=model_name,
                system_prompt="Return: ok",
                user_prompt="ok",
                max_tokens=int(cfg.connection_test_max_tokens),
                temperature=float(cfg.synthesis_temperature),
                log_prefix=f"test:{model_name}",
            )
            return True, "ok"
        except Exception as exc:
            return False, str(exc)

    def test_models(self) -> dict[str, Any]:
        compound_ok, compound_err = self.test_model(cfg.research_model)
        instant_ok, instant_err = self.test_model(cfg.synthesis_model)
        cross_ok, cross_err = self.test_model(cfg.cross_exam_model)
        social_ok, social_err = self.test_model(cfg.social_model)
        return {
            "research": {"model": cfg.research_model, "ok": compound_ok, "error": compound_err if not compound_ok else ""},
            "synthesis": {"model": cfg.synthesis_model, "ok": instant_ok, "error": instant_err if not instant_ok else ""},
            "cross_exam": {"model": cfg.cross_exam_model, "ok": cross_ok, "error": cross_err if not cross_ok else ""},
            "social": {"model": cfg.social_model, "ok": social_ok, "error": social_err if not social_ok else ""},
        }

    def get_provider_status(self) -> dict[str, Any]:
        budget = self.get_budget_status()
        if self.api_key_set():
            compound_ok, _ = self.test_model(cfg.research_model)
            instant_ok, _ = self.test_model(cfg.synthesis_model)
        else:
            compound_ok = False
            instant_ok = False
        return {
            "groq_key_set": self.api_key_set(),
            "compound_available": compound_ok,
            "instant_available": instant_ok,
            "budget_today": budget["used"],
            "budget_remaining": budget["remaining"],
            "budget_pct": round((budget["used"] / budget["limit"]) * 100, 2) if budget["limit"] else 0,
            "groq_key_masked": self.api_key_masked(),
        }


def parse_retry_delay(error_text: str) -> float | None:
    min_delay = 1e-1
    patterns = [
        r"try again in\s*([0-9]+(?:\.[0-9]+)?)\s*s",
        r"retry after\s*([0-9]+(?:\.[0-9]+)?)\s*s",
        r"in\s*([0-9]+(?:\.[0-9]+)?)\s*seconds",
        r"in\s*([0-9]+)\s*ms",
    ]
    lower = error_text.lower()
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            value = float(match.group(1))
            if "ms" in pattern:
                return max(value / 1000.0, min_delay)
            return max(value, min_delay)
    return None