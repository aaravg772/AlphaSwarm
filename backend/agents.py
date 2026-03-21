from __future__ import annotations

from datetime import date
from dataclasses import dataclass, replace
from typing import Any

from .config import cfg, get_depth_agent_ids


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    icon: str
    compound_searches: int
    domain_description: str
    search_queries_template: list[str]
    output_sections: list[str]
    weight_in_synthesis: float = 1.0


AGENTS: dict[str, AgentSpec] = {
    "financial": AgentSpec(
        id="financial",
        name="Financial Analyst",
        icon="chart",
        compound_searches=1,
        domain_description=(
            "Revenue trajectory, gross/operating margins, FCF generation, "
            "balance sheet strength, debt maturity, valuation multiples "
            "(P/E, EV/EBITDA, EV/Revenue vs peers), earnings quality, "
            "guidance credibility, and consensus analyst targets."
        ),
        search_queries_template=[
            "{target} revenue earnings financials valuation analyst targets 2025 2026",
        ],
        output_sections=["financials", "valuation", "earnings_quality"],
        weight_in_synthesis=1.0,
    ),
    "competitive": AgentSpec(
        id="competitive",
        name="Competitive Intelligence",
        icon="swords",
        compound_searches=1,
        domain_description=(
            "Market share dynamics, direct and indirect competitors, "
            "competitive moats (switching costs, network effects, "
            "scale, IP), pricing power, product differentiation, "
            "recent competitor moves, and customer win/loss signals."
        ),
        search_queries_template=[
            "{target} competitors market share competitive landscape 2026",
            "{target} vs {industry} competition pricing strategy",
        ],
        output_sections=["market_position", "moat_assessment", "competitive_threats"],
        weight_in_synthesis=1.0,
    ),
    "news_sentiment": AgentSpec(
        id="news_sentiment",
        name="News & Analyst Sentiment",
        icon="newspaper",
        compound_searches=1,
        domain_description=(
            "Institutional narrative: analyst upgrades/downgrades, earnings call tone, major news events, "
            "CEO/CFO public statements, press releases, and sell-side consensus shifts in the last 30 days. "
            "This is the professional information layer - weighted heavily by markets."
        ),
        search_queries_template=[
            "{target} analyst upgrade downgrade earnings call news CEO statement 2026",
        ],
        output_sections=["analyst_sentiment", "news_events", "executive_tone"],
        weight_in_synthesis=1.0,
    ),
    "social_sentiment": AgentSpec(
        id="social_sentiment",
        name="Social & Retail Sentiment",
        icon="message-circle",
        compound_searches=1,
        domain_description=(
            "Retail and social layer: Reddit (r/wallstreetbets, r/stocks, r/investing), Twitter/X trending mentions, "
            "StockTwits sentiment, YouTube financial momentum, Google Trends search interest, retail options flow, "
            "and FinTok narrative presence. IMPORTANT: Social sentiment is a SECONDARY signal. It can amplify moves "
            "already supported by fundamentals but rarely drives sustained action alone."
        ),
        search_queries_template=[
            "{target} Reddit WallStreetBets social media sentiment retail options Twitter StockTwits 2026",
        ],
        output_sections=["social_buzz_level", "retail_sentiment_direction", "social_risk_flag", "momentum_signal"],
        weight_in_synthesis=0.35,
    ),
    "regulatory": AgentSpec(
        id="regulatory",
        name="Regulatory & Legal Risk",
        icon="shield-alert",
        compound_searches=1,
        domain_description=(
            "Active litigation, DOJ/FTC/SEC investigations, compliance "
            "violations, geopolitical exposure (China, Russia, Middle East), "
            "data privacy risks (GDPR, CCPA), antitrust scrutiny, "
            "government contract dependencies, and export controls."
        ),
        search_queries_template=[
            "{target} lawsuit litigation SEC DOJ FTC investigation 2026",
            "{target} regulatory compliance risk antitrust geopolitical",
        ],
        output_sections=["legal_risks", "regulatory_exposure", "geopolitical_risk"],
        weight_in_synthesis=1.0,
    ),
    "technology": AgentSpec(
        id="technology",
        name="Technology & Innovation",
        icon="cpu",
        compound_searches=1,
        domain_description=(
            "R&D spending trajectory, patent filings and grants, product "
            "roadmap announcements, engineering hiring velocity (job postings), "
            "open source activity, conference/keynote signals, technical debt "
            "indicators, and AI/automation adoption."
        ),
        search_queries_template=[
            "{target} R&D technology innovation product roadmap 2026",
            "{target} engineering hiring patents AI technology edge",
        ],
        output_sections=["innovation_pipeline", "tech_edge", "rd_quality"],
        weight_in_synthesis=1.0,
    ),
    "management": AgentSpec(
        id="management",
        name="Management & Governance",
        icon="users",
        compound_searches=1,
        domain_description=(
            "CEO/CFO track record and tenure, recent executive departures, "
            "board independence and expertise, insider buying/selling patterns, "
            "compensation alignment with shareholders, capital allocation "
            "history, and corporate governance red flags."
        ),
        search_queries_template=[
            "{target} CEO CFO executive leadership management team 2026",
            "{target} insider trading board governance compensation",
        ],
        output_sections=["leadership_quality", "governance", "capital_allocation"],
        weight_in_synthesis=1.0,
    ),
    "esg": AgentSpec(
        id="esg",
        name="ESG & Sustainability",
        icon="leaf",
        compound_searches=1,
        domain_description=(
            "Environmental footprint and carbon commitments, social "
            "controversies (labor practices, DEI, community impact), "
            "governance scores, ESG rating changes, sustainability "
            "reporting quality, and institutional ESG mandate exposure."
        ),
        search_queries_template=[
            "{target} ESG sustainability carbon environment social 2026",
        ],
        output_sections=["esg_rating", "controversies", "sustainability_trajectory"],
        weight_in_synthesis=1.0,
    ),
    "insider": AgentSpec(
        id="insider",
        name="Insider & Institutional Activity",
        icon="building",
        compound_searches=1,
        domain_description=(
            "Institutional ownership changes (13F filings), hedge fund "
            "additions and exits, short interest trajectory, options market "
            "positioning (unusual activity), insider Form 4 filings "
            "(buys vs sells), and activist investor involvement."
        ),
        search_queries_template=[
            "{target} institutional ownership hedge fund 13F short interest 2026",
        ],
        output_sections=["institutional_flows", "short_interest", "insider_transactions"],
        weight_in_synthesis=1.0,
    ),
    "growth": AgentSpec(
        id="growth",
        name="Growth & TAM Analyst",
        icon="rocket",
        compound_searches=1,
        domain_description=(
            "Total addressable market size and penetration rate, "
            "organic vs acquired growth decomposition, geographic expansion "
            "runway, new product/segment contribution, customer acquisition "
            "costs and lifetime value trends, and category growth rates."
        ),
        search_queries_template=[
            "{target} TAM market size growth opportunity expansion 2026",
            "{target} customer acquisition LTV growth rate segment",
        ],
        output_sections=["market_opportunity", "growth_decomposition", "expansion_runway"],
        weight_in_synthesis=1.0,
    ),
    "supply_chain": AgentSpec(
        id="supply_chain",
        name="Supply Chain & Operations",
        icon="factory",
        compound_searches=1,
        domain_description=(
            "Supplier concentration and single-source dependencies, "
            "manufacturing capacity and utilization, logistics network "
            "resilience, inventory management quality, geographic "
            "operational concentration risk, and cost structure flexibility."
        ),
        search_queries_template=[
            "{target} supply chain supplier manufacturing operations 2026",
            "{target} inventory logistics operational risk capacity",
        ],
        output_sections=["supply_risk", "operational_efficiency", "cost_structure"],
        weight_in_synthesis=1.0,
    ),
    "customer_quality": AgentSpec(
        id="customer_quality",
        name="Customer & Revenue Quality",
        icon="badge-dollar-sign",
        compound_searches=1,
        domain_description=(
            "Customer concentration (top 10 customers as % of revenue), "
            "net revenue retention / dollar-based retention, churn signals, "
            "contract length and renewal dynamics, enterprise vs SMB vs "
            "consumer mix, recurring vs transactional revenue quality."
        ),
        search_queries_template=[
            "{target} customer retention churn revenue quality contracts 2026",
            "{target} top customers concentration recurring revenue NRR",
        ],
        output_sections=["revenue_quality", "customer_concentration", "retention_metrics"],
        weight_in_synthesis=1.0,
    ),
    "macro": AgentSpec(
        id="macro",
        name="Macro & Sector Trends",
        icon="line-chart",
        compound_searches=1,
        domain_description=(
            "Sector tailwinds and headwinds, interest rate sensitivity "
            "(duration, floating rate debt), commodity and input cost "
            "exposure, currency risk for international revenue, policy "
            "and regulatory tailwinds, and comparable sector valuations."
        ),
        search_queries_template=[
            "{industry} sector trends macro outlook 2026 interest rates",
            "{target} sector ETF performance macro exposure currency risk",
        ],
        output_sections=["sector_dynamics", "macro_sensitivity", "policy_tailwinds"],
        weight_in_synthesis=1.0,
    ),
    "bear": AgentSpec(
        id="bear",
        name="Bear Case Specialist",
        icon="trending-down",
        compound_searches=1,
        domain_description=(
            "The strongest possible downside thesis. Short seller reports, "
            "critical analyst coverage, forensic accounting red flags, "
            "historical comparable company failures, covenant violations, "
            "addressable TAM overestimation, and management credibility gaps."
        ),
        search_queries_template=[
            "{target} short seller report bear case criticism risk 2026",
            "{target} accounting concern red flag overvalued bubble",
        ],
        output_sections=["primary_bear_thesis", "red_flags", "downside_scenarios"],
        weight_in_synthesis=1.0,
    ),
    "bull": AgentSpec(
        id="bull",
        name="Bull Case Specialist",
        icon="trending-up",
        compound_searches=1,
        domain_description=(
            "The strongest possible upside thesis. Hidden assets not in "
            "consensus models, underfollowed catalysts, optionality (new "
            "markets, products, partnerships), margin expansion levers, "
            "buyback and dividend capacity, and misunderstood competitive "
            "position."
        ),
        search_queries_template=[
            "{target} bull case catalyst upside opportunity growth 2026",
            "{target} hidden asset undervalued optionality expansion",
        ],
        output_sections=["primary_bull_thesis", "catalysts", "upside_scenarios"],
        weight_in_synthesis=1.0,
    ),
    "comparable": AgentSpec(
        id="comparable",
        name="Comparable Analysis",
        icon="git-compare",
        compound_searches=1,
        domain_description=(
            "Comparable public company analysis (comps), historical "
            "acquisition multiples for the sector, precedent transactions, "
            "peer group valuation benchmarking, and relative value "
            "assessment vs closest peers on key metrics."
        ),
        search_queries_template=[
            "{target} comparable companies peers valuation multiples sector",
            "{industry} M&A acquisition multiples precedent transactions 2025 2026",
        ],
        output_sections=["peer_comparison", "acquisition_multiples", "relative_value"],
        weight_in_synthesis=1.0,
    ),
    "product": AgentSpec(
        id="product",
        name="Product & User Experience",
        icon="package",
        compound_searches=1,
        domain_description=(
            "Product quality signals (app store ratings, review trends, "
            "NPS proxies), product roadmap execution track record, "
            "feature velocity vs competitors, developer/user community "
            "health, and platform stickiness indicators."
        ),
        search_queries_template=[
            "{target} product reviews user experience app rating NPS 2026",
        ],
        output_sections=["product_quality", "user_satisfaction", "platform_stickiness"],
        weight_in_synthesis=1.0,
    ),
    "international": AgentSpec(
        id="international",
        name="International & Emerging Markets",
        icon="globe",
        compound_searches=1,
        domain_description=(
            "International revenue mix and growth by geography, emerging "
            "market penetration strategy, foreign regulatory risk, "
            "currency hedging strategy, local competition intensity, "
            "and geopolitical risk by region."
        ),
        search_queries_template=[
            "{target} international revenue global expansion emerging markets 2026",
        ],
        output_sections=["geographic_mix", "international_growth", "em_exposure"],
        weight_in_synthesis=1.0,
    ),
    "synthesis_judge": AgentSpec(
        id="synthesis_judge",
        name="Synthesis Judge",
        icon="scale",
        compound_searches=0,
        domain_description=(
            "Synthesize all specialist findings into a rigorous, "
            "structured investment memo with a clear verdict."
        ),
        search_queries_template=[],
        output_sections=["verdict", "memo"],
        weight_in_synthesis=1.0,
    ),
}

