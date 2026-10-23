from types import SimpleNamespace

import pytest

from app import debt


def artefact(**overrides):
    values = {
        "broken_refs": [],
        "days_behind": 0,
        "commits_since_update": 0,
        "duplicate_rules": [],
        "documented": True,
        "approx_tokens": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def broken(count):
    return [{"path": f"x{i}.py", "line": 1, "reason": "", "found_at": []} for i in range(count)]


def test_worked_example_from_the_docstring():
    claude = artefact(
        broken_refs=broken(2), days_behind=90, commits_since_update=40, approx_tokens=900
    )
    agents = artefact(days_behind=12, commits_since_update=3, documented=False, approx_tokens=600)
    assert debt.points([claude, agents], conflicts=1) == {
        "conflicts": pytest.approx(35 / 3),
        "broken_refs": pytest.approx(10),
        "drift": pytest.approx(9),
        "duplication": 0,
        "undocumented": 2.5,
        "size": 0,
    }
    assert debt.score([claude, agents], conflicts=1) == 33
    assert debt.band(33) == "moderate"


def test_without_a_review_the_other_65_points_scale_to_100():
    claude = artefact(
        broken_refs=broken(2), days_behind=90, commits_since_update=40, approx_tokens=900
    )
    agents = artefact(days_behind=12, commits_since_update=3, documented=False, approx_tokens=600)
    assert debt.score([claude, agents]) == 33
    assert debt.score([claude, agents], conflicts=0) == 22
    worst = artefact(
        broken_refs=broken(9),
        days_behind=999,
        commits_since_update=100,
        duplicate_rules=[{"text": f"rule {i} goes here", "other_path": "b"} for i in range(9)],
        documented=False,
        approx_tokens=100_000,
    )
    assert debt.score([worst]) == 100


def test_drift_averages_staleness_and_churn_from_the_worst_files():
    a = artefact(days_behind=180)
    b = artefact(commits_since_update=50)
    assert debt.components([a, b])["drift"] == pytest.approx(0.75)


def test_counts_add_up_across_files():
    a = artefact(broken_refs=broken(1), approx_tokens=5000)
    b = artefact(broken_refs=broken(1), approx_tokens=3000)
    parts = debt.components([a, b])
    assert parts["broken_refs"] == pytest.approx(2 / 5)
    assert parts["size"] == 1.0


def test_conflicts_count_only_once_reviewed():
    files = [artefact()]
    assert debt.components(files)["conflicts"] == 0
    assert debt.components(files, conflicts=0)["conflicts"] == 0
    assert debt.components(files, conflicts=2)["conflicts"] == pytest.approx(2 / 3)
    assert debt.components(files, conflicts=9)["conflicts"] == 1.0


def test_a_rule_repeated_across_files_counts_once():
    rule = {"text": "- Use pnpm for installs please.", "other_path": "b"}
    same = {"text": "* use PNPM for installs, please", "other_path": "a"}
    files = [artefact(duplicate_rules=[rule]), artefact(duplicate_rules=[same])]
    assert debt.components(files)["duplication"] == pytest.approx(1 / 5)


def test_clean_repo_scores_zero_and_no_artefacts_has_no_score():
    assert debt.score([artefact()]) == 0
    assert debt.score([]) is None


def test_every_component_is_capped():
    rules = [{"text": f"rule number {i} is here", "other_path": "b"} for i in range(9)]
    worst = artefact(
        broken_refs=broken(50),
        days_behind=5000,
        commits_since_update=100,
        duplicate_rules=rules,
        documented=False,
        approx_tokens=100_000,
    )
    assert debt.score([worst], conflicts=20) == 100


def test_unmeasured_values_count_as_zero():
    unknown = artefact(broken_refs=None, days_behind=None, commits_since_update=None)
    assert debt.score([unknown]) == 0


def test_weights_add_up_to_100():
    assert sum(debt.WEIGHTS.values()) == 100


@pytest.mark.parametrize(
    ("score", "band"), [(0, "low"), (24, "low"), (25, "moderate"), (49, "moderate"), (50, "high")]
)
def test_bands(score, band):
    assert debt.band(score) == band
