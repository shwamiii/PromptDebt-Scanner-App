import pytest

from app.errors import ApiError
from app.scanner import mentions, parse_repo_url, status_for


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/widgets",
        "https://github.com/acme/widgets/",
        "https://github.com/acme/widgets.git",
        "https://www.github.com/acme/widgets",
        "http://github.com/acme/widgets",
        "github.com/acme/widgets",
        "  https://github.com/acme/widgets  ",
        "https://github.com/acme/widgets/tree/main/src",
    ],
)
def test_parse_accepts_common_forms(url):
    assert parse_repo_url(url) == "acme/widgets"


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("", "Enter a GitHub repository URL"),
        ("https://gitlab.com/acme/widgets", "That's not a GitHub URL"),
        ("https://github.com.evil.com/acme/widgets", "That's not a GitHub URL"),
        ("acme/widgets", "That's not a GitHub URL"),
        ("https://github.com/acme", "Include the owner and repository name"),
        ("https://github.com/acme/wid$gets", "isn't a valid GitHub repository URL"),
    ],
)
def test_parse_rejects_with_specific_message(url, message):
    with pytest.raises(ApiError) as exc:
        parse_repo_url(url)
    assert message in exc.value.message


@pytest.mark.parametrize(
    ("days", "status"),
    [(None, "unknown"), (0, "fresh"), (30, "fresh"), (31, "ageing"), (90, "ageing"), (91, "stale")],
)
def test_status_bands(days, status):
    assert status_for(days) == status


def test_mentions_matches_whole_names_only():
    assert mentions("See `claude.md` for details.", "CLAUDE.md")
    assert not mentions("See MY_CLAUDE.md", "CLAUDE.md")
    assert not mentions("See CLAUDE.mdx", "CLAUDE.md")
