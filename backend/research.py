from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .agents import (
    build_cross_exam_prompts,
    build_research_prompts,
    get_agent,
    get_depth_required_calls,
    get_relevant_pairs,
    refresh_depth_config,
    resolve_agent_ids,
)
from .config import cfg
from .groq_client import GroqClient
from .hallucination_guard import (
    prepare_findings_for_synthesis,
    scan_for_hallucination_risk,
    validate_memo,
)
from .logger import logger
from .memo import (
    apply_depth_metadata,
    build_research_mode_memo,
    cap_investment_action,
    derive_subscores_from_agents,
    enforce_bear_thesis,
    enforce_score_scale,
    extract_financial_snapshot,
    parse_memo_json,
    synthesis_prompt,
    truncate_findings,
    validate_valuation_verdict,
)
from .session import load_session, save_session
from .technical import run_technical_analysis, validate_target

PHASE_NAMES = {0: "Pending", 1: "Research", 2: "Technical Analysis", 3: "Cross-Examination", 4: "Synthesis", 5: "Complete"}


def _infer_industry(target: str) -> str:
    tokens = (target or "").split()
    if len(tokens) <= 1:
        return "sector"
    return tokens[-1]


def _classify_direction(text: str) -> str:
    t = (text or "").lower()
    pos = sum(k in t for k in ["upside", "growth", "strong", "improving", "bull", "positive"])
    neg = sum(k in t for k in ["downside", "risk", "weak", "deteriorating", "bear", "negative"])
    if pos > neg:
        return "BULLISH"
    if neg > pos:
        return "BEARISH"
    return "NEUTRAL"


def _compute_majority(agent_results: dict[str, Any]) -> tuple[str, str, int, int, int]:
    pos = neg = neu = 0
    weights = {"financial": 2, "bear": 2, "bull": 2, "competitive": 1, "regulatory": 1, "growth": 1}
    weighted_score = 0
    for aid, result in agent_results.items():
        if result.get("status") != "complete":
            continue
        direction = _classify_direction(result.get("findings", ""))
        w = weights.get(aid, 1)
        if direction == "BULLISH":
            pos += 1
            weighted_score += w
        elif direction == "BEARISH":
            neg += 1
            weighted_score -= w
        else:
            neu += 1

    raw = "BULLISH" if pos > neg else "BEARISH" if neg > pos else "NEUTRAL"
    weighted = "BULLISH" if weighted_score > 0 else "BEARISH" if weighted_score < 0 else "NEUTRAL"
    return raw, weighted, pos, neg, neu


def _rank_value(value: str, ordering: list[str]) -> int:
    upper = (value or "").upper()
    if upper in ordering:
        return ordering.index(upper)
    return -1


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"[`*_>#-]", "", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_ta_narrative(ta: dict[str, Any]) -> str:
    if not ta or not ta.get("is_public") or ta.get("error"):
        return ""
    ticker = ta.get("ticker") or "the stock"
    direction = str(ta.get("technical_direction") or "NEUTRAL").upper()
    score = ta.get("technical_score", 5.0)
    signals = ta.get("signals") or []
    bullish = sum(1 for s in signals if s.get("type") == "bullish")
    bearish = sum(1 for s in signals if s.get("type") == "bearish")
    strong = [s for s in signals if s.get("strength") == "strong"]

    trend_bias = "mixed" if bullish == bearish else "bullish" if bullish > bearish else "bearish"
    lead_signal = strong[0]["signal"] if strong else (signals[0]["signal"] if signals else "no dominant signal")
    rsi_signal = next((s.get("signal") for s in signals if "rsi" in (s.get("signal", "").lower())), "RSI inconclusive")
    macd_signal = next((s.get("signal") for s in signals if "macd" in (s.get("signal", "").lower())), "MACD inconclusive")

    return (
        f"Technical analysis for {ticker} is {direction.lower()} ({score}/10) with a {trend_bias} signal balance "
        f"({bullish} bullish vs {bearish} bearish signals). "
        f"The leading chart signal is {lead_signal}. "
        f"Momentum context: {rsi_signal}; {macd_signal}. "
        "Use this as a timing/risk overlay on the fundamental thesis rather than a standalone investment case."
    )


