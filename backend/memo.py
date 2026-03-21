from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from typing import Any

from .config import cfg
from .logger import logger

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether, PageBreak
    )
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

DEPTH_ACTION_CAPS = {
    "quick": {"STRONG_BUY": "BUY", "STRONG_SELL": "SELL"},
    "standard": {},
    "deep": {},
}

DEPTH_DISCLAIMERS = {
    "quick": (
        "Quick Depth: Only 3 agents ran (Financial, Competitive, News Sentiment). "
        "Regulatory risk, technology signals, management quality, bear case, and social sentiment were NOT assessed. "
        "Run Standard or Deep depth for a complete picture."
    ),
    "standard": (
        "Standard Depth: 10 agents ran. Supply chain, customer quality, macro, bear/bull specialists, "
        "and comparable analysis were not included. Run Deep depth for institutional-grade coverage."
    ),
    "deep": "Deep Depth: All 18 agents ran. Comprehensive institutional-grade analysis.",
}

FINANCIAL_PATTERNS = {
    "revenue": [
        r"(?:full[- ]year|annual|fy\s*202[0-9]|total)\s+revenue[:\s]+\$?([\d,.]+\s*[BMK]?)",
        r"revenue[:\s]+\$?([\d,.]+\s*[BMK])",
        r"\$\s*([\d,.]+\s*[BMK])\s+(?:in\s+)?(?:annual\s+)?revenue",
        r"(?:Q[1-4]\s+\d{4})\s+revenue[:\s]+\$?([\d,.]+\s*[BMK]?)",
    ],
    "growth_rate": [
        r"revenue\s+(?:grew?|growth|up|increased?)[:\s]+(\d+\.?\d*)\s*%",
        r"(\d+\.?\d*)\s*%\s+(?:yoy|year.over.year|revenue\s+growth)",
        r"(?:yoy|year.over.year)\s+(?:revenue\s+)?(?:growth|increase)[:\s]+(\d+\.?\d*)\s*%",
        r"(\d+\.?\d*)\s*%\s+(?:ltm|ttm)\s+revenue\s+growth",
    ],
    "fcf": [
        r"free\s+cash\s+flow[:\s]+\$?([\d,.]+\s*[BMK]?)",
        r"FCF[:\s]+\$?([\d,.]+\s*[BMK]?)",
        r"\$([\d,.]+\s*[BMK])\s*(?:in\s+)?(?:free\s+cash)",
        r"fcf\s+(?:of|was|:)\s+\$?([\d,.]+\s*[BMK]?)",
    ],
    "pe_ratio": [
        r"(\d+\.?\d*)[x×]\s*forward\s+(?:p/?e|earnings)",
        r"P/?E\s*(?:ratio)?[:\s]+(\d+\.?\d*)[x×]?",
        r"(\d+\.?\d*)[x×]\s+(?:forward\s+)?p/?e",
        r"(\d+\.?\d*)\s*times\s+(?:forward\s+)?earnings",
        r"trades?\s+at\s+(\d+\.?\d*)[x×]?\s+(?:forward\s+)?earnings",
    ],
    "ev_revenue": [
        r"EV\s*/\s*[Rr]evenue[:\s]+([\d,.]+)[x×]?",
        r"([\d,.]+)[x×]\s*EV\s*/\s*[Rr]evenue",
        r"enterprise\s+value\s*/\s*revenue[:\s]+([\d,.]+)[x×]?",
        r"([\d,.]+)[x×]\s+(?:ev|enterprise)[- ]to[- ]revenue",
    ],
    "gross_margin": [
        r"gross\s+margin[:\s]+(\d+\.?\d*)\s*%",
        r"(\d+\.?\d*)\s*%\s+gross\s+margin",
        r"gross\s+profit\s+margin[:\s]+(\d+\.?\d*)\s*%",
    ],
    "operating_margin": [
        r"operating\s+margin[:\s]+(\d+\.?\d*)\s*%",
        r"(\d+\.?\d*)\s*%\s+operating\s+margin",
        r"op(?:erating)?\s+margin[:\s]+(\d+\.?\d*)\s*%",
    ],
}

SUBSCORE_KEYS = [
    "financial_health",
    "growth_quality",
    "competitive_position",
    "management_quality",
    "risk_profile",
    "innovation_signal",
    "revenue_quality",
]

SUBSCORE_ALIASES = {
    "financial_health": ["financial_health", "financialHealth", "financial", "financial_score"],
    "growth_quality": ["growth_quality", "growthQuality", "growth", "growth_score"],
    "competitive_position": ["competitive_position", "competitivePosition", "competitive", "moat"],
    "management_quality": ["management_quality", "managementQuality", "management", "leadership"],
    "risk_profile": ["risk_profile", "riskProfile", "risk", "risk_score"],
    "innovation_signal": ["innovation_signal", "innovationSignal", "innovation", "product_innovation"],
    "revenue_quality": ["revenue_quality", "revenueQuality", "revenue", "revenue_score"],
}

POSITIVE_CUES = [
    "strong", "improving", "beat", "upside", "growth", "expanding", "profit", "margin expansion",
    "tailwind", "bullish", "outperform", "healthy", "resilient", "accelerating", "momentum",
]
NEGATIVE_CUES = [
    "weak", "deteriorating", "miss", "downside", "decline", "contracting", "loss", "margin pressure",
    "headwind", "bearish", "underperform", "fragile", "stretched", "overvalued", "risk", "guidance cut",
]


def _limit_words(text: str, max_words: int) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).strip()


def _strip_markdown(text: str) -> str:
    clean = re.sub(r"[`*_>#-]", "", text or "")
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def truncate_findings(findings: str, max_chars: int | None = None) -> str:
    limit = int(max_chars if max_chars is not None else cfg.max_findings_chars_synthesis)
    if len(findings) <= limit:
        return findings
    truncated = findings[:limit]
    last_bullet = truncated.rfind("•")
    if last_bullet > limit // 2:
        truncated = truncated[:last_bullet].rstrip()
    return truncated + "\n[...truncated for synthesis]"


def _placeholder_list(prefix: str, count: int) -> str:
    values = [f'"{prefix}{idx + 1}"' for idx in range(max(int(count), 0))]
    return "[" + ",".join(values) + "]"


def _all_agent_ids() -> list[str]:
    combined = f"{cfg.quick_agent_ids},{cfg.standard_agent_ids},{cfg.deep_agent_ids}"
    ids = [x.strip() for x in combined.split(",") if x.strip()]
    unique = []
    seen = set()
    for aid in ids:
        if aid not in seen:
            seen.add(aid)
            unique.append(aid)
    return unique


def validate_social_signal(memo: dict[str, Any], agent_ids: list[str]) -> dict[str, Any]:
    social_ran = "social_sentiment" in (agent_ids or [])

    if not social_ran:
        memo["social_signal"] = {
            "buzz_level": "UNKNOWN",
            "buzz_trend": "UNKNOWN",
            "retail_direction": "UNKNOWN",
            "intensity": "UNKNOWN",
            "market_impact": "UNKNOWN",
            "meme_risk": "UNKNOWN",
            "short_squeeze_risk": "UNKNOWN",
            "influenced_verdict": False,
            "social_note": "Social sentiment agent did not run for this depth. No social data available.",
            "score_adjustment": 0.0,
        }
        logger.log_warn("Social signal zeroed - social_sentiment agent was not in this run's agent list")
        return memo

    signal = memo.get("social_signal", {})
    if (
        signal.get("meme_risk") == "YES"
        and signal.get("short_squeeze_risk") == "YES"
        and signal.get("influenced_verdict") is True
    ):
        logger.log_warn(
            "Social signal flagged meme+squeeze risk AND influenced verdict - verify support in social findings"
        )
    return memo


