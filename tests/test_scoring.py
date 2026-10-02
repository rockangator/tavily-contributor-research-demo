from contributor_lens.models import ContributorProfile, EvidenceItem
from contributor_lens.scoring import assess_contributor


def profile(**overrides):
    values = {
        "login": "contributor-alpha",
        "html_url": "https://github.com/contributor-alpha",
        "contributions": 120,
        "name": "Contributor Alpha",
        "bio": "Maintainer",
        "company": "Acme",
        "location": "Seattle",
        "blog": "https://profile.invalid/contributor-alpha",
        "created_at": "2014-01-01T00:00:00Z",
        "public_repos": 50,
        "followers": 100,
    }
    values.update(overrides)
    return ContributorProfile(**values)


def evidence(url, match="exact"):
    return EvidenceItem(
        title="Maintainer profile",
        url=url,
        excerpt="Contributor Alpha uses the contributor-alpha GitHub account.",
        source_domain=url.split("/")[2],
        relevance=0.9,
        identity_match=match,
        category="Project documentation",
    )


def test_strong_evidence_gets_low_review_priority():
    assessment = assess_contributor(
        profile(),
        [evidence("https://project.invalid/contributor-alpha"), evidence("https://events.invalid/contributor-alpha")],
    )
    assert assessment.identity_confidence >= 70
    assert assessment.evidence_coverage >= 70
    assert assessment.review_priority == "Low"


def test_missing_evidence_creates_review_task_not_adverse_claim():
    assessment = assess_contributor(
        profile(name=None, bio=None, company=None, location=None, blog=None, public_repos=1, followers=0),
        [],
    )
    assert assessment.review_priority == "High"
    assert "No external source" in assessment.reasons[0]
    assert any(
        caveat
        == "The public-source outcome describes retained search results, not contributor behavior."
        for caveat in assessment.caveats
    )


def test_probable_matches_remain_distinct_from_exact_matches():
    exact = assess_contributor(profile(), [evidence("https://one.invalid/contributor-alpha", "exact")])
    probable = assess_contributor(profile(), [evidence("https://one.invalid/contributor-alpha", "probable")])
    assert exact.identity_confidence > probable.identity_confidence