CROSS_EXAM_PAIRS: list[tuple[str, str]] = [
    ("financial", "bear"),
    ("financial", "bull"),
    ("competitive", "growth"),
    ("regulatory", "management"),
    ("technology", "competitive"),
    ("news_sentiment", "bear"),
    ("macro", "financial"),
    ("customer_quality", "growth"),
]

FOCUS_PRIORITIES = {
    "financial": ["financial", "growth", "customer_quality", "management", "comparable"],
    "competitive": ["competitive", "technology", "product", "growth", "comparable"],
    "risk": ["regulatory", "bear", "macro", "supply_chain", "management"],
    "opportunity": ["bull", "growth", "technology", "financial", "international"],
}


def _effective_compound_calls(spec: AgentSpec) -> int:
    if spec.id == "synthesis_judge":
        return 0
    if cfg.compound_searches_override >= 0:
        return int(cfg.compound_searches_override)
    return int(spec.compound_searches or cfg.default_compound_calls_per_agent)


def _current_depth_config() -> dict[str, dict[str, Any]]:
    return {
        "quick": {
            "agents": get_depth_agent_ids("quick"),
            "total_compound_calls": int(cfg.quick_compound_calls),
            "description": "Core research only",
            "est_minutes": 2,
        },
        "standard": {
            "agents": get_depth_agent_ids("standard"),
            "total_compound_calls": int(cfg.standard_compound_calls),
            "description": "Full institutional analysis",
            "est_minutes": 6,
        },
        "deep": {
            "agents": get_depth_agent_ids("deep"),
            "total_compound_calls": int(cfg.deep_compound_calls),
            "description": "Comprehensive deep dive",
            "est_minutes": 12,
        },
    }