def enforce_score_scale(memo: dict[str, Any]) -> dict[str, Any]:
    subscores = memo.get("subscores", {})

    # Detect if the LLM used 0-1 scale: more than half the non-zero scores are < 1.5
    non_zero = [float(v) for v in subscores.values() if isinstance(v, (int, float)) and float(v) > 0]
    using_decimal_scale = len(non_zero) > 0 and sum(1 for v in non_zero if v < 1.5) / len(non_zero) > 0.5

    for key, val in subscores.items():
        if not isinstance(val, (int, float)):
            continue
        fval = float(val)
        if using_decimal_scale and fval < 1.5:
            subscores[key] = round(fval * 10, 1)
            logger.log_warn(f"subscore {key} scaled: {fval} -> {subscores[key]}")
        elif fval > 10:
            # Clamp anything over 10 back to 10
            subscores[key] = 10.0
    memo["subscores"] = subscores

    # Recompute overall_score from the mean of valid (non-zero) subscores.
    # Zero subscores mean the LLM had no data — exclude them from the mean.
    valid_subs = [float(v) for v in subscores.values() if isinstance(v, (int, float)) and float(v) > 0]
    llm_score = memo.get("overall_score", 5)
    if isinstance(llm_score, (int, float)):
        llm_score = float(llm_score)
        if llm_score < 1.5 and llm_score > 0:
            llm_score = round(llm_score * 10, 1)

    if valid_subs:
        computed = round(sum(valid_subs) / len(valid_subs), 1)
        # Only override the LLM score if we have enough subscores to trust the mean
        # (Quick depth has 3 agents — the LLM may not fill all 7 subscores)
        if len(valid_subs) >= 4:
            memo["overall_score"] = computed
            if computed != llm_score:
                logger.log_warn(f"overall_score recomputed from {len(valid_subs)} subscores: {llm_score} -> {computed}")
        else:
            # Not enough subscores — trust the LLM's overall_score but fix scale
            memo["overall_score"] = llm_score
            logger.log_warn(f"overall_score kept from LLM ({llm_score}) — only {len(valid_subs)} valid subscores")
    else:
        # No valid subscores at all — fix LLM score scale and keep it
        memo["overall_score"] = llm_score
        logger.log_warn(f"No valid subscores — using LLM overall_score: {llm_score}")

    return memo


