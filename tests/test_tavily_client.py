from contributor_lens.models import ContributorProfile, RepoRef
from contributor_lens.tavily_client import TavilyEnricher


class FakeTavily:
    def __init__(self):
        self.search_calls = []
        self.extract_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {
            "request_id": f"search-{len(self.search_calls)}",
            "results": [
                {
                    "title": "Runtime Kit maintainers: Contributor Alpha",
                    "url": "https://docs.invalid/runtime-kit/contributor-alpha",
                    "content": "Contributor Alpha (@contributor-alpha) maintains acme/runtime-kit releases.",
                    "score": 0.93,
                },
                {
                    "title": "A namesake with unrelated work",
                    "url": "https://unrelated.invalid/people/contributor-alpha",
                    "content": "A photographer with no software profile.",
                    "score": 0.80,
                },
            ],
        }

    def extract(self, **kwargs):
        self.extract_calls.append(kwargs)
        return {
            "request_id": "extract-1",
            "results": [
                {
                    "url": "https://docs.invalid/runtime-kit/contributor-alpha",
                    "raw_content": "Project documentation confirms Contributor Alpha, contributor-alpha, as a release maintainer.",
                }
            ],
            "failed_results": [],
        }


def make_profile():
    return ContributorProfile(
        login="contributor-alpha",
        html_url="https://github.com/contributor-alpha",
        name="Contributor Alpha",
        contributions=42,
    )


def test_enrichment_rejects_weak_namesake_and_preserves_trace():
    fake = FakeTavily()
    enricher = TavilyEnricher(api_key="unused", client=fake)
    results, request_ids, queries = enricher.enrich(make_profile(), RepoRef("acme", "runtime-kit"))
    assert len(results) == 1
    assert results[0].identity_match == "exact"
    assert request_ids == ["search-1", "search-2"]
    assert len(queries) == 2
    assert all(call["search_depth"] == "basic" for call in fake.search_calls)
    assert all(call["safe_search"] is True for call in fake.search_calls)
    assert all("linkedin.com" in call["exclude_domains"] for call in fake.search_calls)


def test_deep_extract_updates_excerpt():
    fake = FakeTavily()
    enricher = TavilyEnricher(api_key="unused", client=fake)
    results, request_ids, _ = enricher.enrich(
        make_profile(), RepoRef("acme", "runtime-kit"), deep_extract=True
    )
    assert results[0].extracted is True
    assert "release maintainer" in results[0].excerpt
    assert request_ids[-1] == "extract-1"
