import pytest

from contributor_lens.models import RepoRef


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("pydantic/pydantic", "pydantic/pydantic"),
        ("https://github.com/pydantic/pydantic", "pydantic/pydantic"),
        ("https://www.github.com/pydantic/pydantic.git?tab=readme", "pydantic/pydantic"),
        (" github.com/pydantic/pydantic ", "pydantic/pydantic"),
    ],
)
def test_parse_repo(value, expected):
    assert RepoRef.parse(value).full_name == expected


@pytest.mark.parametrize("value", ["", "github.com/owner", "https://gitlab.com/owner/repo"])
def test_parse_repo_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        RepoRef.parse(value)
