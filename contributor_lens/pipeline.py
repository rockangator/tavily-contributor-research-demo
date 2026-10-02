from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

from .github_client import GitHubClient
from .models import (
    ContributorAssessment,
    ContributorProfile,
    EvidenceItem,
    RepoAssessment,
    RepoRef,
    RepositoryMetadata,
)
from .scoring import METHODOLOGY_VERSION, assess_contributor, priority_rank
from .tavily_client import TavilyEnricher


def analyze_repository(
    repo: RepoRef,
    top_n: int,
    github_token: str | None,
    tavily_api_key: str,
    tavily_project_id: str | None = None,
    deep_extract: bool = False,
) -> RepoAssessment:
    github = GitHubClient(token=github_token)
    errors: list[str] = []
    try:
        repository = github.get_repository(repo)
        profiles = github.get_contributors(repo, limit=top_n)
        enricher = TavilyEnricher(api_key=tavily_api_key, project_id=tavily_project_id)
        assessments: list[ContributorAssessment] = []

        workers = min(5, max(1, len(profiles)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_profile = {
                pool.submit(enricher.enrich, profile, repo, deep_extract): profile for profile in profiles
            }
            for future in as_completed(future_to_profile):
                profile = future_to_profile[future]
                try:
                    evidence, request_ids, queries = future.result()
                    assessments.append(assess_contributor(profile, evidence, request_ids, queries))
                except Exception as exc:
                    message = f"{profile.login}: {exc}"
                    errors.append(message)
                    assessments.append(assess_contributor(profile, [], error=str(exc)))

        assessments.sort(key=lambda item: (priority_rank(item.review_priority), -item.profile.contributions))
        return RepoAssessment(
            repository=repository,
            contributors=assessments,
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_mode="live",
            methodology_version=METHODOLOGY_VERSION,
            errors=errors,
            github_rate_limit_remaining=github.rate_limit_remaining,
        )
    finally:
        github.close()


def load_fixture(path: str | Path) -> RepoAssessment:
    payload = json.loads(Path(path).read_text())
    repository = RepositoryMetadata(**payload["repository"])
    assessments: list[ContributorAssessment] = []
    profile_keys = {field.name for field in fields(ContributorProfile)}
    evidence_keys = {field.name for field in fields(EvidenceItem)}
    for row in payload["contributors"]:
        profile = ContributorProfile(**{key: value for key, value in row["profile"].items() if key in profile_keys})
        evidence = [
            EvidenceItem(**{key: value for key, value in item.items() if key in evidence_keys})
            for item in row.get("evidence", [])
        ]
        assessments.append(
            ContributorAssessment(
                profile=profile,
                evidence=evidence,
                identity_confidence=row["identity_confidence"],
                evidence_coverage=row["evidence_coverage"],
                review_priority=row["review_priority"],
                reasons=row.get("reasons", []),
                caveats=row.get("caveats", []),
                tavily_request_ids=row.get("tavily_request_ids", []),
                search_queries=row.get("search_queries", []),
                error=row.get("error"),
            )
        )
    return RepoAssessment(
        repository=repository,
        contributors=assessments,
        generated_at=payload["generated_at"],
        source_mode=payload.get("source_mode", "offline"),
        methodology_version=payload.get("methodology_version", METHODOLOGY_VERSION),
        errors=payload.get("errors", []),
        github_rate_limit_remaining=payload.get("github_rate_limit_remaining"),
        synthetic=payload.get("synthetic", True),
    )


def save_assessment(assessment: RepoAssessment, path: str | Path) -> None:
    """Persist a sanitized report. API keys are never part of RepoAssessment."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(json.dumps(asdict(assessment), indent=2) + "\n")
    temporary.replace(destination)
