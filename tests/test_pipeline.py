from datetime import datetime, timezone

from contributor_lens.models import (
    ContributorAssessment,
    ContributorProfile,
    RepoAssessment,
    RepositoryMetadata,
)
from contributor_lens.pipeline import load_fixture, save_assessment


def live_assessment():
    return RepoAssessment(
        repository=RepositoryMetadata(
            full_name="test-owner/test-repository",
            html_url="https://github.com/test-owner/test-repository",
        ),
        contributors=[
            ContributorAssessment(
                profile=ContributorProfile(
                    login="contributor-alpha",
                    html_url="https://github.com/contributor-alpha",
                )
            )
        ],
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_mode="live",
    )


def test_live_assessment_round_trips_without_credentials(tmp_path):
    assessment = live_assessment()
    destination = tmp_path / "latest-live-report.json"

    save_assessment(assessment, destination)
    restored = load_fixture(destination)

    assert restored.repository.full_name == "test-owner/test-repository"
    assert restored.generated_at == assessment.generated_at
    assert restored.contributors[0].profile.login == assessment.contributors[0].profile.login
    serialized = destination.read_text()
    assert "TAVILY_API_KEY" not in serialized
    assert "GITHUB_TOKEN" not in serialized
