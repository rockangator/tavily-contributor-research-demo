from __future__ import annotations

import json
from typing import Any

from .models import ContributorAssessment, EvidenceItem, RepoAssessment


SCHEMA_VERSION = "0.3"


def _public_source_result(item: ContributorAssessment) -> dict[str, Any]:
    exact_matches = sum(evidence.identity_match == "exact" for evidence in item.evidence)
    probable_matches = sum(evidence.identity_match == "probable" for evidence in item.evidence)
    retained_sources = len(item.evidence)
    searches_attempted = len(item.search_queries)

    if item.error:
        outcome = "Search incomplete"
        explanation = (
            "At least one public-source search did not complete. Review the reported error "
            "and rerun the analysis before treating this source set as complete."
        )
    elif retained_sources == 0:
        outcome = "No retained matches"
        explanation = (
            f"{searches_attempted} public-source search"
            f"{'es were' if searches_attempted != 1 else ' was'} attempted, but no result "
            "contained enough identity details to retain. This is not a negative finding "
            "about the contributor."
        )
    elif exact_matches:
        outcome = "Exact match found"
        explanation = (
            f"{exact_matches} retained source{'s' if exact_matches != 1 else ''} included "
            "the GitHub handle plus another identity detail."
        )
    else:
        outcome = "Probable match only"
        explanation = (
            f"{probable_matches or retained_sources} retained source"
            f"{'s were' if (probable_matches or retained_sources) != 1 else ' was'} a probable "
            "identity match and should be confirmed before use."
        )

    result: dict[str, Any] = {
        "outcome": outcome,
        "explanation": explanation,
        "searchesAttempted": searches_attempted,
        "retainedSourceCount": retained_sources,
        "identityMatchCounts": {
            "exact": exact_matches,
            "probable": probable_matches,
        },
    }
    if item.error:
        result["searchError"] = item.error
    return result


def _evidence_record(evidence: EvidenceItem, synthetic: bool) -> dict[str, Any]:
    record: dict[str, Any] = {
        "title": evidence.title,
        "sourceDomain": evidence.source_domain,
        "identityMatch": evidence.identity_match,
        "category": evidence.category,
        "excerpt": evidence.excerpt,
    }
    if not synthetic:
        record["url"] = evidence.url
        record["searchRelevance"] = evidence.relevance
        record["focusedExtractionUsed"] = evidence.extracted
    return record


def _contributor_record(
    item: ContributorAssessment,
    synthetic: bool,
    source_mode: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "githubLogin": item.profile.login,
        "displayName": item.profile.display_name,
        "commitsInRepository": item.profile.contributions,
        "publicSourceResult": _public_source_result(item),
        "reasons": item.reasons,
        "evidence": [_evidence_record(evidence, synthetic) for evidence in item.evidence],
        "trace": {
            "type": (
                "illustrative-query-plan"
                if synthetic
                else "saved-source-trace"
                if source_mode == "snapshot"
                else "live-search-trace"
            ),
            "queries": item.search_queries,
        },
    }
    if not synthetic:
        record["githubUrl"] = item.profile.html_url
    if source_mode == "live":
        record["trace"]["tavilyRequestIds"] = item.tavily_request_ids
    return record


def build_sbom_sidecar(assessment: RepoAssessment) -> dict[str, Any]:
    """Build the portable contributor-evidence report used by the demo."""
    repository: dict[str, Any] = {
        "name": assessment.repository.full_name,
        "defaultBranch": assessment.repository.default_branch,
        "license": assessment.repository.license_name,
    }
    if not assessment.synthetic:
        repository["url"] = assessment.repository.html_url

    return {
        "schemaVersion": SCHEMA_VERSION,
        "documentType": "contributor-evidence-report",
        "dataClassification": (
            "fictional-demo"
            if assessment.synthetic
            else "saved-public-data"
            if assessment.source_mode == "snapshot"
            else "live-public-data"
        ),
        "sourceMode": assessment.source_mode,
        "methodologyVersion": assessment.methodology_version,
        "generatedAt": assessment.generated_at,
        "repository": repository,
        "scope": {
            "statement": "Public-source search results for selected repository contributors",
            "interpretation": (
                "Each outcome reports what the public-source search retained after identity "
                "matching. No retained matches is not a negative finding about a contributor. "
                "Search incomplete means at least one request failed."
            ),
            "excludes": [
                "malicious intent or contributor behavior",
                "citizenship, nationality, immigration status, or U.S.-person eligibility",
            ],
        },
        "resultDefinitions": {
            "Exact match found": (
                "At least one retained source includes the GitHub handle plus another "
                "identity detail."
            ),
            "Probable match only": (
                "Retained sources contain fewer identity details and require confirmation."
            ),
            "No retained matches": (
                "Searches completed, but no result contained enough identity details to retain."
            ),
            "Search incomplete": "At least one public-source search request failed.",
        },
        "contributors": [
            _contributor_record(item, assessment.synthetic, assessment.source_mode)
            for item in assessment.contributors
        ],
        "errors": assessment.errors,
    }


def sidecar_json(assessment: RepoAssessment) -> str:
    return json.dumps(build_sbom_sidecar(assessment), indent=2, sort_keys=False)