DEPTH_CONFIG: dict[str, dict[str, Any]] = _current_depth_config()


def refresh_depth_config() -> dict[str, dict[str, Any]]:
    global DEPTH_CONFIG
    DEPTH_CONFIG = _current_depth_config()
    return DEPTH_CONFIG


def get_agent(agent_id: str) -> AgentSpec:
    spec = AGENTS[agent_id]
    weight = cfg.social_synthesis_weight if agent_id == "social_sentiment" else spec.weight_in_synthesis
    searches = _effective_compound_calls(spec)
    return replace(spec, weight_in_synthesis=weight, compound_searches=searches)


def list_research_agents() -> list[AgentSpec]:
    return [get_agent(aid) for aid in AGENTS if aid != "synthesis_judge"]


def resolve_agent_ids(depth: str, focus: str = "all-around", custom_agent_ids: list[str] | None = None) -> list[str]:
    active_depths = refresh_depth_config()
    d = (depth or "standard").lower()
    if d == "custom":
        return [a for a in (custom_agent_ids or []) if a in AGENTS and a != "synthesis_judge"]

    agent_ids = list(active_depths.get(d, active_depths["standard"])["agents"])
    f = (focus or cfg.default_focus or "all-around").lower()
    if f in FOCUS_PRIORITIES:
        rank = {aid: idx for idx, aid in enumerate(FOCUS_PRIORITIES[f])}
        agent_ids = sorted(agent_ids, key=lambda aid: rank.get(aid, 999))
    return agent_ids


