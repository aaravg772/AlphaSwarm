from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import os

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "backend" / "alphaswarm_config.json"


@dataclass
class AlphaConfig:
    research_model: str = "compound-beta"
    cross_exam_model: str = "llama-3.1-8b-instant"
    synthesis_model: str = "llama-3.3-70b-versatile"
    social_model: str = "compound-beta"
    research_fallback_model: str = "llama-3.1-8b-instant"
    research_temperature: float = 0.2
    synthesis_temperature: float = 0.1
    cross_exam_temperature: float = 0.15

    research_max_tokens: int = 1200
    cross_exam_max_tokens: int = 600
    synthesis_max_tokens: int = 5000
    social_max_tokens: int = 800
    connection_test_max_tokens: int = 20

    daily_compound_limit: int = 250
    budget_warning_threshold: int = 50
    budget_hard_floor: int = 5

    default_depth: str = "standard"
    default_focus: str = "all"
    compound_searches_override: int = -1

    phase1_enabled: bool = True
    phase2_cross_exam_enabled: bool = True
    phase3_synthesis_enabled: bool = True
    # Technical analysis phase — always runs for public companies, no Groq budget used
    phase_technical_enabled: bool = True
    skip_cross_exam_for_quick: bool = True
    max_cross_exam_pairs: int = 5

    cache_enabled: bool = True
    cache_ttl_hours: int = 6
    cache_max_entries: int = 200
    cache_persist_to_disk: bool = True

    max_findings_chars_synthesis: int = 1200
    max_ta_chars_synthesis: int = 500
    max_context_chars: int = 2000
    max_cross_exam_chars: int = 2400
    strip_markdown_for_synthesis: bool = True

    hallucination_guard_enabled: bool = True
    min_sources_for_low_risk: int = 1
    medium_risk_claim_threshold: int = 1
    high_risk_claim_threshold: int = 3
    block_high_risk_findings: bool = False
    prefix_medium_risk_findings: bool = True
    fail_on_zero_sources: bool = False

    social_max_score_adjustment: float = 0.5
    social_synthesis_weight: float = 0.35
    social_min_buzz_for_influence: str = "HIGH"
    social_min_impact_for_influence: str = "AMPLIFYING"

    memo_key_findings_count: int = 8
    memo_bull_thesis_count: int = 5
    memo_bear_thesis_count: int = 5
    memo_key_risks_count: int = 5
    memo_catalysts_count: int = 5
    memo_summary_max_words: int = 200
    memo_prediction_max_words: int = 120
    memo_include_social_signal: bool = True
    memo_validation_enabled: bool = True

    max_retries_on_429: int = 2
    retry_delay_buffer_seconds: float = 2.0
    synthesis_max_retries: int = 3
    continue_on_agent_failure: bool = True

    default_compound_calls_per_agent: int = 1

    quick_compound_calls: int = 3
    standard_compound_calls: int = 10
    deep_compound_calls: int = 18

    quick_agent_ids: str = "financial,competitive,news_sentiment"
    standard_agent_ids: str = (
        "financial,competitive,news_sentiment,"
        "regulatory,technology,management,"
        "esg,insider,growth,social_sentiment"
    )
    deep_agent_ids: str = (
        "financial,competitive,news_sentiment,"
        "regulatory,technology,management,"
        "esg,insider,growth,social_sentiment,"
        "supply_chain,customer_quality,macro,"
        "bear,bull,comparable,product,international"
    )

    verbose_logging: bool = False
    port: int = 8001


cfg: AlphaConfig = AlphaConfig()


def load_config() -> None:
    global cfg
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for key, value in saved.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        except Exception as e:
            print(f"[CONFIG] Failed to load config: {e}")
            print("[CONFIG] Using defaults")


def save_config(updates: dict) -> None:
    global cfg
    for key, value in updates.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)


def reset_config() -> None:
    global cfg
    cfg = AlphaConfig()
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    save_config({})


def get_config_dict() -> dict:
    return asdict(cfg)


def get_depth_agent_ids(depth: str) -> list:
    mapping = {
        "quick": cfg.quick_agent_ids,
        "standard": cfg.standard_agent_ids,
        "deep": cfg.deep_agent_ids,
    }
    raw = mapping.get(depth, cfg.standard_agent_ids)
    return [x.strip() for x in raw.split(",") if x.strip()]


load_config()
