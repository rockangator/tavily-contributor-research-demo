from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"

    @classmethod
    def parse(cls, value: str) -> "RepoRef":
        raw = value.strip()
        if not raw:
            raise ValueError("Enter a GitHub repository URL or owner/repository.")

        if raw.lower().startswith(("github.com/", "www.github.com/")):
            raw = f"https://{raw}"
        elif "://" not in raw:
            raw = f"https://github.com/{raw.lstrip('/')}"
        parsed = urlparse(raw)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Only github.com repository URLs are supported.")

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Use a repository URL such as https://github.com/owner/repository.")
        owner, name = parts[0], parts[1]
        if name.endswith(".git"):
            name = name[:-4]
        if not owner or not name:
            raise ValueError("The repository owner and name are both required.")
        return cls(owner=owner, name=name)


@dataclass
class RepositoryMetadata:
    full_name: str
    html_url: str
    description: str | None = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    default_branch: str = "main"
    license_name: str | None = None


@dataclass
class ContributorProfile:
    login: str
    html_url: str
    avatar_url: str | None = None
    contributions: int = 0
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    location: str | None = None
    blog: str | None = None
    created_at: str | None = None
    public_repos: int = 0
    followers: int = 0
    account_type: str = "User"

    @property
    def display_name(self) -> str:
        return self.name or self.login

    @property
    def account_age_years(self) -> float | None:
        if not self.created_at:
            return None
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc) - created).days / 365.25)
        except ValueError:
            return None


@dataclass
class EvidenceItem:
    title: str
    url: str
    excerpt: str
    source_domain: str
    relevance: float = 0.0
    identity_match: str = "weak"
    category: str = "Other"
    query: str = ""
    extracted: bool = False


@dataclass
class ContributorAssessment:
    profile: ContributorProfile
    evidence: list[EvidenceItem] = field(default_factory=list)
    identity_confidence: int = 0
    evidence_coverage: int = 0
    review_priority: str = "High"
    reasons: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    tavily_request_ids: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class RepoAssessment:
    repository: RepositoryMetadata
    contributors: list[ContributorAssessment]
    generated_at: str
    source_mode: str
    methodology_version: str = "0.1.0"
    errors: list[str] = field(default_factory=list)
    github_rate_limit_remaining: int | None = None
    synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
