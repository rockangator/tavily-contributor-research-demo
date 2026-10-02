import json
from datetime import datetime, timezone

from contributor_lens.export import build_sbom_sidecar, sidecar_json
from contributor_lens.models import (
    ContributorAssessment,
    ContributorProfile,
    EvidenceItem,
    RepoAssessment,
    RepositoryMetadata,
)
from contributor_lens.scoring import assess_contributor


def build_test_assessment():
    def profile(login: str) -> ContributorProfile:
        return ContributorProfile(
            login=login,
            html_url=f"https://github.com/{login}",
            contributions=12,
            name=login.replace("-", " ").title(),
            bio="Test fixture profile.",
        )

    exact_sources = [
        EvidenceItem(
            title=f"Contributor Alpha source {index}",
            url=f"https://source-{index}.invalid/contributors/alpha",
            excerpt="Synthetic source used by an offline unit test.",
            source_domain=f"source-{index}.invalid",
            identity_match="exact",
            category="Test source",
        )
        for index in range(1, 4)
    ]
    probable_source = EvidenceItem(
        title="Contributor Beta source",
        url="https://source.invalid/contributors/beta",
        excerpt="Synthetic source used by an offline unit test.",
        source_domain="source.invalid",
        identity_match="probable",
        category="Test source",
    )
    contributors = [
        assess_contributor(
            profile("contributor-alpha"),
            exact_sources,
            request_ids=["test-search-1"],
            search_queries=['"contributor-alpha" test repository'],
        ),
        assess_contributor(
            profile("contributor-beta"),
            [probable_source],
            search_queries=['"contributor-beta" test repository'],
        ),
        assess_contributor(
            profile("contributor-gamma"),
            [],
            search_queries=['"contributor-gamma" test repository', '"contributor-gamma" GitHub'],
        ),
    ]
    return RepoAssessment(
        repository=RepositoryMetadata(
            full_name="test-owner/test-repository",
            html_url="https://github.com/test-owner/test-repository",
            default_branch="main",
        ),
        contributors=contributors,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_mode="offline",
        synthetic=True,
    )


def test_fixture_loads_and_report_marks_fictional_data():
    assessment = build_test_assessment()
    sidecar = build_sbom_sidecar(assessment)
    assert assessment.synthetic is True
    assert len(sidecar["contributors"]) == 3
    assert sidecar["dataClassification"] == "fictional-demo"
    assert sidecar["documentType"] == "contributor-evidence-report"
    assert "url" not in sidecar["repository"]
    assert all("githubUrl" not in row for row in sidecar["contributors"])
    assert "eligibilityStatus" not in json.dumps(sidecar)
    assert sidecar["schemaVersion"] == "0.3"


def test_report_uses_concrete_public_source_outcomes():
    assessment = build_test_assessment()
    sidecar = build_sbom_sidecar(assessment)
    contributors = {row["githubLogin"]: row for row in sidecar["contributors"]}

    assert contributors["contributor-alpha"]["publicSourceResult"] == {
        "outcome": "Exact match found",
        "explanation": (
            "3 retained sources included the GitHub handle plus another identity detail."
        ),
        "searchesAttempted": 1,
        "retainedSourceCount": 3,
        "identityMatchCounts": {"exact": 3, "probable": 0},
    }
    assert contributors["contributor-beta"]["publicSourceResult"]["outcome"] == (
        "Probable match only"
    )
    no_matches = contributors["contributor-gamma"]["publicSourceResult"]
    assert no_matches["outcome"] == "No retained matches"
    assert no_matches["retainedSourceCount"] == 0
    assert "not a negative finding" in no_matches["explanation"]


def test_incomplete_search_is_reported_directly():
    assessment = build_test_assessment()
    assessment.contributors[0].error = "Tavily request timed out"
    sidecar = build_sbom_sidecar(assessment)

    result = sidecar["contributors"][0]["publicSourceResult"]
    assert result["outcome"] == "Search incomplete"
    assert result["searchError"] == "Tavily request timed out"


def test_report_omits_internal_scoring_language():
    assessment = build_test_assessment()
    serialized = json.dumps(build_sbom_sidecar(assessment))

    for legacy_field in (
        "reviewStatus",
        "identityEvidence",
        "identityConfidenceScore",
        "evidenceCoverageScore",
    ):
        assert legacy_field not in serialized
    assert "evidence completeness" not in serialized.lower()


def test_sidecar_json_is_valid_json():
    assessment = build_test_assessment()
    payload = json.loads(sidecar_json(assessment))
    assert payload["repository"]["name"] == "test-owner/test-repository"
