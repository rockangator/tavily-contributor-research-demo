from __future__ import annotations

from .models import ContributorAssessment, ContributorProfile, EvidenceItem


METHODOLOGY_VERSION = "0.1.0"


def assess_contributor(
    profile: ContributorProfile,
    evidence: list[EvidenceItem],
    request_ids: list[str] | None = None,
    search_queries: list[str] | None = None,
    error: str | None = None,
) -> ContributorAssessment:
    exact = sum(item.identity_match == "exact" for item in evidence)
    probable = sum(item.identity_match == "probable" for item in evidence)
    domains = {item.source_domain for item in evidence}

    identity_confidence = min(
        100,
        exact * 35 + probable * 18 + min(15, max(0, len(domains) - 1) * 5),
    )

    profile_fields = [profile.name, profile.bio, profile.company, profile.location, profile.blog]
    completeness = round(25 * sum(bool(field) for field in profile_fields) / len(profile_fields))
    age = profile.account_age_years
    maturity = 15 if age is not None and age >= 5 else 10 if age is not None and age >= 2 else 5 if age else 0
    activity_context = min(20, 5 + min(profile.public_repos, 50) // 5 + min(profile.followers, 100) // 20)
    external = min(40, exact * 14 + probable * 7 + min(12, len(domains) * 4))
    evidence_coverage = min(100, completeness + maturity + activity_context + external)

    reasons: list[str] = []
    if not evidence:
        reasons.append("No external source contained enough identity details to be retained")
    elif exact == 0:
        reasons.append("The retained source is a probable identity match and needs confirmation")
    else:
        reasons.append(
            f"{exact} source{'s' if exact != 1 else ''} included the GitHub identity plus matching context"
        )
    if len(domains) == 1:
        reasons.append("All retained sources came from one public domain")
    else:
        if len(domains) > 1:
            reasons.append(f"Retained sources span {len(domains)} public domains")
    if not profile.name or not profile.bio:
        reasons.append("The GitHub profile is missing a full name or bio, reducing identity context")
    if error:
        reasons.append("Enrichment was incomplete because an external request failed")

    if evidence_coverage < 40 or identity_confidence < 30:
        priority = "High"
    elif evidence_coverage < 70 or identity_confidence < 65:
        priority = "Medium"
    else:
        priority = "Low"

    caveats = [
        "The public-source outcome describes retained search results, not contributor behavior.",
        "Public-source results can be incomplete or out of date.",
        "A human reviewer should confirm identity matches before using retained sources.",
    ]

    return ContributorAssessment(
        profile=profile,
        evidence=evidence,
        identity_confidence=identity_confidence,
        evidence_coverage=evidence_coverage,
        review_priority=priority,
        reasons=reasons,
        caveats=caveats,
        tavily_request_ids=request_ids or [],
        search_queries=search_queries or [],
        error=error,
    )


def priority_rank(value: str) -> int:
    return {"High": 0, "Medium": 1, "Low": 2}.get(value, 3)