def get_depth_required_calls(depth: str, custom_agent_ids: list[str] | None = None) -> int:
    active_depths = refresh_depth_config()
    if (depth or "").lower() == "custom":
        return sum(get_agent(aid).compound_searches for aid in (custom_agent_ids or []) if aid in AGENTS)
    return int(active_depths.get(depth, active_depths["standard"])["total_compound_calls"])


def get_relevant_pairs(agent_ids: list[str], depth: str) -> list[tuple[str, str]]:
    active = set(agent_ids)
    pairs = [(a, b) for (a, b) in CROSS_EXAM_PAIRS if a in active and b in active]
    return pairs[: max(int(cfg.max_cross_exam_pairs), 0)]


def build_combined_query(agent: AgentSpec, target: str, industry: str) -> str:
    if not agent.search_queries_template:
        return f"{target} {agent.name} latest data"
    rendered = [q.format(target=target, industry=industry) for q in agent.search_queries_template]
    # Use only the first query — joining multiple with " | " inflates prompt size
    # and can push compound models over their input token limit (413 error)
    return rendered[0]


ANTI_HALLUCINATION_RULES = (
    "ANTI-HALLUCINATION RULES - READ FIRST:\n"
    "1. ONLY report information you found in your web search results. Never use training data as a source.\n"
    "2. Every specific fact (number, date, name, percentage, price, rating) MUST be attributed to a source.\n"
    "3. If not found, write 'Not found in search results' - never guess.\n"
    "4. If source is older than 6 months, flag '[possibly outdated - from DATE]'.\n"
    "5. Never invent analyst names, targets, ratings, or executive facts.\n"
    "6. Never state stock price, revenue, or earnings without source attribution.\n"
    "7. You are a researcher, not an extrapolator."
)