def _to_float(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            m = re.search(r"[-+]?\d+(\.\d+)?", value)
            if m:
                return float(m.group(0))
    except Exception:
        return None
    return None


def normalize_subscores(memo: dict[str, Any]) -> dict[str, Any]:
    raw = memo.get("subscores") if isinstance(memo.get("subscores"), dict) else {}
    normalized: dict[str, float | None] = {}
    for key in SUBSCORE_KEYS:
        val = None
        for alias in SUBSCORE_ALIASES.get(key, [key]):
            if alias in raw:
                val = _to_float(raw.get(alias))
                if val is not None:
                    break
        normalized[key] = val
    memo["subscores"] = normalized
    return memo


def _sentiment_score(text: str) -> float:
    t = (text or "").lower()
    pos = sum(1 for cue in POSITIVE_CUES if cue in t)
    neg = sum(1 for cue in NEGATIVE_CUES if cue in t)
    delta = pos - neg
    if delta > 6:
        delta = 6
    if delta < -6:
        delta = -6
    return delta / 6.0


def derive_subscores_from_agents(memo: dict[str, Any], agent_results: dict[str, Any]) -> dict[str, Any]:
    memo = normalize_subscores(memo)
    subs = memo.get("subscores") or {}

    per_agent_signal: dict[str, float] = {}
    for aid, result in (agent_results or {}).items():
        if result.get("status") != "complete":
            continue
        signal = _sentiment_score(result.get("findings", ""))
        per_agent_signal[aid] = signal

    def aggregate(agent_ids: list[str], fallback: float) -> float:
        vals = [per_agent_signal[a] for a in agent_ids if a in per_agent_signal]
        if not vals:
            return fallback
        return sum(vals) / len(vals)

    all_vals = list(per_agent_signal.values())
    global_signal = (sum(all_vals) / len(all_vals)) if all_vals else 0.0

    model_map = {
        "financial_health": ["financial", "macro", "regulatory"],
        "growth_quality": ["growth", "bull", "news_sentiment", "international"],
        "competitive_position": ["competitive", "comparable", "customer_quality", "international"],
        "management_quality": ["management", "insider", "regulatory"],
        "risk_profile": ["bear", "regulatory", "macro", "supply_chain", "esg"],
        "innovation_signal": ["technology", "product", "growth"],
        "revenue_quality": ["financial", "growth", "customer_quality", "competitive"],
    }

    def to_score(signal: float) -> float:
        return round(max(1.0, min(10.0, 5.5 + signal * 2.5)), 1)

    for key in SUBSCORE_KEYS:
        cur = _to_float(subs.get(key))
        if cur is not None and cur > 0:
            continue
        signal = aggregate(model_map.get(key, []), global_signal)
        subs[key] = to_score(signal)

    memo["subscores"] = subs
    valid = [float(v) for v in subs.values() if isinstance(v, (int, float)) and float(v) > 0]
    if valid:
        base = round(sum(valid) / len(valid), 1)
        adj = _to_float((memo.get("social_signal") or {}).get("score_adjustment")) or 0.0
        cap = abs(float(cfg.social_max_score_adjustment))
        if adj > cap:
            adj = cap
        elif adj < -cap:
            adj = -cap
        memo["overall_score"] = round(max(1.0, min(10.0, base + adj)), 1)
    return memo


def enforce_bear_thesis(memo: dict[str, Any]) -> dict[str, Any]:
    bear = memo.get("bear_thesis", [])
    if not bear or bear == ["None"]:
        risks = memo.get("key_risks", [])
        recovered = [r.get("risk", "") for r in risks[: cfg.memo_bear_thesis_count] if r.get("risk")]
        if not recovered:
            recovered = ["Bear case not identified - run Deep depth for full analysis"]
        memo["bear_thesis"] = recovered
        logger.log_warn("Bear thesis was empty - populated from key_risks")
    return memo


def validate_valuation_verdict(memo: dict[str, Any], agent_results: dict[str, Any]) -> dict[str, Any]:
    verdict = memo.get("financial_snapshot", {}).get("valuation_verdict", "")
    financial_findings = agent_results.get("financial", {}).get("findings", "").lower()

    cheap_signals = ["undervalued", "discount", "cheap relative", "below peers", "low multiple"]
    expensive_signals = [
        "high relative to peers",
        "premium",
        "expensive",
        "stretched",
        "priced for perfection",
        "elevated",
        "40x",
        "50x",
        "rich multiple",
    ]

    cheap_count = sum(1 for s in cheap_signals if s in financial_findings)
    expensive_count = sum(1 for s in expensive_signals if s in financial_findings)

    if expensive_count > cheap_count and verdict == "CHEAP":
        corrected = "EXPENSIVE" if expensive_count >= 2 else "FAIR"
        memo.setdefault("financial_snapshot", {})["valuation_verdict"] = corrected
        logger.log_warn(
            f"Valuation verdict corrected: CHEAP -> {corrected} (found {expensive_count} expensive signals)"
        )

    return memo


def extract_financial_snapshot(snapshot: dict[str, Any], financial_findings: str, all_findings: str = "") -> dict[str, Any]:
    # Search financial agent findings first, then fall back to all agent findings combined.
    # This ensures we still extract data even when the financial agent errors (e.g. 413).
    search_texts = []
    if financial_findings:
        search_texts.append(financial_findings)
    if all_findings and all_findings != financial_findings:
        search_texts.append(all_findings)
    combined = " ".join(search_texts)

    for field, patterns in FINANCIAL_PATTERNS.items():
        if snapshot.get(field) in (None, "Not found", "", "N/A"):
            for pattern in patterns:
                match = re.search(pattern, combined, re.IGNORECASE)
                if match:
                    snapshot[field] = match.group(1)
                    logger.log_system(f"financial_snapshot.{field} extracted from findings: {match.group(1)}")
                    break
    return snapshot


def cap_investment_action(memo: dict[str, Any], depth: str) -> dict[str, Any]:
    action = memo.get("investment_action", "HOLD")
    caps = DEPTH_ACTION_CAPS.get((depth or "").lower(), {})
    if action in caps:
        capped = caps[action]
        memo["investment_action"] = capped
        logger.log_warn(f"Investment action capped for {depth} depth: {action} -> {capped}")

    if (depth or "").lower() == "quick" and memo.get("confidence") == "HIGH":
        memo["confidence"] = "MEDIUM"
        logger.log_warn("Confidence capped to MEDIUM for Quick depth - only 3 agents ran")

    return memo


def apply_depth_metadata(memo: dict[str, Any], depth: str, agent_ids: list[str]) -> dict[str, Any]:
    normalized = (depth or "standard").lower()
    memo["depth_disclaimer"] = DEPTH_DISCLAIMERS.get(normalized, DEPTH_DISCLAIMERS["standard"])
    memo["agents_that_ran"] = list(agent_ids or [])
    all_ids = _all_agent_ids()
    memo["agents_not_run"] = [aid for aid in all_ids if aid not in (agent_ids or [])]
    return memo


def synthesis_prompt(
    *,
    target: str,
    findings_by_agent: dict[str, str],
    cross_exam_summary: str,
    majority: str,
    weighted_direction: str,
    positive: int,
    negative: int,
    neutral: int,
    max_chars: int,
) -> tuple[str, str]:
    system = (
        "You are a senior investment analyst writing an institutional-grade research memo. "
        "Read all agent findings and produce a detailed, substantive JSON memo. "
        "Be specific, quantitative, and analytical. Every prose field must contain REAL ANALYSIS "
        "— not one-line bullets but full sentences with data, context, and reasoning. "
        "Take a clear, well-supported position. Return JSON only.\n\n"
        "DEPTH REQUIREMENTS — CRITICAL:\n"
        f"summary: {cfg.memo_summary_max_words} words of genuine analysis in flowing prose. "
        "Cover business model, financial trajectory, competitive position, and key risks. "
        "Lead with the single most important insight. Include specific numbers from the research. "
        "No bullet points — write real paragraphs.\n"
        f"final_prediction: {cfg.memo_prediction_max_words} words. Give a specific, reasoned outlook "
        "with a time horizon, the key assumptions behind the view, the most important upside driver, "
        "and what single factor could invalidate the thesis.\n"
        f"key_findings: Exactly {cfg.memo_key_findings_count} findings. Each finding must be 2-3 analytical "
        "sentences with specific data — not a one-line headline. Each should be a standalone insight "
        "that adds to understanding beyond what the summary covers.\n"
        f"bull_thesis: {cfg.memo_bull_thesis_count} bull points. Each 2-3 sentences explaining "
        "WHY this is bullish with specific evidence. No vague assertions.\n"
        f"bear_thesis: {cfg.memo_bear_thesis_count} bear points. Each 2-3 sentences on the downside case. "
        "MANDATORY even for bullish verdicts. Cover valuation risk, competitive threats, "
        "execution risk, macro headwinds, or any structural concerns.\n"
        f"key_risks: {cfg.memo_key_risks_count} risks. Each with a 2-sentence description of "
        "what the risk is and its realistic impact on the investment thesis.\n"
        f"key_catalysts: {cfg.memo_catalysts_count} catalysts. Each 1-2 sentences on what the "
        "catalyst is, when it could materialize, and why it would move the stock.\n\n"
        "ANTI-HALLUCINATION RULES:\n"
        "1. Only use facts from agent findings. Never use training data as a source.\n"
        "2. Every specific number must come from the research. If conflicting data exists, cite the most recent.\n"
        "3. HIGH hallucination-risk findings: reference with uncertainty language, avoid specific numbers.\n"
        "4. Missing numeric data: write \'Not found\' — never fabricate.\n"
        "5. Never invent stock prices, revenue figures, analyst ratings, or executive statements.\n\n"
        "SOCIAL SIGNAL RULES:\n"
        "1. Only populate social_signal fields if social_sentiment agent findings are present.\n"
        "2. If absent: all social fields = UNKNOWN, influenced_verdict=false, score_adjustment=0.0.\n"
        "3. Never infer social sentiment from financial or news data.\n\n"
        f"Social weight in synthesis: {cfg.social_synthesis_weight}. "
        f"Social can influence verdict only when buzz >= {cfg.social_min_buzz_for_influence}, "
        f"impact >= {cfg.social_min_impact_for_influence}, and fundamentals are mixed.\n\n"
        "SCORING SCALE — ALL VALUES 1.0 to 10.0:\n"
        "financial_health, growth_quality, competitive_position, management_quality, "
        "risk_profile, innovation_signal, revenue_quality — equal weight 1.0 each.\n"
        f"social_sentiment_adjustment: max +/-{cfg.social_max_score_adjustment} on overall_score only.\n\n"
        "TECHNICAL CHART DATA RULES:\n"
        "The [TECHNICAL_CHART] agent provides real price/indicator data computed from 1-year daily candles.\n"
        "1. Use RSI, MACD, trend direction, and S/R levels to inform the verdict and key findings.\n"
        "2. If technical direction contradicts the fundamental verdict, flag this as a key risk or caveat.\n"
        "3. Include the technical score and 1-2 chart signals in key_findings if they are meaningful.\n"
        "4. Reference specific price levels (support, resistance, 52w high/low) where relevant.\n"
        "5. If TECHNICAL_CHART is absent or shows private_company, omit technical references entirely."
    )

    lines = [f"TARGET: {target}", "", "AGENT FINDINGS (truncated):"]
    for name, text in findings_by_agent.items():
        payload = _strip_markdown(text) if cfg.strip_markdown_for_synthesis else text
        lines.append(f"[{name.upper()}] {truncate_findings(payload, max_chars)}")

    schema_social = (
        '"social_signal":{"buzz_level":"HIGH|MEDIUM|LOW|MINIMAL",'
        '"buzz_trend":"RISING|STABLE|FALLING",'
        '"retail_direction":"BULLISH|BEARISH|MIXED|NEUTRAL",'
        '"intensity":"EXTREME|STRONG|MODERATE|MILD",'
        '"market_impact":"MINOR|MODERATE|AMPLIFYING",'
        '"meme_risk":"YES|NO|POSSIBLE",'
        '"short_squeeze_risk":"YES|NO|POSSIBLE",'
        '"influenced_verdict":false,'
        '"social_note":"one sentence max 20 words",'
        '"score_adjustment":0.0},'
    ) if cfg.memo_include_social_signal else '"social_signal":null,'

    bear_instruction = (
        f"bear_thesis: array of {cfg.memo_bear_thesis_count} strings (max 20 words each). "
        "MUST include bear points even for bullish verdicts. Use valuation, competition, execution, macro, integration risks. "
        "If no bear agent ran, derive from other agents. Never return ['None'] or empty."
    )

    schema = (
        "{"
        '"verdict":"BULLISH|BEARISH|NEUTRAL",'
        '"confidence":"HIGH|MEDIUM|LOW",'
        '"overall_score":"<float 1.0-10.0>",'
        '"investment_action":"BUY|HOLD|SELL|STRONG_BUY|STRONG_SELL",'
        '"time_horizon":"SHORT|MEDIUM|LONG",'
        '"summary":"...",'
        '"final_prediction":"...",'
        f'"key_findings":{_placeholder_list("finding", cfg.memo_key_findings_count)},'
        '"subscores":{"financial_health":"<float 1.0-10.0>","growth_quality":"<float 1.0-10.0>","competitive_position":"<float 1.0-10.0>",'
        '"management_quality":"<float 1.0-10.0>","risk_profile":"<float 1.0-10.0>","innovation_signal":"<float 1.0-10.0>","revenue_quality":"<float 1.0-10.0>"},'
        '"financial_snapshot":{"revenue":"...","growth_rate":"...","gross_margin":"...",'
        '"operating_margin":"...","pe_ratio":"...","ev_revenue":"...","fcf":"...","valuation_verdict":"CHEAP|FAIR|EXPENSIVE"},'
        f'"bull_thesis":{_placeholder_list("bull", cfg.memo_bull_thesis_count)},'
        f'"bear_thesis":{_placeholder_list("bear", cfg.memo_bear_thesis_count)},'
        '"key_risks":[{"risk":"...","severity":"HIGH|MEDIUM|LOW",'
        '"category":"Financial|Regulatory|Competitive|Execution|Macro"}],'
        f'"key_catalysts":{_placeholder_list("catalyst", cfg.memo_catalysts_count)},'
        f"{schema_social}"
        f'"majority_raw":"{majority}",'
        f'"majority_weighted":"{weighted_direction}",'
        f'"agents_positive":{positive},'
        f'"agents_negative":{negative},'
        f'"agents_neutral":{neutral}'
        "}"
    )

    lines.extend(
        [
            "",
            "CROSS-EXAM NOTES (key disagreements only):",
            (cross_exam_summary[: cfg.max_cross_exam_chars] if cross_exam_summary else "None"),
            "",
            "MANDATORY CONSTRAINTS:",
            f"Raw majority: {majority} ({positive}+ / {negative}- / {neutral}=)",
            f"Weighted direction: {weighted_direction}",
            "Your verdict MUST be consistent with these numbers.",
            "",
            "Return JSON only.",
            f"summary: {cfg.memo_summary_max_words} words, flowing prose paragraphs — no bullets.",
            f"final_prediction: {cfg.memo_prediction_max_words} words, specific outlook with assumptions.",
            f"key_findings: exactly {cfg.memo_key_findings_count} items, each 2-3 analytical sentences with data.",
            f"bull_thesis: {cfg.memo_bull_thesis_count} items, each 2-3 sentences with evidence.",
            f"bear_thesis: {cfg.memo_bear_thesis_count} items, each 2-3 sentences — MANDATORY.",
            f"key_risks: {cfg.memo_key_risks_count} items each with description and impact.",
            f"key_catalysts: {cfg.memo_catalysts_count} items each with timing and significance.",
            bear_instruction,
            "",
            "Schema:",
            schema,
        ]
    )
    return system, "\n".join(lines)


def _fallback_memo(target: str) -> dict[str, Any]:
    return {
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "NEUTRAL",
        "confidence": "LOW",
        "overall_score": 5.0,
        "investment_action": "HOLD",
        "time_horizon": "MEDIUM",
        "summary": "Synthesis response could not be parsed. Review underlying agent findings.",
        "final_prediction": "Insufficient structured output. Maintain neutral stance until further validated data.",
        "key_findings": ["Synthesis parsing fallback triggered"] * max(int(cfg.memo_key_findings_count), 1),
        "subscores": {
            "financial_health": 5.0,
            "growth_quality": 5.0,
            "competitive_position": 5.0,
            "management_quality": 5.0,
            "risk_profile": 5.0,
            "innovation_signal": 5.0,
            "revenue_quality": 5.0,
        },
        "financial_snapshot": {
            "revenue": "N/A",
            "growth_rate": "N/A",
            "gross_margin": "N/A",
            "operating_margin": "N/A",
            "pe_ratio": "N/A",
            "ev_revenue": "N/A",
            "fcf": "N/A",
            "valuation_verdict": "FAIR",
        },
        "bull_thesis": [],
        "bear_thesis": [],
        "key_risks": [],
        "key_catalysts": [],
        "social_signal": {
            "buzz_level": "UNKNOWN",
            "buzz_trend": "UNKNOWN",
            "retail_direction": "UNKNOWN",
            "intensity": "UNKNOWN",
            "market_impact": "UNKNOWN",
            "meme_risk": "UNKNOWN",
            "short_squeeze_risk": "UNKNOWN",
            "influenced_verdict": False,
            "social_note": "Social sentiment agent did not run for this depth. No social data available.",
            "score_adjustment": 0.0,
        },
        "majority_raw": "NEUTRAL",
        "majority_weighted": "NEUTRAL",
        "agents_positive": 0,
        "agents_negative": 0,
        "agents_neutral": 0,
    }


def parse_memo_json(raw_text: str, target: str, agent_ids: list[str] | None = None) -> dict[str, Any]:
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end < 0:
            raise ValueError("No JSON")
        parsed = json.loads(raw_text[start : end + 1])
        parsed["target"] = target
        parsed.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
        if "summary" in parsed:
            parsed["summary"] = _limit_words(str(parsed.get("summary", "")), int(cfg.memo_summary_max_words))
        if "final_prediction" in parsed:
            parsed["final_prediction"] = _limit_words(
                str(parsed.get("final_prediction", "")), int(cfg.memo_prediction_max_words)
            )
        parsed = validate_social_signal(parsed, list(agent_ids or []))
        parsed = enforce_score_scale(parsed)
        parsed = enforce_bear_thesis(parsed)
        return parsed
    except Exception:
        fallback = _fallback_memo(target)
        return validate_social_signal(fallback, list(agent_ids or []))


def memo_to_markdown(session_data: dict[str, Any]) -> str:
    memo = session_data.get("memo") or {}
    lines = [
        f"# AlphaSwarm Memo - {session_data.get('target', '')}",
        f"Generated: {memo.get('generated_at', '')}",
        f"Verdict: **{memo.get('verdict', 'NEUTRAL')}**",
        f"Action: **{memo.get('investment_action', 'HOLD')}**",
        "",
        "## Summary",
        memo.get("summary", ""),
        "",
        "## Key Findings",
    ]
    for item in memo.get("key_findings", []):
        lines.append(f"- {item}")

    lines += ["", "## Subscores"]
    for k, v in (memo.get("subscores") or {}).items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## Agent Findings"]
    for agent_id, result in (session_data.get("agent_results") or {}).items():
        lines += [f"### {agent_id}", result.get("findings", ""), ""]

    lines += ["## Sources"]
    for agent_id, result in (session_data.get("agent_results") or {}).items():
        for src in result.get("sources", []):
            url = src.get("url", "")
            query = src.get("query", "")
            lines.append(f"- [{agent_id}] {url or query} ({query})")

    return "\n".join(lines)


def memo_to_pdf(session_data: dict[str, Any], out_path: str) -> None:
    """Generate a polished PDF research memo using reportlab."""
    if not REPORTLAB_OK:
        raise RuntimeError("reportlab is not installed. Run: pip install reportlab")

    import unicodedata

    memo = session_data.get("memo") or {}
    target = session_data.get("target", "Unknown")
    generated = (memo.get("generated_at") or "").replace("T", " ")[:19] or datetime.now(timezone.utc).isoformat()[:19]
    depth = (session_data.get("depth") or "").upper()
    agent_count = len(session_data.get("agent_ids") or [])

    C_ACCENT = colors.HexColor("#00b4a6")
    C_GREEN = colors.HexColor("#16a34a")
    C_RED = colors.HexColor("#dc2626")
    C_AMBER = colors.HexColor("#d97706")
    C_TEXT = colors.HexColor("#0f172a")
    C_MUTED = colors.HexColor("#64748b")
    C_PANEL = colors.HexColor("#f8fafc")
    C_BORDER = colors.HexColor("#e2e8f0")
    C_WHITE = colors.white
    C_HEADING = colors.HexColor("#1e293b")
    C_BLUE = colors.HexColor("#1d4ed8")

    verdict = memo.get("verdict", "NEUTRAL")
    verdict_color = C_GREEN if verdict == "BULLISH" else C_RED if verdict == "BEARISH" else C_AMBER
    verdict_hex = "#16a34a" if verdict == "BULLISH" else "#dc2626" if verdict == "BEARISH" else "#d97706"

    action = memo.get("investment_action", "HOLD")
    action_hex = "#16a34a" if action in ("BUY", "STRONG_BUY") else "#dc2626" if action in ("SELL", "STRONG_SELL") else "#d97706"

    def clean_text(raw: str, max_chars: int = 4000) -> str:
        if not raw:
            return ""
        text = str(raw)[:max_chars]
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        text = re.sub(r"#{1,6}\s*", "", text)
        text = re.sub(r"`[^`]*`", "", text)
        text = re.sub(r"~~(.*?)~~", r"\1", text)
        text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
        text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
        text = text.replace("*", "").replace("_", " ")
        text = re.sub(r"\[\d+\]", "", text)
        text = text.replace("\u25a0", " ").replace("\u25cf", " ").replace("\u25cb", " ")
        safe = []
        for ch in text:
            cp = ord(ch)
            if cp < 128:
                safe.append(ch)
            elif cp in (0x2013, 0x2014):
                safe.append("-")
            elif cp in (0x2018, 0x2019):
                safe.append("'")
            elif cp in (0x201c, 0x201d):
                safe.append('"')
            elif cp in (0x2026,):
                safe.append("...")
            elif unicodedata.category(ch).startswith("L"):
                try:
                    ch.encode("latin-1")
                    safe.append(ch)
                except Exception:
                    safe.append("?")
            else:
                safe.append(" ")
        text = "".join(safe)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").strip()

    def clean_url(url: str) -> str:
        url = (url or "").strip().rstrip(".;,)")
        url = re.sub(r"[\u25a0\u25cf\u25cb#]+$", "", url)
        if len(url) <= 92:
            return url
        return f"{url[:89]}..."

    def escape_xml(text: str) -> str:
        return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def extract_source_urls(src: Any) -> list[str]:
        candidates: list[str] = []
        if isinstance(src, dict):
            for key in ("url", "link", "source", "query", "result", "results", "output"):
                val = src.get(key)
                if isinstance(val, str) and val.strip():
                    candidates.append(val.strip())
        elif isinstance(src, str):
            candidates.append(src.strip())

        urls: list[str] = []
        for c in candidates:
            found = re.findall(r"https?://[^\s\"'<>]+", c)
            if found:
                urls.extend(found)
            elif c.startswith("http"):
                urls.append(c)
        return urls

    base = getSampleStyleSheet()

    def S(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    h1 = S("h1", fontName="Helvetica-Bold", fontSize=22, leading=30, textColor=C_HEADING, spaceAfter=6 * mm)
    h2 = S("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=C_HEADING, spaceBefore=6 * mm, spaceAfter=2.5 * mm)
    body = S("body", fontSize=9.6, leading=14.5, textColor=C_TEXT, spaceAfter=2.2 * mm)
    body_tight = S("body_tight", fontSize=8.6, leading=12.5, textColor=C_TEXT, spaceAfter=1.4 * mm)
    label = S("label", fontSize=8.3, fontName="Helvetica-Bold", textColor=C_MUTED)
    value = S("value", fontSize=9.2, fontName="Helvetica-Bold", textColor=C_TEXT)
    small = S("small", fontSize=7.8, leading=10.5, textColor=C_MUTED)
    bullet = S("bullet", fontSize=9.6, leading=14.8, textColor=C_TEXT, leftIndent=8 * mm, firstLineIndent=-5 * mm, spaceAfter=2.6 * mm)
    risk_meta = S("risk_meta", fontSize=8.6, leading=12.8, textColor=C_MUTED, spaceAfter=0.6 * mm)
    risk_text = S("risk_text", fontSize=9.4, leading=14.2, textColor=C_TEXT, spaceAfter=2.8 * mm)

    def P(text: str, style: ParagraphStyle) -> Paragraph:
        cleaned = clean_text(text)
        try:
            return Paragraph(cleaned, style)
        except Exception:
            return Paragraph(re.sub(r"<[^>]+>", "", cleaned), style)

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=24 * mm,
        bottomMargin=17 * mm,
        title=f"AlphaSwarm Research - {target}",
        author="AlphaSwarm",
    )
    width = A4[0] - 34 * mm
    story: list[Any] = []

    def draw_header_footer(canvas, doc_obj):
        canvas.saveState()
        page_num = canvas.getPageNumber()
        top_y = A4[1] - 10 * mm
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.6)
        canvas.line(doc_obj.leftMargin, top_y, A4[0] - doc_obj.rightMargin, top_y)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(C_ACCENT)
        canvas.drawString(doc_obj.leftMargin, top_y + 2.3 * mm, "ALPHASWARM RESEARCH MEMO")
        canvas.setFillColor(C_MUTED)
        canvas.setFont("Helvetica", 7.8)
        canvas.drawRightString(A4[0] - doc_obj.rightMargin, top_y + 2.3 * mm, clean_text(target, 70))

        bottom_y = 9 * mm
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(doc_obj.leftMargin, bottom_y + 3.5 * mm, A4[0] - doc_obj.rightMargin, bottom_y + 3.5 * mm)
        canvas.setFillColor(C_MUTED)
        canvas.setFont("Helvetica", 7.2)
        canvas.drawString(doc_obj.leftMargin, bottom_y, f"Generated {generated}")
        canvas.drawRightString(A4[0] - doc_obj.rightMargin, bottom_y, f"Page {page_num}")
        canvas.restoreState()

    def rule(space_before: float = 1.4, space_after: float = 3.4):
        story.append(Spacer(1, space_before * mm))
        story.append(HRFlowable(width="100%", thickness=0.45, color=C_BORDER))
        story.append(Spacer(1, space_after * mm))

    def section(title: str, color_hex: str = "#1e293b"):
        story.append(Paragraph(f'<font color="{color_hex}"><b>{clean_text(title, 80)}</b></font>', h2))

    # Cover header (stable two-column layout to prevent overlap)
    cover_right = Table(
        [
            [Paragraph(f'<font color="{verdict_hex}"><b>{clean_text(verdict, 20)}</b></font>', S("v1", fontSize=14, fontName="Helvetica-Bold", alignment=2))],
            [Paragraph(f'<font color="{action_hex}"><b>{clean_text(action, 20)}</b></font>', S("v2", fontSize=10.5, fontName="Helvetica-Bold", alignment=2))],
            [Paragraph(f"Score {memo.get('overall_score', '—')}/10 | {clean_text(memo.get('confidence', '—'), 20)} confidence", S("v3", fontSize=8.1, textColor=C_MUTED, alignment=2))],
        ],
        colWidths=[56 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_WHITE),
                ("BOX", (0, 0), (-1, -1), 0.7, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        ),
    )
    cover_left = [
        Paragraph(clean_text(target, 180), h1),
        Paragraph(
            f"Generated {generated} | Depth {depth or 'STANDARD'} | {agent_count} agents",
            S("meta", fontSize=9.4, textColor=C_MUTED, spaceAfter=1.8 * mm),
        ),
    ]
    story.append(
        KeepTogether(Table(
            [[cover_left, cover_right]],
            colWidths=[width - 60 * mm, 60 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        ))
    )
    story.append(Spacer(1, 1.8 * mm))
    story.append(
        Table(
            [[P(memo.get("summary") or "No summary available.", S("sum_card", fontSize=9.4, leading=14.2, textColor=C_TEXT))]],
            colWidths=[width],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), C_PANEL),
                    ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=1.8, color=C_ACCENT))
    story.append(Spacer(1, 3.4 * mm))

    # Financial snapshot
    section("Financial Snapshot")
    fin = memo.get("financial_snapshot") or {}
    metrics = [
        ("Revenue", fin.get("revenue")),
        ("Growth Rate", fin.get("growth_rate")),
        ("Gross Margin", fin.get("gross_margin")),
        ("Operating Margin", fin.get("operating_margin")),
        ("P/E Ratio", fin.get("pe_ratio")),
        ("EV/Revenue", fin.get("ev_revenue")),
        ("Free Cash Flow", fin.get("fcf")),
        ("Valuation", fin.get("valuation_verdict")),
    ]
    grid = []
    for i in range(0, len(metrics), 2):
        row = []
        for k, v in metrics[i : i + 2]:
            val = "—" if v in (None, "", "Not found", "N/A", "None") else clean_text(str(v), 80)
            row.extend([Paragraph(f"<b>{k}</b>", label), Paragraph(val, value)])
        grid.append(row)
    ft = Table(grid, colWidths=[30 * mm, 44 * mm, 30 * mm, 44 * mm])
    ft.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_PANEL),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_PANEL, C_WHITE]),
                ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(ft)
    rule()

    # Score summary
    section("Score Summary")
    subscores = memo.get("subscores") or {}
    score_rows = []
    for name, val in subscores.items():
        score_val = float(val) if isinstance(val, (int, float)) else 0.0
        filled = max(0, min(20, int(round(score_val * 2))))
        bar = f'<font color="#00b4a6">{"|" * filled}</font><font color="#cbd5e1">{"|" * (20 - filled)}</font>'
        score_rows.append([Paragraph(clean_text(name.replace("_", " ").title(), 45), label), Paragraph(bar, S("bar", fontName="Courier", fontSize=7.8, leading=10.5)), Paragraph(f"<b>{score_val:.1f}</b>", S("sv", fontSize=9.4, fontName="Helvetica-Bold", alignment=2))])
    scores_table = Table(score_rows or [[Paragraph("No subscores available.", small), "", ""]], colWidths=[45 * mm, width - 62 * mm, 17 * mm])
    scores_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_PANEL),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_PANEL, C_WHITE]),
                ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    overall = float(memo.get("overall_score") or 5)
    overall_hex = "#16a34a" if overall >= 7 else "#d97706" if overall >= 5 else "#dc2626"
    overall_card = Table(
        [
            [Paragraph("Overall", S("ol1", fontSize=8.8, textColor=C_MUTED, fontName="Helvetica-Bold", alignment=1, spaceAfter=2.2 * mm))],
            [Paragraph(f'<font color="{overall_hex}"><b>{overall:.1f}/10</b></font>', S("ol2", fontSize=26, leading=28, fontName="Helvetica-Bold", alignment=1, spaceAfter=1.2 * mm))],
            [Paragraph(f'<font color="{action_hex}"><b>{clean_text(action, 20)}</b></font>', S("ol3", fontSize=9.6, leading=11.6, fontName="Helvetica-Bold", alignment=1))],
        ],
        colWidths=[38 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_WHITE),
                ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        ),
    )
    story.append(
        Table(
            [[overall_card, scores_table]],
            colWidths=[40 * mm, width - 40 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        )
    )
    rule()

    # Narrative sections
    section("12-Month Outlook & Prediction", "#1d4ed8")
    story.append(P(memo.get("final_prediction") or "No prediction available.", body))
    rule()

    section("Key Findings")
    findings = memo.get("key_findings") or []
    if not findings:
        story.append(P("No key findings were returned.", body_tight))
    for i, finding in enumerate(findings, 1):
        story.append(P(f"{i}. {clean_text(str(finding), 800)}", bullet))
    rule()

    # Bull/Bear columns
    section("Thesis Framework")
    half = (width - 4 * mm) / 2

    def thesis_block(title: str, items: list[Any], bg: str, border, text_color) -> Table:
        rows = [[Paragraph(f"<b>{title}</b>", S(f"{title}_h", fontSize=10, fontName="Helvetica-Bold", textColor=text_color, spaceAfter=1.4 * mm))]]
        if not items:
            rows.append([Paragraph("No entries provided.", small)])
        for item in items:
            rows.append([P(f"• {clean_text(str(item), 900)}", S(f"{title}_i", fontSize=9.2, leading=13.4, textColor=C_TEXT, spaceAfter=1.4 * mm))])
        t = Table(rows, colWidths=[half - 2 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)), ("BOX", (0, 0), (-1, -1), 0.6, border), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        return t

    bull_table = thesis_block("Bull Case", memo.get("bull_thesis") or [], "#f0fdf4", C_GREEN, C_GREEN)
    bear_table = thesis_block("Bear Case", memo.get("bear_thesis") or [], "#fef2f2", C_RED, C_RED)
    story.append(Table([[bull_table, bear_table]], colWidths=[half, half], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])))
    rule()

    section("Key Risks", "#7c3aed")
    severity_colors = {"HIGH": "#dc2626", "MEDIUM": "#d97706", "LOW": "#16a34a"}
    risks = memo.get("key_risks") or []
    if not risks:
        story.append(P("No explicit risks listed.", body_tight))
    for risk in risks:
        sev = str(risk.get("severity") or "MEDIUM").upper()
        cat = clean_text(risk.get("category") or "General", 40)
        txt = clean_text(risk.get("risk") or "", 550)
        sev_hex = severity_colors.get(sev, "#d97706")
        meta_style = S(f"risk_meta_{sev}", fontSize=8.6, leading=12.8, textColor=colors.HexColor(sev_hex), fontName="Helvetica-Bold", spaceAfter=0.6 * mm)
        story.append(P(f"[{sev}] {cat}", meta_style))
        story.append(P(txt, risk_text))
    rule()

    section("Key Catalysts", "#0891b2")
    catalysts = memo.get("key_catalysts") or []
    if not catalysts:
        story.append(P("No catalysts listed.", body_tight))
    for cat in catalysts:
        story.append(P(f"• {clean_text(str(cat), 550)}", body))
    rule()

    # ── Technical Analysis (Phase 4) ─────────────────────────────────────────
    ta = session_data.get("technical_analysis") or {}
    if ta and ta.get("is_public") and not ta.get("error"):
        story.append(PageBreak())
        # Use plain hex strings — HexColor objects have no .hexval() method
        TA_BULL_HEX = "#16a34a"
        TA_BEAR_HEX = "#dc2626"
        TA_NEU_HEX  = "#d97706"
        TA_ACC_HEX  = "#00b4a6"
        C_TA_BULL   = colors.HexColor(TA_BULL_HEX)
        C_TA_BEAR   = colors.HexColor(TA_BEAR_HEX)
        C_TA_NEU    = colors.HexColor(TA_NEU_HEX)
        C_TA_ACC    = colors.HexColor(TA_ACC_HEX)

        def ta_color_hex(direction: str) -> str:
            d = (direction or "").upper()
            return TA_BULL_HEX if d == "BULLISH" else TA_BEAR_HEX if d == "BEARISH" else TA_NEU_HEX

        ticker   = clean_text(ta.get("ticker") or "", 20)
        ta_dir   = clean_text(ta.get("technical_direction") or "NEUTRAL", 15)
        ta_score = ta.get("technical_score") or 5.0
        dir_hex  = ta_color_hex(ta_dir)

        ta_header_right = Table(
            [
                [Paragraph(f'<font color="{dir_hex}"><b>{ta_dir}</b></font>',
                            S("ta_dir", fontSize=12, fontName="Helvetica-Bold", alignment=2))],
                [Paragraph(f"Technical Score: {ta_score}/10",
                            S("ta_sc", fontSize=8.4, textColor=C_MUTED, alignment=2))],
            ],
            colWidths=[44 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), C_WHITE),
                ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]),
        )
        story.append(Table(
            [[Paragraph(f'<font color="{TA_ACC_HEX}"><b>Technical Chart Analysis — {ticker}</b></font>',
                         S("ta_h", fontSize=13, fontName="Helvetica-Bold", textColor=C_TA_ACC)), ta_header_right]],
            colWidths=[width - 46 * mm, 46 * mm],
            style=TableStyle([("VALIGN", (0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]),
        ))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "1-Year Daily Candles · RSI(14) · MACD(12,26,9) · Bollinger Bands(20,2) · Pivot S/R Levels",
            S("ta_sub", fontSize=8, textColor=C_MUTED, spaceAfter=3 * mm),
        ))

        # S/R levels grid
        sr = ta.get("support_resistance") or {}
        def fmtprice(v):
            try:
                return f"${float(v):.2f}" if v is not None else "N/A"
            except (TypeError, ValueError):
                return "N/A"
        sr_data = [
            [Paragraph("<b>Current Price</b>", label), Paragraph(fmtprice(sr.get("current_price")), value),
             Paragraph("<b>52w High</b>", label), Paragraph(fmtprice(sr.get("wk52_high")), value)],
            [Paragraph("<b>52w Low</b>", label), Paragraph(fmtprice(sr.get("wk52_low")), value),
             Paragraph("<b>Pivot</b>", label), Paragraph(fmtprice(sr.get("pivot")), value)],
            [Paragraph("<b>Resistance 1</b>", label), Paragraph(fmtprice(sr.get("r1")), value),
             Paragraph("<b>Resistance 2</b>", label), Paragraph(fmtprice(sr.get("r2")), value)],
            [Paragraph("<b>Support 1</b>", label), Paragraph(fmtprice(sr.get("s1")), value),
             Paragraph("<b>Support 2</b>", label), Paragraph(fmtprice(sr.get("s2")), value)],
        ]
        sr_table = Table(sr_data, colWidths=[30*mm, 36*mm, 30*mm, 36*mm])
        sr_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), C_PANEL),
            ("ROWBACKGROUNDS", (0,0),(-1,-1), [C_PANEL, C_WHITE]),
            ("BOX", (0,0),(-1,-1), 0.6, C_BORDER),
            ("INNERGRID", (0,0),(-1,-1), 0.3, C_BORDER),
            ("TOPPADDING", (0,0),(-1,-1), 4), ("BOTTOMPADDING", (0,0),(-1,-1), 4),
            ("LEFTPADDING", (0,0),(-1,-1), 5), ("RIGHTPADDING", (0,0),(-1,-1), 5),
        ]))
        story.append(sr_table)
        story.append(Spacer(1, 3 * mm))

        # Signals table
        signals = ta.get("signals") or []
        if signals:
            story.append(Paragraph("<b>Technical Signals</b>", S("ta_sig_h", fontSize=9, fontName="Helvetica-Bold", textColor=C_HEADING, spaceBefore=1*mm, spaceAfter=2*mm)))
            sig_rows = [[
                Paragraph("<b>Signal</b>", label),
                Paragraph("<b>Type</b>", label),
                Paragraph("<b>Strength</b>", label),
                Paragraph("<b>Detail</b>", label),
            ]]
            for s in signals[:8]:
                stype = str(s.get("type", "neutral")).upper()
                shex  = ta_color_hex(stype)
                sig_rows.append([
                    Paragraph(clean_text(s.get("signal", ""), 60), S("sc1", fontSize=8.2, textColor=C_TEXT)),
                    Paragraph(f'<font color="{shex}"><b>{stype}</b></font>', S("sc2", fontSize=8.2, fontName="Helvetica-Bold")),
                    Paragraph(clean_text(str(s.get("strength", "")).upper(), 12), S("sc3", fontSize=8.2, textColor=C_MUTED)),
                    Paragraph(clean_text(s.get("detail", ""), 160), S("sc4", fontSize=7.8, textColor=C_MUTED, leading=10.5)),
                ])
            sig_table = Table(sig_rows, colWidths=[48*mm, 20*mm, 18*mm, width-86*mm], repeatRows=1)
            sig_table.setStyle(TableStyle([
                ("BACKGROUND", (0,0),(-1,0), C_PANEL),
                ("ROWBACKGROUNDS", (0,1),(-1,-1), [C_WHITE, C_PANEL]),
                ("BOX", (0,0),(-1,-1), 0.6, C_BORDER),
                ("INNERGRID", (0,0),(-1,-1), 0.3, C_BORDER),
                ("TOPPADDING", (0,0),(-1,-1), 4), ("BOTTOMPADDING", (0,0),(-1,-1), 4),
                ("LEFTPADDING", (0,0),(-1,-1), 5), ("RIGHTPADDING", (0,0),(-1,-1), 5),
                ("VALIGN", (0,0),(-1,-1), "TOP"),
            ]))
            story.append(sig_table)
            story.append(Spacer(1, 3 * mm))

        # Candlestick patterns
        patterns = ta.get("patterns") or []
        if patterns:
            story.append(Paragraph("<b>Candlestick Patterns Detected</b>", S("ta_pat_h", fontSize=9, fontName="Helvetica-Bold", textColor=C_HEADING, spaceBefore=1*mm, spaceAfter=2*mm)))
            for p in patterns:
                ptype  = str(p.get("type", "neutral")).upper()
                phex   = ta_color_hex(ptype)
                story.append(Paragraph(
                    f'<font color="{phex}"><b>{clean_text(p.get("name", ""), 30)}</b></font>'
                    f' — {clean_text(p.get("desc", ""), 200)}',
                    S(f"pat_{ptype}", fontSize=8.6, leading=12.5, textColor=C_TEXT, spaceAfter=1.5*mm),
                ))

        # TA findings text block (truncated)
        findings_text = (ta.get("findings") or "").strip()
        if findings_text:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph("<b>Full Technical Findings</b>", S("ta_ff_h", fontSize=9, fontName="Helvetica-Bold", textColor=C_HEADING, spaceAfter=2*mm)))
            for line in findings_text.split("\n")[:40]:
                line = line.strip()
                if line.startswith("##"):
                    story.append(Paragraph(clean_text(line.replace("##","").strip(), 80), S("ta_sec", fontSize=8.6, fontName="Helvetica-Bold", textColor=C_TA_ACC, spaceBefore=2*mm, spaceAfter=1*mm)))
                elif line.startswith("-"):
                    story.append(Paragraph(clean_text(line, 300), S("ta_li", fontSize=8.2, leading=11.5, textColor=C_TEXT, leftIndent=4*mm, spaceAfter=0.8*mm)))
                elif line:
                    story.append(Paragraph(clean_text(line, 300), body_tight))

        story.append(Spacer(1, 2 * mm))
        story.append(HRFlowable(width="100%", thickness=0.45, color=C_BORDER))
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph(
            "Technical analysis data sourced from yfinance (1-year daily candles). Not financial advice — use as supplementary signal only.",
            S("ta_disc", fontSize=7.4, textColor=C_MUTED, spaceAfter=3*mm),
        ))

    story.append(PageBreak())
    section("Agent Research Findings")
    for agent_id, result in (session_data.get("agent_results") or {}).items():
        if result.get("status") != "complete":
            continue
        findings_text = (result.get("findings") or "").strip()
        if not findings_text:
            continue
        agent_name = clean_text(result.get("name") or agent_id, 100)
        source_count = len(result.get("sources") or [])

        header = Table(
            [[Paragraph(f"<b>{agent_name}</b>", S("ah1", fontSize=10, fontName="Helvetica-Bold", textColor=C_WHITE)), Paragraph(f"{source_count} sources", S("ah2", fontSize=8.2, textColor=C_WHITE, alignment=2))]],
            colWidths=[width * 0.78, width * 0.22],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), C_BLUE), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]),
        )
        story.append(Spacer(1, 3.1 * mm))
        story.append(header)

        sections = re.split(r"##\s+", findings_text)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            parts = sec.split("\n", 1)
            if len(parts) > 1:
                sec_title, sec_body = parts[0].strip(), parts[1].strip()
                story.append(Paragraph(clean_text(sec_title, 120), S("ast", fontSize=8.8, fontName="Helvetica-Bold", textColor=C_BLUE, spaceBefore=2.2 * mm, spaceAfter=1 * mm)))
            else:
                sec_body = parts[0].strip()
            for line in sec_body.split("\n"):
                line = re.sub(r"^[-•*]\s*", "", line.strip())
                if line:
                    story.append(P(line, body_tight))

    story.append(PageBreak())
    section("Sources")
    source_rows = [[Paragraph("<b>Agent</b>", label), Paragraph("<b>Source URL</b>", label)]]
    seen = set()
    for agent_id, result in (session_data.get("agent_results") or {}).items():
        for src in (result.get("sources") or []):
            for raw_url in extract_source_urls(src):
                url = clean_url(raw_url).rstrip("】〔[]")
                if not url or url in seen:
                    continue
                seen.add(url)
                source_rows.append([
                    Paragraph(clean_text(agent_id, 30), small),
                    Paragraph(escape_xml(url), small),
                ])
    if len(source_rows) == 1:
        source_rows.append([Paragraph("N/A", small), Paragraph("No sources captured.", small)])

    src_table = Table(source_rows, colWidths=[35 * mm, width - 35 * mm], repeatRows=1)
    src_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), C_PANEL),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_PANEL]),
                ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(src_table)
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.45, color=C_BORDER))
    story.append(Spacer(1, 1.5 * mm))
    story.append(
        Paragraph(
            "This memo was generated by AlphaSwarm for informational purposes only and is not financial advice.",
            small,
        )
    )

    doc.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)


def memo_to_html(session_data: dict[str, Any]) -> str:
    """Legacy HTML export — kept for compatibility."""
    memo = session_data.get("memo") or {}
    findings = "".join(f"<li>{escape(str(x))}</li>" for x in memo.get("key_findings", []))
    score_rows = "".join(
        f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>"
        for k, v in (memo.get("subscores") or {}).items()
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"/>
<style>body{{font-family:Arial,sans-serif;padding:24px;color:#0f172a}}.card{{border:1px solid #cbd5e1;border-radius:10px;padding:12px;margin:10px 0}}</style>
</head><body>
<h1>AlphaSwarm — {escape(session_data.get("target",""))}</h1>
<div class="card"><b>{escape(str(memo.get("verdict","NEUTRAL")))}</b> | {escape(str(memo.get("investment_action","HOLD")))}</div>
<div class="card"><h3>Summary</h3><p>{escape(str(memo.get("summary","")))}</p><ul>{findings}</ul></div>
<div class="card"><h3>Subscores</h3><table>{score_rows}</table></div>
</body></html>"""
