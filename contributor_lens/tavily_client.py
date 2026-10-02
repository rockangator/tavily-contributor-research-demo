from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from .models import ContributorProfile, EvidenceItem, RepoRef


class TavilyEnrichmentError(RuntimeError):
    pass


class TavilyEnricher:
    """Search and optionally extract public evidence with conservative identity matching."""

    def __init__(
        self,
        api_key: str,
        project_id: str | None = None,
        client: object | None = None,
    ) -> None:
        if client is None:
            try:
                from tavily import TavilyClient
            except ImportError as exc:  # pragma: no cover - dependency guidance
                raise TavilyEnrichmentError("Install tavily-python before using live enrichment.") from exc
            kwargs = {"api_key": api_key}
            if project_id:
                kwargs["project_id"] = project_id
            client = TavilyClient(**kwargs)
        self.client = client

    @staticmethod
    def build_queries(profile: ContributorProfile, repo: RepoRef) -> list[str]:
        display = profile.display_name.replace('"', "")
        login = profile.login.replace('"', "")
        return [
            f'"{display}" "{login}" GitHub open source developer',
            f'"{display}" "{repo.full_name}" contributor maintainer',
        ]

    def enrich(
        self,
        profile: ContributorProfile,
        repo: RepoRef,
        deep_extract: bool = False,
    ) -> tuple[list[EvidenceItem], list[str], list[str]]:
        queries = self.build_queries(profile, repo)
        evidence_by_url: dict[str, EvidenceItem] = {}
        request_ids: list[str] = []

        for query in queries:
            try:
                response = self.client.search(
                    query=query,
                    search_depth="basic",
                    chunks_per_source=2,
                    max_results=6,
                    include_answer=False,
                    include_raw_content=False,
                    include_favicon=False,
                    include_usage=True,
                    safe_search=True,
                    exclude_domains=["linkedin.com"],
                )
            except Exception as exc:
                raise TavilyEnrichmentError(f"Tavily search failed: {exc}") from exc

            request_id = response.get("request_id")
            if request_id:
                request_ids.append(str(request_id))
            for result in response.get("results", []):
                item = self._to_evidence(result, query, profile, repo)
                if item.identity_match == "weak":
                    continue
                existing = evidence_by_url.get(item.url)
                if existing is None or item.relevance > existing.relevance:
                    evidence_by_url[item.url] = item

        evidence = sorted(evidence_by_url.values(), key=lambda item: item.relevance, reverse=True)[:8]
        if deep_extract and evidence:
            evidence, extract_request_id = self._extract_top(evidence, profile, repo)
            if extract_request_id:
                request_ids.append(extract_request_id)
        return evidence, request_ids, queries

    def _extract_top(
        self,
        evidence: list[EvidenceItem],
        profile: ContributorProfile,
        repo: RepoRef,
    ) -> tuple[list[EvidenceItem], str | None]:
        selected = evidence[:3]
        try:
            response = self.client.extract(
                urls=[item.url for item in selected],
                extract_depth="basic",
                format="markdown",
                query=f"Public evidence connecting {profile.display_name} ({profile.login}) to {repo.full_name} and open-source work",
                chunks_per_source=2,
                include_usage=True,
            )
        except Exception:
            return evidence, None

        content_by_url = {
            row.get("url"): self._clean_excerpt(row.get("raw_content") or "")
            for row in response.get("results", [])
        }
        enriched: list[EvidenceItem] = []
        for item in evidence:
            extracted = content_by_url.get(item.url)
            enriched.append(replace(item, excerpt=extracted or item.excerpt, extracted=bool(extracted)))
        request_id = response.get("request_id")
        return enriched, str(request_id) if request_id else None

    @classmethod
    def _to_evidence(
        cls,
        result: dict,
        query: str,
        profile: ContributorProfile,
        repo: RepoRef,
    ) -> EvidenceItem:
        url = str(result.get("url") or "")
        title = str(result.get("title") or url or "Untitled source")
        content = str(result.get("content") or "")
        body = f"{title} {content}".lower()
        combined = f"{body} {url}".lower()
        login = profile.login.lower()
        full_name = (profile.name or "").strip().lower()
        name_tokens = [token for token in re.split(r"\W+", full_name) if len(token) > 2]
        repo_tokens = [repo.owner.lower(), repo.name.lower(), repo.full_name.lower()]

        handle_match = (
            f"@{login}" in body
            or f"github.com/{login}" in combined
            or f"github handle {login}" in body
            or f"github account {login}" in body
        )
        full_name_match = bool(full_name and full_name in combined)
        token_match = bool(name_tokens) and sum(token in combined for token in name_tokens) >= min(2, len(name_tokens))
        repo_match = any(token in combined for token in repo_tokens)

        if handle_match and (full_name_match or repo_match):
            identity_match = "exact"
        elif handle_match or (full_name_match and repo_match) or (token_match and repo_match):
            identity_match = "probable"
        else:
            identity_match = "weak"

        domain = urlparse(url).netloc.lower().removeprefix("www.")
        return EvidenceItem(
            title=title,
            url=url,
            excerpt=cls._clean_excerpt(content),
            source_domain=domain or "unknown",
            relevance=float(result.get("score") or 0.0),
            identity_match=identity_match,
            category=cls._category(domain, url),
            query=query,
        )

    @staticmethod
    def _clean_excerpt(value: str, limit: int = 700) -> str:
        text = re.sub(r"\s+", " ", value).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    @staticmethod
    def _category(domain: str, url: str) -> str:
        lowered = f"{domain} {url}".lower()
        if "github.com" in lowered:
            return "GitHub"
        if "linkedin.com" in lowered:
            return "Professional profile"
        if any(token in lowered for token in ("youtube.com", "youtu.be", "speakerdeck.com", "slideshare.net")):
            return "Talk or presentation"
        if any(token in lowered for token in ("medium.com", "substack.com", "dev.to")):
            return "Publication"
        return "Web source"
