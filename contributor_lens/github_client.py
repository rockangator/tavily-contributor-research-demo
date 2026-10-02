from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from .models import ContributorProfile, RepoRef, RepositoryMetadata


class GitHubAPIError(RuntimeError):
    pass


class GitHubClient:
    base_url = "https://api.github.com"

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "contributor-lens/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = client or httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)
        self.rate_limit_remaining: int | None = None

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        response = self.client.get(f"{self.base_url}{path}", params=params)
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining and remaining.isdigit():
            self.rate_limit_remaining = int(remaining)
        if response.status_code == 403 and remaining == "0":
            reset = response.headers.get("x-ratelimit-reset", "unknown")
            raise GitHubAPIError(f"GitHub API rate limit reached. Reset timestamp: {reset}.")
        if response.status_code == 404:
            raise GitHubAPIError("GitHub repository or contributor was not found, or it is not public.")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = ""
            try:
                message = response.json().get("message", "")
            except (ValueError, AttributeError):
                pass
            raise GitHubAPIError(f"GitHub returned {response.status_code}: {message or 'request failed'}") from exc
        return response.json()

    def get_repository(self, repo: RepoRef) -> RepositoryMetadata:
        payload = self._get(f"/repos/{repo.full_name}")
        assert isinstance(payload, dict)
        license_payload = payload.get("license") or {}
        return RepositoryMetadata(
            full_name=payload.get("full_name", repo.full_name),
            html_url=payload.get("html_url", repo.url),
            description=payload.get("description"),
            stars=int(payload.get("stargazers_count") or 0),
            forks=int(payload.get("forks_count") or 0),
            open_issues=int(payload.get("open_issues_count") or 0),
            default_branch=payload.get("default_branch") or "main",
            license_name=license_payload.get("spdx_id") or license_payload.get("name"),
        )

    def get_contributors(self, repo: RepoRef, limit: int = 5) -> list[ContributorProfile]:
        payload = self._get(
            f"/repos/{repo.full_name}/contributors",
            params={"per_page": min(max(limit * 3, 30), 100), "anon": "true"},
        )
        assert isinstance(payload, list)
        rows = [
            row
            for row in payload
            if row.get("login") and row.get("type") != "Bot" and not row.get("login", "").endswith("[bot]")
        ][:limit]

        profiles: dict[str, ContributorProfile] = {}
        workers = min(8, max(1, len(rows)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_row = {pool.submit(self._get_user, row): row for row in rows}
            for future in as_completed(future_to_row):
                row = future_to_row[future]
                login = row["login"]
                try:
                    profiles[login] = future.result()
                except Exception:
                    profiles[login] = self._profile_from_contributor_row(row)

        return [profiles[row["login"]] for row in rows]

    def _get_user(self, contributor_row: dict[str, Any]) -> ContributorProfile:
        payload = self._get(f"/users/{contributor_row['login']}")
        assert isinstance(payload, dict)
        return ContributorProfile(
            login=contributor_row["login"],
            html_url=payload.get("html_url") or contributor_row.get("html_url", ""),
            avatar_url=payload.get("avatar_url") or contributor_row.get("avatar_url"),
            contributions=int(contributor_row.get("contributions") or 0),
            name=payload.get("name"),
            bio=payload.get("bio"),
            company=payload.get("company"),
            location=payload.get("location"),
            blog=payload.get("blog"),
            created_at=payload.get("created_at"),
            public_repos=int(payload.get("public_repos") or 0),
            followers=int(payload.get("followers") or 0),
            account_type=payload.get("type") or "User",
        )

    @staticmethod
    def _profile_from_contributor_row(row: dict[str, Any]) -> ContributorProfile:
        return ContributorProfile(
            login=row["login"],
            html_url=row.get("html_url", ""),
            avatar_url=row.get("avatar_url"),
            contributions=int(row.get("contributions") or 0),
            account_type=row.get("type") or "User",
        )
