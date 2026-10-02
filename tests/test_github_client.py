from contributor_lens.github_client import GitHubClient
from contributor_lens.models import RepoRef


class FakeResponse:
    def __init__(self, payload, remaining="4999"):
        self._payload = payload
        self.status_code = 200
        self.headers = {"x-ratelimit-remaining": remaining}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeHTTPClient:
    def __init__(self):
        self.calls = []
        self.closed = False

    def get(self, url, params=None):
        self.calls.append((url, params))
        if url.endswith("/repos/acme/runtime-kit"):
            return FakeResponse(
                {
                    "full_name": "acme/runtime-kit",
                    "html_url": "https://github.com/acme/runtime-kit",
                    "description": "Runtime helpers",
                    "stargazers_count": 10,
                    "forks_count": 2,
                    "open_issues_count": 1,
                    "default_branch": "main",
                    "license": {"spdx_id": "Apache-2.0"},
                }
            )
        if url.endswith("/repos/acme/runtime-kit/contributors"):
            return FakeResponse(
                [
                    {
                        "login": "contributor-alpha",
                        "html_url": "https://github.com/contributor-alpha",
                        "avatar_url": "https://avatars.invalid/contributor-alpha",
                        "contributions": 42,
                        "type": "User",
                    },
                    {
                        "login": "dependabot[bot]",
                        "html_url": "https://github.com/apps/dependabot",
                        "contributions": 40,
                        "type": "Bot",
                    },
                    {"name": "Anonymous", "contributions": 12},
                ]
            )
        if url.endswith("/users/contributor-alpha"):
            return FakeResponse(
                {
                    "login": "contributor-alpha",
                    "html_url": "https://github.com/contributor-alpha",
                    "avatar_url": "https://avatars.invalid/contributor-alpha",
                    "name": "Contributor Alpha",
                    "bio": "Maintainer",
                    "company": "Acme",
                    "location": "Seattle",
                    "blog": "https://profile.invalid/contributor-alpha",
                    "created_at": "2014-01-01T00:00:00Z",
                    "public_repos": 20,
                    "followers": 50,
                    "type": "User",
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    def close(self):
        self.closed = True


def test_github_ingestion_filters_bots_and_anonymous_rows():
    fake = FakeHTTPClient()
    client = GitHubClient(client=fake)
    repo = RepoRef("acme", "runtime-kit")
    metadata = client.get_repository(repo)
    contributors = client.get_contributors(repo, limit=5)
    assert metadata.license_name == "Apache-2.0"
    assert [item.login for item in contributors] == ["contributor-alpha"]
    assert contributors[0].contributions == 42
    assert client.rate_limit_remaining == 4999
    contributor_call = next(call for call in fake.calls if call[0].endswith("/contributors"))
    assert contributor_call[1]["anon"] == "true"