def build_research_prompts(
    *,
    target: str,
    industry: str,
    agent: AgentSpec,
    specific_questions: str,
    context: str,
) -> tuple[str, str, str]:
    query = build_combined_query(agent, target, industry)
    today_date = date.today().strftime("%B %d, %Y")
    date_rules = (
        f"DATE RECENCY RULES:\nToday's date is {today_date}.\n"
        "1. Prefer sources from the last 90 days whenever possible.\n"
        "2. If information is older than 6 months, flag '[OLDER DATA - from DATE]'.\n"
        "3. If a source describes a pending future event, verify whether newer sources confirm the outcome.\n"
    )
    if agent.id == "news_sentiment":
        date_rules += (
            "4. For news_sentiment: ONLY report news from the last 30 days. "
            "Discard older articles even if they seem relevant.\n"
        )

    if agent.id == "social_sentiment":
        system = (
            "You are the Social & Retail Sentiment analyst. Your job is to accurately report the social signal, NOT to hype it. "
            "Social sentiment is a secondary, noisy signal. You must: "
            "1. Report what you found factually "
            "2. Explicitly state the Market Impact Estimate "
            "3. Never claim social sentiment alone drives price action "
            "4. Always add the Catalyst Needed field "
            "5. Default Market Impact Estimate to MINOR unless concrete extreme activity evidence exists.\n\n"
            f"{ANTI_HALLUCINATION_RULES}\n\n"
            f"{date_rules}\n"
            "Return findings in this EXACT format:\n"
            "## SOCIAL_BUZZ_LEVEL\n"
            "- Level: HIGH | MEDIUM | LOW | MINIMAL\n"
            "- Trend: RISING | STABLE | FALLING\n"
            "- Primary platforms: [list]\n\n"
            "## RETAIL_SENTIMENT_DIRECTION\n"
            "- Direction: BULLISH | BEARISH | MIXED | NEUTRAL\n"
            "- Intensity: EXTREME | STRONG | MODERATE | MILD\n"
            "- Key themes: [2-3 bullets]\n\n"
            "## SOCIAL_RISK_FLAG\n"
            "- Meme stock risk: YES | NO | POSSIBLE\n"
            "- Short squeeze potential: YES | NO | POSSIBLE\n"
            "- FOMO driven: YES | NO | POSSIBLE\n\n"
            "## MOMENTUM_SIGNAL\n"
            "- 7-day trend: [direction]\n"
            "- Market impact estimate: MINOR | MODERATE | AMPLIFYING\n"
            "- Catalyst needed to sustain: [fundamental catalyst]\n\n"
            "## CONFIDENCE\n"
            "LOW - social data is noisy. Verify against fundamentals before acting."
        )
    else:
        sections = "\n".join(f"## {name.upper()}" for name in agent.output_sections)
        competitor_rules = ""
        if agent.id == "competitive":
            competitor_rules = (
                "COMPETITOR RELEVANCE RULES:\n"
                "Only include direct competitors competing for the same customer spend.\n"
                f"Sanity-check: would a customer choose between {target} and this company for the same need?\n\n"
            )
        # Cap domain_description to avoid 413 on compound models (keep under ~300 chars)
        domain_short = agent.domain_description[:300].rstrip()
        system = (
            f"You are a specialist {agent.name} analyst. Focus ONLY on {domain_short}. "
            "One search call — make it count. Be concise. Max 50 words per section.\n\n"
            f"{ANTI_HALLUCINATION_RULES}\n\n"
            f"{date_rules}\n"
            f"{competitor_rules}"
            f"{sections}\n"
            "- Bullet 1 (max 20 words, specific fact + source)\n"
            "- Bullet 2\n"
            "- Bullet 3\n\n"
            "## CONFIDENCE\n"
            "High | Medium | Low — one word, one sentence reason.\n\n"
            "## TOP_FINDING\n"
            "One sentence: the single most important thing found."
        )

    user = (
        f"TARGET: {target}\n"
        f"QUERY: {query}\n"
        f"QUESTIONS: {(specific_questions or 'None')[:200]}\n"
        f"CONTEXT: {(context or 'None')[:400]}\n"
        "Include source URLs inline."
    )
    return system, user, query