def _extract_social_signal(findings: str) -> dict[str, Any]:
    text = findings or ""

    def pick(options: list[str], default: str) -> str:
        upper = text.upper()
        for opt in options:
            if opt in upper:
                return opt
        return default

    buzz_level = pick(["HIGH", "MEDIUM", "LOW", "MINIMAL"], "MINIMAL")
    buzz_trend = pick(["RISING", "STABLE", "FALLING"], "STABLE")
    retail_direction = pick(["BULLISH", "BEARISH", "MIXED", "NEUTRAL"], "NEUTRAL")
    intensity = pick(["EXTREME", "STRONG", "MODERATE", "MILD"], "MILD")
    market_impact = pick(["AMPLIFYING", "MODERATE", "MINOR"], "MINOR")
    meme_risk = pick(["POSSIBLE", "YES", "NO"], "NO")
    short_squeeze_risk = pick(["POSSIBLE", "YES", "NO"], "NO")

    max_adj = float(cfg.social_max_score_adjustment)
    medium_adj = round(max_adj * 0.4, 2)
    adjustment = 0.0
    if buzz_level == "HIGH" and market_impact == "AMPLIFYING":
        adjustment = max_adj if retail_direction == "BULLISH" else -max_adj if retail_direction == "BEARISH" else 0.0
    elif buzz_level == "MEDIUM":
        adjustment = medium_adj if retail_direction == "BULLISH" else -medium_adj if retail_direction == "BEARISH" else 0.0

    return {
        "buzz_level": buzz_level,
        "buzz_trend": buzz_trend,
        "retail_direction": retail_direction,
        "intensity": intensity,
        "market_impact": market_impact,
        "meme_risk": meme_risk,
        "short_squeeze_risk": short_squeeze_risk,
        "influenced_verdict": False,
        "social_note": "Social signal is secondary; fundamentals remain primary.",
        "score_adjustment": adjustment,
    }


