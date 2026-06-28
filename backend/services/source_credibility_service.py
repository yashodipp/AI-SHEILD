from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from backend.utils.scoring import clamp

try:
    import whois
except Exception:  # pragma: no cover - optional dependency
    whois = None


SOURCE_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "source_reputation.json"


def _load_source_reputation() -> dict[str, Any]:
    if not SOURCE_DATA_PATH.exists():
        return {
            "trusted_domains": {},
            "risky_domains": {},
            "known_domain_ages": {},
            "suspicious_tlds": [],
        }

    return json.loads(SOURCE_DATA_PATH.read_text(encoding="utf-8"))


SOURCE_REPUTATION = _load_source_reputation()


def normalize_domain(url: str) -> tuple[str, str]:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = (parsed.netloc or parsed.path).strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split(":")[0], parsed.scheme or "https"


def domain_age_years(domain: str) -> Optional[int]:
    known_ages = SOURCE_REPUTATION.get("known_domain_ages", {})
    if domain in known_ages:
        return int(known_ages[domain])

    if os.getenv("AI_SHIELD_DEEP_SOURCE_CHECK", "false").lower() != "true":
        return None

    if whois is None:
        return None

    try:
        record = whois.whois(domain)
        creation_date = getattr(record, "creation_date", None)
        if isinstance(creation_date, list):
            creation_date = creation_date[0]
        if creation_date is None:
            return None
        comparison_now = datetime.now(tz=creation_date.tzinfo or timezone.utc)
        age_days = (comparison_now - creation_date).days
        return max(0, age_days // 365)
    except Exception:
        return None


def analyze_source_credibility(url: str) -> dict[str, Any]:
    domain, scheme = normalize_domain(url)
    if not domain:
        return {
            "available": False,
            "domain": "",
            "score": 0.5,
            "trust_level": "unknown",
            "https": False,
            "age_years": None,
            "reasons": ["No valid domain could be extracted from the submitted URL."],
        }

    trusted_domains = SOURCE_REPUTATION.get("trusted_domains", {})
    risky_domains = SOURCE_REPUTATION.get("risky_domains", {})
    suspicious_tlds = SOURCE_REPUTATION.get("suspicious_tlds", [])

    trusted_match = next((name for name in trusted_domains if domain == name or domain.endswith(f".{name}")), None)
    risky_match = next((name for name in risky_domains if domain == name or domain.endswith(f".{name}")), None)
    age_years = domain_age_years(domain)
    https_enabled = scheme == "https"

    score = 0.52
    reasons: list[str] = []

    if https_enabled:
        score += 0.08
        reasons.append("HTTPS is enabled for the submitted source.")
    else:
        score -= 0.1
        reasons.append("The submitted source does not use HTTPS.")

    if trusted_match:
        tier = trusted_domains[trusted_match].get("tier", "high")
        score += 0.22 if tier == "high" else 0.12
        reasons.append(f"The source matches a trusted domain in the credibility database: {trusted_match}.")

    if risky_match:
        score -= 0.28
        reasons.append(f"The source matches a high-risk or untrusted domain in the watchlist: {risky_match}.")

    if any(domain.endswith(tld) for tld in suspicious_tlds):
        score -= 0.08
        reasons.append("The domain uses a TLD commonly associated with low-trust or spammy websites.")

    if age_years is not None:
        if age_years >= 10:
            score += 0.1
            reasons.append(f"The domain has a mature presence ({age_years} years).")
        elif age_years >= 3:
            score += 0.04
            reasons.append(f"The domain is at least a few years old ({age_years} years).")
        else:
            score -= 0.08
            reasons.append(f"The domain appears very new ({age_years} years), which increases risk.")
    else:
        reasons.append("Domain age could not be verified automatically, so age trust signals are limited.")

    if domain.count(".") >= 3:
        score -= 0.03
        reasons.append("The URL uses a deep subdomain structure, which can sometimes indicate impersonation.")

    final_score = round(clamp(score, 0.05, 0.98), 2)
    if final_score >= 0.78:
        trust_level = "high"
    elif final_score >= 0.55:
        trust_level = "medium"
    else:
        trust_level = "low"

    return {
        "available": True,
        "domain": domain,
        "score": final_score,
        "trust_level": trust_level,
        "https": https_enabled,
        "age_years": age_years,
        "trusted_match": trusted_match,
        "risky_match": risky_match,
        "reasons": reasons,
    }
