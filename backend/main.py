from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import asyncio
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import list_research_agents, refresh_depth_config
from .config import cfg, get_config_dict, reset_config, save_config
from .groq_client import GroqClient
from .logger import logger
from .memo import derive_subscores_from_agents, enforce_score_scale, memo_to_html, memo_to_markdown, memo_to_pdf
from .research import ResearchManager, depth_card_data
from .session import RESEARCH_DIR, delete_session, list_sessions, load_session, save_session
from .technical import validate_target

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

load_dotenv(ROOT / ".env")

app = FastAPI(title="AlphaSwarm", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    groq_client = GroqClient()
    manager = ResearchManager(groq=groq_client)
except Exception as exc:
    logger.log_error(f"Groq client initialization failed: {exc}")
    groq_client = None
    manager = None


def _backfill_memo_scores(data: dict[str, Any]) -> dict[str, Any]:
    memo = data.get("memo") or {}
    if not memo:
        return data
    subs = memo.get("subscores") if isinstance(memo.get("subscores"), dict) else {}
    required = [
        "financial_health",
        "growth_quality",
        "competitive_position",
        "management_quality",
        "risk_profile",
        "innovation_signal",
        "revenue_quality",
    ]
    missing = any(not isinstance(subs.get(k), (int, float)) or float(subs.get(k)) <= 0 for k in required)
    if not missing:
        return data

    memo = derive_subscores_from_agents(memo, data.get("agent_results") or {})
    memo = enforce_score_scale(memo)
    data["memo"] = memo
    try:
        save_session(data)
    except Exception:
        pass
    return data


class StartResearchRequest(BaseModel):
    target: str = Field(min_length=1)
    depth: str = "standard"
    focus: str = "all-around"
    specific_questions: str = ""
    context: str = ""
    agent_ids: list[str] = []
    force_refresh: bool = False


@app.on_event("startup")
async def startup() -> None:
    budget_used_today = 0
    if groq_client:
        budget_used_today = groq_client.get_budget_status().get("used", 0)

    logger.log_system(f"AlphaSwarm starting on port {cfg.port}")
    logger.log_system("Config loaded from alphaswarm_config.json")
    logger.log_config("-- AI Models --")
    logger.log_config(f"Research:      {cfg.research_model} (max {cfg.research_max_tokens} tokens, temp {cfg.research_temperature})")
    logger.log_config(f"Synthesis:     {cfg.synthesis_model} (max {cfg.synthesis_max_tokens} tokens, temp {cfg.synthesis_temperature})")
    logger.log_config(f"Cross-Exam:    {cfg.cross_exam_model} (max {cfg.cross_exam_max_tokens} tokens, temp {cfg.cross_exam_temperature})")
    logger.log_config(f"Social:        {cfg.social_model} (max {cfg.social_max_tokens} tokens)")
    logger.log_config("-- Research --")
    logger.log_config(f"Default depth: {cfg.default_depth}")
    logger.log_config(f"Cross-exam:    {'enabled' if cfg.phase2_cross_exam_enabled else 'disabled'} max {cfg.max_cross_exam_pairs} pairs")
    logger.log_config(f"Cache:         {'enabled' if cfg.cache_enabled else 'disabled'} TTL {cfg.cache_ttl_hours}h")
    logger.log_config(f"Technical:     {'enabled' if cfg.phase_technical_enabled else 'disabled'} (Phase 4, free)")
    logger.log_config("-- Budget --")
    logger.log_config(f"Daily limit:   {cfg.daily_compound_limit}")
    logger.log_config(f"Warning at:    {cfg.budget_warning_threshold} remaining")
    logger.log_config(f"Hard floor:    {cfg.budget_hard_floor}")
    logger.log_config(f"Today used:    {budget_used_today}")
    logger.log_system(f"Groq API key: {groq_client.api_key_masked() if groq_client else 'missing'}")
    logger.log_system("Ready.")


@app.middleware("http")
async def api_log_middleware(request: Request, call_next):
    response = await call_next(request)
    logger.log_api(f"{request.method} {request.url.path} -> {response.status_code}")
    return response


@app.get("/api/meta")
async def meta() -> dict[str, Any]:
    refresh_depth_config()
    budget = (
        groq_client.get_budget_status()
        if groq_client
        else {"used": 0, "limit": cfg.daily_compound_limit, "remaining": cfg.daily_compound_limit}
    )
    return {
        "depth_config": depth_card_data(),
        "agents": [asdict(a) for a in list_research_agents()],
        "budget": budget,
        "settings": get_config_dict(),
    }


@app.get("/api/budget")
async def budget() -> dict[str, Any]:
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    return groq_client.get_budget_status()


@app.post("/api/budget/reset")
async def budget_reset() -> dict[str, Any]:
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    return groq_client.reset_budget_today()


@app.post("/api/research/start")
async def start_research(payload: StartResearchRequest) -> dict[str, Any]:
    if manager is None:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    result = await manager.start_session(payload.model_dump())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/target/validate")
async def validate_research_target(target: str) -> dict[str, Any]:
    if not target.strip():
        raise HTTPException(status_code=400, detail="Target is required")
    return await asyncio.to_thread(validate_target, target)


@app.get("/api/research/{session_id}/status")
async def research_status(session_id: str) -> dict[str, Any]:
    if manager is None:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    status = await manager.get_status(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
    return manager.status_response(status)


@app.post("/api/research/{session_id}/proceed")
async def research_proceed(session_id: str) -> dict[str, Any]:
    if manager is None:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    result = await manager.proceed(session_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unable to proceed"))
    return result


@app.get("/api/research/{session_id}/memo")
async def research_memo(session_id: str) -> dict[str, Any]:
    data = await history_item(session_id)
    if not data.get("memo"):
        raise HTTPException(status_code=409, detail="Memo not ready")
    return data


# ── Technical chart data endpoint ─────────────────────────────────────────────
@app.get("/api/research/{session_id}/technical")
async def get_technical_data(session_id: str) -> dict[str, Any]:
    """
    Returns the full technical analysis result including OHLCV chart data
    and computed indicators. Kept separate from /status to avoid bloating
    the 2-second polling response (chart_data is 200-500KB for 1yr daily).
    """
    data = None
    if manager is not None:
        data = await manager.get_status(session_id)
    if not data:
        data = load_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")

    ta = data.get("technical_analysis")
    if not ta:
        raise HTTPException(status_code=409, detail="Technical analysis not yet complete")

    return {
        "session_id": session_id,
        "ticker": ta.get("ticker"),
        "is_public": ta.get("is_public", False),
        "technical_score": ta.get("technical_score", 5.0),
        "technical_direction": ta.get("technical_direction", "NEUTRAL"),
        "signals": ta.get("signals", []),
        "patterns": ta.get("patterns", []),
        "support_resistance": ta.get("support_resistance", {}),
        "findings": ta.get("findings", ""),
        "chart_data": ta.get("chart_data"),
        "error": ta.get("error"),
        "analyzed_at": ta.get("analyzed_at"),
    }


@app.get("/api/history")
async def history() -> list[dict[str, Any]]:
    return list_sessions()


@app.get("/api/history/{session_id}")
async def history_item(session_id: str) -> dict[str, Any]:
    if manager is not None:
        live = await manager.get_status(session_id)
        if live:
            return _backfill_memo_scores(live)
    data = load_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return _backfill_memo_scores(data)


@app.delete("/api/history/{session_id}")
async def history_delete(session_id: str) -> dict[str, bool]:
    if manager and session_id in manager.sessions:
        del manager.sessions[session_id]
    return {"deleted": delete_session(session_id)}


@app.get("/api/research/{session_id}/export/pdf")
async def export_pdf(session_id: str):
    data = None
    if manager is not None:
        data = await manager.get_status(session_id)
    if not data:
        data = load_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    if not data.get("memo"):
        raise HTTPException(status_code=409, detail="Research not yet complete")
    out_path = RESEARCH_DIR / f"{session_id}.pdf"
    try:
        await asyncio.to_thread(memo_to_pdf, data, str(out_path))
    except Exception as exc:
        logger.log_error(f"PDF export failed: {exc}")
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc
    target = (data.get("target") or session_id).replace(" ", "_")
    return FileResponse(
        str(out_path),
        media_type="application/pdf",
        filename=f"AlphaSwarm_{target}_research.pdf",
    )


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    settings = get_config_dict()
    readonly = {
        "groq_key_set": bool(groq_client and groq_client.api_key_set()),
        "compound_model_available": bool(groq_client and groq_client.test_model(cfg.research_model)[0]),
        "budget_today": groq_client.get_budget_status()["used"] if groq_client else 0,
        "budget_remaining": groq_client.get_budget_status()["remaining"] if groq_client else 0,
        "cache_entries": groq_client.cache_entries() if groq_client else 0,
        "groq_key_masked": groq_client.api_key_masked() if groq_client else "missing",
    }
    settings["_readonly"] = readonly
    return settings


@app.post("/api/settings")
async def set_settings(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    updates = {k: v for k, v in payload.items() if k in get_config_dict()}
    save_config(updates)
    refresh_depth_config()
    logger.log_system(f"[CONFIG] Updated {len(updates)} settings")
    return get_config_dict()


@app.post("/api/settings/reset")
async def reset_settings() -> dict[str, Any]:
    reset_config()
    refresh_depth_config()
    logger.log_system("[CONFIG] Reset to defaults")
    return get_config_dict()


@app.get("/api/provider-status")
async def provider_status() -> dict[str, Any]:
    if not groq_client:
        return {
            "groq_key_set": False,
            "compound_available": False,
            "instant_available": False,
            "budget_today": 0,
            "budget_remaining": 0,
            "budget_pct": 0.0,
        }
    status = groq_client.get_provider_status()
    return {
        "groq_key_set": status["groq_key_set"],
        "compound_available": status["compound_available"],
        "instant_available": status["instant_available"],
        "budget_today": status["budget_today"],
        "budget_remaining": status["budget_remaining"],
        "budget_pct": status["budget_pct"],
    }


@app.get("/api/ai/test")
async def test_ai() -> dict[str, Any]:
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    return groq_client.test_models()


@app.post("/api/cache/clear")
async def clear_cache() -> dict[str, Any]:
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq client not configured")
    result = groq_client.clear_cache()
    return {"ok": True, "entries": result["entries"]}


class ChatRequest(BaseModel):
    session_id: str
    messages: list[dict] = []
    system_prompt: str = ""


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    if manager is None or groq_client is None:
        raise HTTPException(status_code=500, detail="Groq client not configured")

    history_lines = []
    for msg in payload.messages[:-1]:
        role = "User" if msg["role"] == "user" else "Analyst"
        history_lines.append(f"{role}: {msg['content']}")

    last_user = next(
        (m["content"] for m in reversed(payload.messages) if m["role"] == "user"), ""
    )

    user_prompt = ""
    if history_lines:
        user_prompt += "CONVERSATION HISTORY:\n" + "\n".join(history_lines) + "\n\n"
    user_prompt += f"USER QUESTION: {last_user}"

    try:
        result = await asyncio.to_thread(
            groq_client.instant_analysis,
            purpose="chat",
            system_prompt=payload.system_prompt,
            user_prompt=user_prompt,
            session_id=payload.session_id,
        )
        return {"reply": result["text"], "ok": True}
    except Exception as exc:
        logger.log_error(f"Chat endpoint error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/{path:path}")
async def spa_fallback(path: str):
    target = FRONTEND_DIR / path
    if target.exists() and target.is_file():
        return FileResponse(str(target))
    return JSONResponse({"detail": "Not Found"}, status_code=404)