class ResearchManager:
    def __init__(self, groq: GroqClient) -> None:
        self.groq = groq
        self.sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def _push_event(self, session_id: str, kind: str, message: str) -> None:
        session = await self.get_status(session_id)
        if not session:
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "message": message,
        }
        session.setdefault("event_log", []).append(event)
        if len(session["event_log"]) > 400:
            session["event_log"] = session["event_log"][-400:]

    def _should_run_phase_2(self, depth: str, agent_ids: list[str]) -> bool:
        if not cfg.phase2_cross_exam_enabled:
            return False
        if depth == "quick" and cfg.skip_cross_exam_for_quick:
            return False
        return len(get_relevant_pairs(agent_ids, depth)) > 0

    async def _wait_for_user_proceed(self, session_id: str, next_phase: int, phase_name: str) -> None:
        session = await self.get_status(session_id)
        if not session:
            return
        session["status"] = "waiting_for_user"
        session["awaiting_user_phase"] = next_phase
        session["awaiting_user_message"] = f"Phase complete. Click proceed to start {phase_name}."
        await self._push_event(
            session_id,
            "phase",
            f"Awaiting user action to start Phase {next_phase}: {phase_name}",
        )
        await self._save(session_id)

        while True:
            await asyncio.sleep(0.4)
            session = await self.get_status(session_id)
            if not session:
                return
            if session.get("awaiting_user_phase") is None:
                break
            if session.get("status") == "error":
                return

    async def _mark_phase_cross_exam_skipped(self, session_id: str, reason: str) -> None:
        session = await self.get_status(session_id)
        if not session:
            return
        session["phase"] = 2
        session["phase_name"] = PHASE_NAMES[2]
        session["cross_exam_notes"] = [{"skipped": True, "reason": reason}]
        await self._push_event(session_id, "phase", f"Phase 3 (Cross-Exam) skipped: {reason}")
        await self._save(session_id)

    async def proceed(self, session_id: str) -> dict[str, Any]:
        session = await self.get_status(session_id)
        if not session:
            return {"ok": False, "error": "Session not found"}
        if session.get("awaiting_user_phase") is None:
            return {"ok": False, "error": "Session is not waiting for user action"}
        next_phase = session.get("awaiting_user_phase")
        session["awaiting_user_phase"] = None
        session["awaiting_user_message"] = ""
        session["status"] = "running"
        await self._push_event(session_id, "phase", f"User proceeded to Phase {next_phase}")
        await self._save(session_id)
        return {"ok": True, "next_phase": next_phase}

    async def get_status(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            if session_id in self.sessions:
                return self.sessions[session_id]
        data = load_session(session_id)
        if data:
            async with self._lock:
                self.sessions[session_id] = data
        return data

    def _make_agent_state(self, agent_id: str) -> dict[str, Any]:
        spec = get_agent(agent_id)
        return {
            "agent_id": agent_id,
            "name": spec.name,
            "icon": spec.icon,
            "status": "pending",
            "findings": "",
            "findings_preview": "",
            "search_queries": [],
            "sources": [],
            "tokens_used": 0,
            "compound_calls": 0,
            "searches_total": int(spec.compound_searches),
            "error": None,
        }

    async def _generate_session_id(self) -> str:
        for _ in range(32):
            epoch_ms_hex = format(int(datetime.now(timezone.utc).timestamp() * 1000), "x")
            candidate = f"{epoch_ms_hex}-{uuid.uuid4().hex}"
            async with self._lock:
                live_exists = candidate in self.sessions
            if live_exists:
                continue
            if load_session(candidate):
                continue
            return candidate
        return f"fallback-{uuid.uuid4().hex}-{uuid.uuid4().hex}"

    async def start_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        refresh_depth_config()
        depth = (payload.get("depth") or cfg.default_depth).lower()
        mode = (payload.get("mode") or cfg.default_mode or "standard").lower()
        if mode not in {"standard", "research"}:
            mode = "standard"
        custom_agent_ids = payload.get("agent_ids") or []
        force_refresh = bool(payload.get("force_refresh", False))
        agent_ids = resolve_agent_ids(depth, custom_agent_ids)
        required_calls = get_depth_required_calls(depth, custom_agent_ids) if cfg.phase1_enabled else 0
        target = payload.get("target", "")
        target_validation = await asyncio.to_thread(validate_target, target)
        if not target_validation.get("is_valid"):
            return {"error": target_validation.get("reason", "Invalid target")}

        ok, reason = self.groq.ensure_budget_for_run(required_calls=required_calls)
        if not ok:
            return {"error": reason, "required": required_calls, "budget": self.groq.get_budget_status()}

        session_id = await self._generate_session_id()
        session = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "target": target,
            "depth": depth,
            "mode": mode,
            "context": (payload.get("context") or "")[: cfg.max_context_chars],
            "specific_questions": payload.get("specific_questions") or "",
            "status": "running",
            "phase": 0,
            "phase_name": PHASE_NAMES[0],
            "agent_ids": agent_ids,
            "agents_total": len(agent_ids),
            "agents_complete": 0,
            "agent_results": {aid: self._make_agent_state(aid) for aid in agent_ids},
            "cross_exam_notes": [],
            "memo": None,
            # Technical analysis results stored separately from agent_results
            "technical_analysis": None,
            "budget_used": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "required_compound_calls": required_calls,
            "budget_snapshot_start": self.groq.get_budget_status(),
            "error": None,
            "awaiting_user_phase": None,
            "awaiting_user_message": "",
            "event_log": [],
            "target_validation": target_validation,
        }

        async with self._lock:
            self.sessions[session_id] = session
        save_session(session)
        await self._push_event(
            session_id,
            "research",
            f"Started research for '{target}' with {len(agent_ids)} agents ({depth} depth).",
        )

        logger.log_phase(f"━━━ Phase 1: Research | Target: {target} | {len(agent_ids)} agents ━━━")
        asyncio.create_task(self.run_research(session_id, target, depth, session["context"], agent_ids, force_refresh=force_refresh))
        return {"session_id": session_id, "required_compound_calls": required_calls}

    async def _save(self, session_id: str) -> None:
        session = await self.get_status(session_id)
        if session:
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_session(session)

    async def run_research(
        self,
        session_id: str,
        target: str,
        depth: str,
        context: str,
        agent_ids: list[str],
        force_refresh: bool = False,
    ) -> None:
        try:
            session = await self.get_status(session_id)
            target_validation = (session or {}).get("target_validation", {})
            if not target_validation:
                target_validation = await asyncio.to_thread(validate_target, target)
                if session is not None:
                    session["target_validation"] = target_validation
                    await self._save(session_id)
            # ── Phase 1: Research agents ──────────────────────────────────────
            if cfg.phase1_enabled:
                await self._run_phase_1(session_id, target, depth, context, agent_ids, force_refresh=force_refresh)

            # ── Phase 2: Technical Analysis (free, no API calls) ─────────────
            # Runs BEFORE cross-exam and synthesis so TA data feeds into both.
            if cfg.phase_technical_enabled and target_validation.get("is_public", False):
                await self._run_phase_technical(session_id, target)
            elif cfg.phase_technical_enabled and target_validation.get("is_private", False):
                session = await self.get_status(session_id)
                if session:
                    session["technical_analysis"] = {
                        "ticker": None,
                        "is_public": False,
                        "technical_score": 5.0,
                        "technical_direction": "NEUTRAL",
                        "signals": [],
                        "patterns": [],
                        "support_resistance": {},
                        "findings": (
                            "## TECHNICAL_ANALYSIS\n"
                            f"- Status: SKIPPED — '{target}' identified as private company.\n"
                            "- Technical analysis requires exchange-listed securities with market data."
                        ),
                        "chart_data": None,
                        "error": "private_company",
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await self._push_event(
                        session_id,
                        "phase",
                        "Technical Analysis skipped: private company target.",
                    )
                    await self._save(session_id)

            # ── Phase 3: Cross-Examination ────────────────────────────────────
            should_run_phase3 = self._should_run_phase_2(depth, agent_ids)
            if should_run_phase3:
                await self._wait_for_user_proceed(session_id, 3, "Cross-Examination")
                await self._run_phase_cross_exam(session_id, depth, agent_ids)
            else:
                await self._mark_phase_cross_exam_skipped(
                    session_id,
                    "Cross-examination not run for this depth/config. Proceed to synthesis.",
                )

            # ── Phase 4: Synthesis ────────────────────────────────────────────
            if cfg.phase3_synthesis_enabled:
                await self._wait_for_user_proceed(session_id, 4, "Synthesis")
                await self._run_phase_synthesis(session_id, target, depth, agent_ids)
            else:
                session = await self.get_status(session_id)
                if session:
                    session["memo"] = {
                        "verdict": "NEUTRAL",
                        "confidence": "LOW",
                        "summary": "Phase 4 synthesis is disabled in Settings.",
                    }

            session = await self.get_status(session_id)
            if session:
                session["status"] = "complete"
                session["phase"] = 5
                session["phase_name"] = PHASE_NAMES[5]
                session["budget_snapshot_end"] = self.groq.get_budget_status()
                await self._save(session_id)
                await self._push_event(
                    session_id,
                    "research",
                    f"Research complete for '{target}'.",
                )
                logger.log_system(
                    f"Research complete | {target} | session:{session_id} | {session['budget_used']} calls used"
                )
        except Exception as exc:
            logger.log_error(f"Session {session_id} crashed: {exc}")
            session = await self.get_status(session_id)
            if session:
                session["status"] = "error"
                session["error"] = str(exc)
                await self._save(session_id)

    async def _run_phase_1(self, session_id: str, target: str, depth: str, context: str, agent_ids: list[str], force_refresh: bool = False) -> None:
        del depth
        session = await self.get_status(session_id)
        if not session:
            return

        session["phase"] = 1
        session["phase_name"] = PHASE_NAMES[1]
        await self._save(session_id)
        await self._push_event(session_id, "phase", "Phase 1 started: Independent Research")

        industry = _infer_industry(target)

        for aid in agent_ids:
            spec = get_agent(aid)
            state = session["agent_results"][aid]
            state["status"] = "searching"
            logger.log_agent(f"{spec.name}: starting research")
            await self._push_event(session_id, "agent", f"{spec.name}: searching")

            system_prompt, user_prompt, query = build_research_prompts(
                target=target,
                industry=industry,
                agent=spec,
                specific_questions=session.get("specific_questions", ""),
                context=context,
            )

            state["search_queries"] = [query]
            await self._save(session_id)

            try:
                result = await asyncio.to_thread(
                    self.groq.compound_research,
                    agent_id=aid,
                    agent_spec=spec,
                    target=target,
                    user_context=context,
                    session_id=session_id,
                    phase=1,
                    query=query,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    force_refresh=force_refresh,
                )
                state["status"] = "running"
                await self._save(session_id)
                state.update(
                    {
                        "status": "complete",
                        "findings": result["findings"],
                        "findings_preview": result["findings"][:260],
                        "sources": result["sources"],
                        "tokens_used": result["tokens"]["in"] + result["tokens"]["out"],
                        "compound_calls": result["compound_calls"],
                    }
                )
                state["hallucination_check"] = scan_for_hallucination_risk(
                    findings=state["findings"],
                    sources=state["sources"],
                    agent_name=spec.name,
                )
                session["budget_used"] += int(result["compound_calls"])
                session["total_tokens_in"] += int(result["tokens"]["in"])
                session["total_tokens_out"] += int(result["tokens"]["out"])
                logger.log_agent(
                    f"{spec.name}: complete | {len(result['sources'])} sources | finding: {result['findings'][:70]}"
                )
                await self._push_event(
                    session_id,
                    "ai",
                    f"{spec.name}: complete ({len(result['sources'])} sources, {result['tokens']['in']}in/{result['tokens']['out']}out tokens)",
                )
            except Exception as exc:
                state.update({"status": "error", "error": str(exc)})
                logger.log_warn(f"{spec.name} failed: {exc}")
                await self._push_event(session_id, "warn", f"{spec.name}: error - {exc}")
                if not cfg.continue_on_agent_failure:
                    raise RuntimeError(f"Agent failure with continue_on_agent_failure disabled: {spec.name}") from exc

            session["agents_complete"] = sum(
                1 for a in session["agent_results"].values() if a.get("status") in {"complete", "error"}
            )
            await self._save(session_id)

        total_sources = sum(len(s.get("sources", [])) for s in session["agent_results"].values())
        logger.log_phase(
            f"✓ Phase 1 complete | {len(agent_ids)} agents | {session['budget_used']} calls | {total_sources} sources"
        )
        await self._push_event(
            session_id,
            "phase",
            f"Phase 1 complete: {len(agent_ids)} agents, {session['budget_used']} calls, {total_sources} sources",
        )

    async def _run_phase_cross_exam(self, session_id: str, depth: str, agent_ids: list[str]) -> None:
        session = await self.get_status(session_id)
        if not session:
            return

        if depth == "quick" and cfg.skip_cross_exam_for_quick:
            session["cross_exam_notes"] = [
                {
                    "skipped": True,
                    "reason": (
                        "Cross-examination skipped for Quick depth (cfg.skip_cross_exam_for_quick=True). "
                        "Run Standard or Deep depth to enable agent cross-verification."
                    ),
                }
            ]
            return

        pairs = get_relevant_pairs(agent_ids, depth)
        if not pairs:
            session["cross_exam_notes"] = [
                {
                    "skipped": True,
                    "reason": "No relevant cross-examination pairs available for this run.",
                }
            ]
            return

        session["phase"] = 3
        session["phase_name"] = PHASE_NAMES[3]
        await self._save(session_id)
        await self._push_event(session_id, "phase", f"Phase 3 started: Cross-Examination ({len(pairs)} pairs)")
        logger.log_phase(f"━━━ Phase 3: Cross-Examination | {len(pairs)} pairs ━━━")

        for a_id, b_id in pairs:
            a_state = session["agent_results"].get(a_id, {})
            b_state = session["agent_results"].get(b_id, {})
            a_find = truncate_findings(a_state.get("findings", ""), 800)
            b_find = truncate_findings(b_state.get("findings", ""), 800)
            system_prompt, user_prompt = build_cross_exam_prompts(
                agent_a_name=a_state.get("name", a_id),
                agent_b_name=b_state.get("name", b_id),
                agent_a_findings=a_find,
                agent_b_findings=b_find,
            )
            try:
                result = await asyncio.to_thread(
                    self.groq.instant_analysis,
                    purpose="cross_examination",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    session_id=session_id,
                )
                note = {"agent_a": a_id, "agent_b": b_id, "note": result["text"][: cfg.max_cross_exam_chars]}
                session["cross_exam_notes"].append(note)
                session["total_tokens_in"] += int(result["token_in"])
                session["total_tokens_out"] += int(result["token_out"])
                await self._push_event(
                    session_id,
                    "ai",
                    f"Cross-exam: {a_id} x {b_id} complete",
                )
            except Exception as exc:
                logger.log_warn(f"Cross exam failed ({a_id} x {b_id}): {exc}")
                await self._push_event(session_id, "warn", f"Cross-exam failed ({a_id} x {b_id}): {exc}")
            await self._save(session_id)

        logger.log_phase(f"✓ Phase 3 complete | {len(session['cross_exam_notes'])} pairs")
        await self._push_event(
            session_id,
            "phase",
            f"Phase 3 complete: {len(session['cross_exam_notes'])} notes",
        )

    async def _run_phase_synthesis(self, session_id: str, target: str, depth: str, agent_ids: list[str]) -> None:
        session = await self.get_status(session_id)
        if not session:
            return
        mode = (session.get("mode") or "standard").lower()

        session["phase"] = 4
        session["phase_name"] = PHASE_NAMES[4]
        await self._save(session_id)
        await self._push_event(session_id, "phase", "Phase 4 started: Synthesis")
        logger.log_phase("━━━ Phase 4: Synthesis ━━━")

        raw_findings_by_agent = {
            aid: result.get("findings", "")
            for aid, result in session["agent_results"].items()
            if result.get("status") == "complete"
        }
        findings_by_agent = prepare_findings_for_synthesis(
            {aid: session["agent_results"][aid] for aid in raw_findings_by_agent.keys()}
        )
        if cfg.strip_markdown_for_synthesis:
            findings_by_agent = {aid: _strip_markdown(text) for aid, text in findings_by_agent.items()}

        # ── Scale per-agent char budget by agent count to stay under token limit ──
        # Target: ~10,000 chars total. Deep(18)→~500/agent, Standard(10)→~900, Quick(3)→1200
        n_agents = max(len(findings_by_agent), 1)
        per_agent_chars = min(cfg.max_findings_chars_synthesis, max(400, 10000 // n_agents))
        if per_agent_chars < cfg.max_findings_chars_synthesis:
            logger.log_phase(
                f"Synthesis: scaling per-agent findings to {per_agent_chars} chars "
                f"({n_agents} agents, target 10k total)"
            )
            findings_by_agent = {
                aid: truncate_findings(text, per_agent_chars)
                for aid, text in findings_by_agent.items()
            }

        # ── Inject TA narrative (pre-interpreted plain-English signal) ───────────
        ta = session.get("technical_analysis") or {}
        ta_findings = ta.get("findings", "")
        if ta_findings and ta.get("is_public") and not ta.get("error"):
            ta_text = _build_ta_narrative(ta) or (
                ta_findings if not cfg.strip_markdown_for_synthesis else _strip_markdown(ta_findings)
            )
            findings_by_agent["technical_chart"] = truncate_findings(ta_text, int(cfg.max_ta_chars_synthesis))
            logger.log_phase(
                f"Technical analysis injected into synthesis: {ta.get('ticker')} "
                f"{ta.get('technical_direction')} score={ta.get('technical_score')}"
            )

        majority_raw, majority_weighted, pos, neg, neu = _compute_majority(session["agent_results"])
        cross_summary = " | ".join(note.get("note", "") for note in session.get("cross_exam_notes", []))
        system_prompt, user_prompt = synthesis_prompt(
            target=target,
            findings_by_agent=findings_by_agent,
            cross_exam_summary=cross_summary[: cfg.max_cross_exam_chars],
            majority=majority_raw,
            weighted_direction=majority_weighted,
            positive=pos,
            negative=neg,
            neutral=neu,
            max_chars=cfg.max_findings_chars_synthesis,
        )

        total_prompt_chars = len(system_prompt) + len(user_prompt)
        logger.log_phase(
            f"Synthesis prompt: sys={len(system_prompt)}ch user={len(user_prompt)}ch "
            f"total={total_prompt_chars}ch (~{total_prompt_chars//4} tokens)"
        )

        if mode == "research":
            memo = build_research_mode_memo(
                target=target,
                depth=depth,
                agent_ids=agent_ids,
                agent_results=session["agent_results"],
                cross_exam_notes=session.get("cross_exam_notes", []),
                technical_analysis=session.get("technical_analysis"),
            )
        else:
            result = await asyncio.to_thread(
                self.groq.instant_analysis,
                purpose="synthesis",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                session_id=session_id,
            )
            session["total_tokens_in"] += int(result["token_in"])
            session["total_tokens_out"] += int(result["token_out"])

            memo = parse_memo_json(result["text"], target, agent_ids=agent_ids)
            memo = derive_subscores_from_agents(memo, session["agent_results"])
            memo = enforce_score_scale(memo)
            memo = enforce_bear_thesis(memo)
            memo["majority_raw"] = majority_raw
            memo["majority_weighted"] = majority_weighted
            memo["agents_positive"] = pos
            memo["agents_negative"] = neg
            memo["agents_neutral"] = neu

        social_findings = session["agent_results"].get("social_sentiment", {}).get("findings", "")
        social_signal = _extract_social_signal(social_findings)

        buzz_rank = _rank_value(social_signal["buzz_level"], ["MINIMAL", "LOW", "MEDIUM", "HIGH"])
        impact_rank = _rank_value(social_signal["market_impact"], ["MINOR", "MODERATE", "AMPLIFYING"])
        min_buzz_rank = _rank_value(cfg.social_min_buzz_for_influence, ["MINIMAL", "LOW", "MEDIUM", "HIGH"])
        min_impact_rank = _rank_value(cfg.social_min_impact_for_influence, ["MINOR", "MODERATE", "AMPLIFYING"])
        fundamentals_mixed = abs(pos - neg) <= 1

        if (
            social_signal["meme_risk"] == "YES"
            and social_signal["short_squeeze_risk"] == "YES"
            and social_signal["buzz_trend"] == "RISING"
            and buzz_rank >= min_buzz_rank
            and impact_rank >= min_impact_rank
            and fundamentals_mixed
        ):
            social_signal["influenced_verdict"] = True

        memo.setdefault("social_signal", social_signal)
        if mode != "research" and memo.get("social_signal", {}).get("influenced_verdict"):
            logger.log_warn(
                "Social sentiment influenced the verdict direction. Verify fundamental support before acting."
            )

        financial_findings = session["agent_results"].get("financial", {}).get("findings", "")
        all_findings = " ".join(
            r.get("findings", "") for r in session["agent_results"].values()
            if r.get("status") == "complete"
        )
        snapshot = memo.setdefault("financial_snapshot", {})
        memo["financial_snapshot"] = extract_financial_snapshot(snapshot, financial_findings, all_findings=all_findings)

        if mode != "research":
            memo = validate_valuation_verdict(memo, session["agent_results"])
            memo = cap_investment_action(memo, depth)
            memo = apply_depth_metadata(memo, depth, agent_ids)
            memo = validate_memo(memo, session["agent_results"])

        session["memo"] = memo
        await self._save(session_id)
        if mode == "research":
            await self._push_event(session_id, "memo", "Research dossier ready (raw mode).")
            logger.log_memo("Research dossier generated (mode=research)")
        else:
            await self._push_event(
                session_id,
                "memo",
                f"Memo ready: {memo.get('verdict')} | {memo.get('confidence')} | score {memo.get('overall_score')}",
            )
            logger.log_memo(
                f"Verdict: {memo.get('verdict')} | Confidence: {memo.get('confidence')} | Score: {memo.get('overall_score')}/10"
            )

    async def _run_phase_technical(self, session_id: str, target: str) -> None:
        """
        Phase 2: Technical Analysis
        Runs synchronously in a thread pool (no Groq API calls, no budget used).
        Stores results in session['technical_analysis'] and injects a summary
        into the memo for synthesis context.
        """
        session = await self.get_status(session_id)
        if not session:
            return

        session["phase"] = 2
        session["phase_name"] = PHASE_NAMES[2]
        await self._save(session_id)
        await self._push_event(session_id, "phase", "Phase 2 started: Technical Analysis")
        logger.log_phase(f"━━━ Phase 2: Technical Analysis | Target: {target} ━━━")

        try:
            ta_result = await asyncio.to_thread(run_technical_analysis, target)

            ticker = ta_result.get("ticker")
            is_public = ta_result.get("is_public", False)
            direction = ta_result.get("technical_direction", "NEUTRAL")
            score = ta_result.get("technical_score", 5.0)
            error = ta_result.get("error")

            # Store full TA result (chart_data can be large, kept separate from findings)
            session["technical_analysis"] = {
                "ticker": ticker,
                "is_public": is_public,
                "technical_score": score,
                "technical_direction": direction,
                "signals": ta_result.get("signals", []),
                "patterns": ta_result.get("patterns", []),
                "support_resistance": ta_result.get("support_resistance", {}),
                "findings": ta_result.get("findings", ""),
                "chart_data": ta_result.get("chart_data"),  # full OHLCV + indicators
                "error": error,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

            if error == "private_company":
                await self._push_event(session_id, "phase",
                    f"Technical: {target} is private — chart analysis skipped, continuing to synthesis")
                logger.log_phase(f"Technical Analysis: {target} is private, skipping chart")
            elif error and error.startswith("data_fetch_failed"):
                detail = error.replace("data_fetch_failed: ", "")
                await self._push_event(session_id, "warn",
                    f"Technical: data fetch failed for {ticker} — {detail}")
                logger.log_warn(f"Technical data fetch failed for {ticker}: {detail}")
            else:
                sr = ta_result.get("support_resistance", {})
                current = sr.get("current_price")
                await self._push_event(session_id, "phase",
                    f"Phase 2 complete: Technical Analysis — {ticker} | {direction} | Score {score}/10"
                    + (f" | Price ${current:.2f}" if current else ""))
                logger.log_phase(
                    f"✓ Phase 2 complete | {ticker} | {direction} | Score {score}/10 | "
                    f"{len(ta_result.get('signals', []))} signals | {len(ta_result.get('patterns', []))} patterns"
                )
        except Exception as exc:
            logger.log_error(f"Technical analysis failed: {exc}")
            await self._push_event(session_id, "warn", f"Technical analysis error: {exc}")
            session["technical_analysis"] = {
                "ticker": None,
                "is_public": False,
                "technical_score": 5.0,
                "technical_direction": "NEUTRAL",
                "signals": [],
                "patterns": [],
                "support_resistance": {},
                "findings": f"Technical analysis failed: {exc}",
                "chart_data": None,
                "error": str(exc),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

        await self._save(session_id)

    def status_response(self, session: dict[str, Any]) -> dict[str, Any]:
        agents = []
        for aid in session.get("agent_ids", []):
            st = session.get("agent_results", {}).get(aid, {})
            agents.append(
                {
                    "id": aid,
                    "name": st.get("name"),
                    "status": st.get("status", "pending"),
                    "current_search_query": (st.get("search_queries") or [""])[0],
                    "searches_completed": st.get("compound_calls", 0),
                    "searches_total": st.get("searches_total", 1),
                    "findings_preview": st.get("findings_preview", ""),
                    "sources": [s.get("url") or s.get("query") for s in st.get("sources", [])],
                    "complete": st.get("status") in {"complete", "error"},
                }
            )

        # Expose technical analysis metadata (NOT chart_data — that's fetched via separate endpoint)
        ta = session.get("technical_analysis") or {}
        ta_summary = {
            "ticker": ta.get("ticker"),
            "is_public": ta.get("is_public", False),
            "technical_score": ta.get("technical_score"),
            "technical_direction": ta.get("technical_direction"),
            "signals": ta.get("signals", []),
            "patterns": ta.get("patterns", []),
            "support_resistance": ta.get("support_resistance", {}),
            "error": ta.get("error"),
        } if ta else None

        return {
            "session_id": session.get("session_id"),
            "target": session.get("target"),
            "mode": session.get("mode", "standard"),
            "status": session.get("status"),
            "phase": session.get("phase"),
            "phase_name": session.get("phase_name"),
            "agents": agents,
            "agents_complete": session.get("agents_complete", 0),
            "agents_total": session.get("agents_total", 0),
            "memo": session.get("memo"),
            "budget_used": session.get("budget_used", 0),
            "required_compound_calls": session.get("required_compound_calls", 0),
            "awaiting_user_phase": session.get("awaiting_user_phase"),
            "awaiting_user_message": session.get("awaiting_user_message", ""),
            "event_log": session.get("event_log", [])[-200:],
            "technical_analysis": ta_summary,
            "target_validation": session.get("target_validation"),
        }


def depth_card_data() -> dict[str, Any]:
    return refresh_depth_config()
