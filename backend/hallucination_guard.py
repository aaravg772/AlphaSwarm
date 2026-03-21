from __future__ import annotations

import re
from typing import Any

from .config import cfg
from .logger import logger

CLAIM_PATTERNS = [
    r"\$[\d,]+(?:\.\d+)?[BMK]?",
    r"\d+\.?\d*\s*%",
    r"(?:Q[1-4]|FY)\s*\d{4}",
    r"\d+x",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:CEO|CFO|CTO|COO)\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
]

TRAINING_DATA_PHRASES = [
    "as of my knowledge",
    "based on my training",
    "i believe",
    "i think",
    "typically",
    "historically",
    "in general",
    "usually",
    "it is known that",
    "commonly",
    "as is well known",
    "as everyone knows",
]


def scan_for_hallucination_risk(
    findings: str,
    sources: list[Any],
    agent_name: str,
) -> dict[str, Any]:
    if not cfg.hallucination_guard_enabled:
        return {"risk_level": "LOW", "issues": [], "warnings": [], "unsourced_claims": 0}

    issues: list[str] = []
    warnings: list[str] = []

    findings_lower = (findings or "").lower()
    for phrase in TRAINING_DATA_PHRASES:
        if phrase in findings_lower:
            warnings.append(f"Possible training data language: '{phrase}'")

    for pattern in CLAIM_PATTERNS:
        matches = re.findall(pattern, findings or "")
        for match in matches:
            idx = (findings or "").find(match)
            context = (findings or "")[max(0, idx - 100) : idx + 100]
            has_source = any(
                [
                    "http" in context,
                    "source:" in context.lower(),
                    "according to" in context.lower(),
                    "per " in context.lower(),
                    "reported by" in context.lower(),
                    "via " in context.lower(),
                ]
            )
            if not has_source:
                issues.append(f"Unsourced claim: '{match}'")

    if len(sources) < int(cfg.min_sources_for_low_risk) and len(issues) > 0:
        issues.append(
            "CRITICAL: Specific claims made but too few web sources returned. Findings may rely on training data."
        )

    if cfg.fail_on_zero_sources and len(sources) == 0:
        issues.append("CRITICAL: Zero sources returned and strict mode fail_on_zero_sources is enabled.")

    risk_level = (
        "HIGH"
        if len(issues) >= int(cfg.high_risk_claim_threshold) or any("CRITICAL" in issue for issue in issues)
        else "MEDIUM"
        if len(issues) >= int(cfg.medium_risk_claim_threshold) or len(warnings) >= int(cfg.medium_risk_claim_threshold)
        else "LOW"
    )

    logger.log_hallucination_scan(
        agent_name=agent_name,
        risk_level=risk_level,
        unsourced_count=len(issues),
        warning_count=len(warnings),
    )

    if risk_level in ("HIGH", "MEDIUM"):
        logger.log_warn(
            f"Hallucination risk {risk_level} for {agent_name}: {len(issues)} unsourced claims"
        )

    return {
        "risk_level": risk_level,
        "issues": issues,
        "warnings": warnings,
        "unsourced_claims": len(issues),
    }


def prepare_findings_for_synthesis(agent_results: dict[str, Any]) -> dict[str, str]:
    prepared: dict[str, str] = {}
    for agent_id, result in agent_results.items():
        risk = result.get("hallucination_check", {})
        risk_level = risk.get("risk_level", "LOW")
        findings = result.get("findings", "")

        if risk_level == "HIGH" and cfg.block_high_risk_findings:
            prepared[agent_id] = (
                f"[WARNING: {agent_id} findings blocked due to HIGH hallucination risk - "
                f"{risk.get('unsourced_claims', 0)} unsourced claims.]"
            )
            logger.log_hallucination_filtered(agent_id, "HIGH risk blocked")
        elif risk_level == "HIGH":
            prepared[agent_id] = (
                f"[WARNING: {agent_id} findings flagged HIGH hallucination risk - "
                f"{risk.get('unsourced_claims', 0)} unsourced claims. Treat with caution. "
                f"Original findings: {findings[: cfg.max_cross_exam_chars]}...]"
            )
            logger.log_hallucination_filtered(agent_id, "HIGH risk prefix")
        elif risk_level == "MEDIUM" and cfg.prefix_medium_risk_findings:
            prepared[agent_id] = f"[NOTE: some claims unverified] {findings}"
            logger.log_hallucination_filtered(agent_id, "MEDIUM risk prefix")
        else:
            prepared[agent_id] = findings
    return prepared


def validate_memo(memo: dict[str, Any], agent_results: dict[str, Any]) -> dict[str, Any]:
    if not cfg.memo_validation_enabled:
        memo.setdefault("validation_warnings", [])
        return memo

    all_findings_text = " ".join(r.get("findings", "") for r in agent_results.values())
    issues: list[str] = []

    snapshot = memo.get("financial_snapshot", {})
    for field, value in snapshot.items():
        if value and value != "Not found":
            numbers = re.findall(r"\d+\.?\d*", str(value))
            for num in numbers:
                if len(num) >= 2 and num not in all_findings_text:
                    issues.append(
                        f"financial_snapshot.{field} value '{value}' not found in any agent findings"
                    )

    computed_majority = memo.get("majority_raw")
    verdict = memo.get("verdict")
    if computed_majority == "BEARISH" and verdict == "BULLISH":
        if not memo.get("social_signal", {}).get("influenced_verdict"):
            issues.append(
                "VERDICT MISMATCH: verdict is BULLISH but raw majority is BEARISH without social sentiment justification"
            )

    if issues:
        memo["validation_warnings"] = issues
        logger.log_memo_validation(issues_count=len(issues), passed=False)
        for issue in issues:
            logger.log_warn(f"  -> {issue}")
    else:
        memo["validation_warnings"] = []
        logger.log_memo_validation(issues_count=0, passed=True)

    return memo