def build_cross_exam_prompts(
    *,
    agent_a_name: str,
    agent_b_name: str,
    agent_a_findings: str,
    agent_b_findings: str,
) -> tuple[str, str]:
    system = (
        "You are a forensic cross-examination engine for investment research. "
        "Surface contradictions, not summaries. Prefer concrete conflicts in numbers, dates, guidance, valuation, "
        "or causality. If both can be true, classify as interpretation gap instead of contradiction."
    )
    user = (
        f"A ({agent_a_name}):\n{agent_a_findings[:800]}\n\n"
        f"B ({agent_b_name}):\n{agent_b_findings[:800]}\n\n"
        "Return exactly these sections:\n"
        "NUMERICAL_CONTRADICTIONS:\n"
        "- <number/date from A> vs <number/date from B> + why conflict\n"
        "- ...\n\n"
        "DATE_CONFLICTS:\n"
        "- <event/date mismatch> + why it matters\n"
        "- ...\n\n"
        "COMPETING_INTERPRETATIONS:\n"
        "- <same fact> interpreted differently by A vs B\n"
        "- ...\n\n"
        "WHAT_TO_VERIFY_NEXT:\n"
        "- <specific filing/metric/date check>\n"
        "- ...\n\n"
        "Rules:\n"
        "- Include 1-3 bullets per section.\n"
        "- Quote exact values/dates when present.\n"
        "- If none, write '- None found'."
    )
    return system, user
