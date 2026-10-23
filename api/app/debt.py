"""The Prompt Debt Score: one 0-100 number for a repository's AI instruction files.

Six measurements are taken across all of the repo's artefacts together. Each is
turned into a 0-1 component (capped, so one extreme value can't dominate),
multiplied by its weight, and the results are added up:

    component            repo-level measure                                weight
    conflicting rules    min(conflicts found by the AI review / 3, 1)        35
    broken references    min(total broken paths / 5, 1)                      25
    drift                mean of staleness and churn (below)                 20
    duplicated rules     min(distinct rules repeated across files / 5, 1)    10
    undocumented         share of artefacts the README doesn't mention         5
    size                 min(max(total tokens - 2000, 0) / 6000, 1)           5

    drift     = (staleness + churn) / 2, where
    staleness = min(most days behind / 180, 1)
    churn     = min(most commits since an update / 100, 1)

    score = sum(weight x component), rounded to the nearest whole number
    band  = Low (0-24), Moderate (25-49), High (50-100)

Staleness and churn both measure how far the code has moved on since an artefact was
updated (in days and in commits), so they are averaged into one drift component
rather than counted twice. Both use the worst artefact, because one badly
out-of-date file is enough to mislead an AI tool. Broken references, duplicates and
size add up across files, because each one is more for a maintainer to fix.

Conflicting rules come from the optional AI review (see review.py). Until a review
has run, or when it can't run or fails, conflicts are left out rather than counted as
0: the other five components are scored out of their 65 points and scaled back to
0-100 (score = points x 100 / 65). Because conflicts come from a model, that one
component is not fully reproducible: a different model or model version may find a
different number.

Worked example: a repo has CLAUDE.md and AGENTS.md. The AI review found 1 conflict
between them. The more out-of-date file is 90 days behind and 40 commits have landed
since it changed. Between them they mention 2 paths that no longer exist, repeat no
rules, the README mentions only one of them, and together they're about 1,500 tokens:

    conflicting rules  35 x min(1/3, 1)          = 35 x 0.333 = 11.67
    broken references  25 x min(2/5, 1)          = 25 x 0.4   = 10
    drift              20 x (90/180 + 40/100)/2  = 20 x 0.45  = 9
    duplicated rules   10 x 0                    = 0
    undocumented        5 x 1/2                  = 2.5
    size                5 x 0                    = 0
    total = 33.17, rounded to 33 -> Moderate

Without an AI review, the same repo scores the other 21.5 points out of 65, scaled to
21.5 x 100 / 65 = 33.08, rounded to 33 -> Moderate.

Other values that couldn't be measured (e.g. no commit history, or a repo too large
to check references) also count as 0 rather than guessing. A repo with no artefacts
has no score.

The weights, caps and bands are provisional: chosen by judgement, to be calibrated
against real repositories in the research.
"""

import math

from .analysis import normalise_rule

WEIGHTS = {
    "conflicts": 35,
    "broken_refs": 25,
    "drift": 20,
    "duplication": 10,
    "undocumented": 5,
    "size": 5,
}

CONFLICTS_CAP = 3
BROKEN_REFS_CAP = 5
STALENESS_CAP_DAYS = 180
CHURN_CAP_COMMITS = 100
DUPLICATION_CAP = 5
SIZE_FREE_TOKENS = 2000
SIZE_SPAN_TOKENS = 6000

MODERATE_FROM = 25
HIGH_FROM = 50

# An artefact this large gets its own "oversized" finding.
OVERSIZED_TOKENS = 5000


def _capped(value: float, cap: float) -> float:
    return min(value / cap, 1.0)


def components(artefacts, conflicts: int | None = None) -> dict[str, float]:
    """Each repo-level measurement scaled to 0-1. ``artefacts`` must not be empty.

    ``conflicts`` is the number found by the AI review, or None if none has run.
    """
    broken = sum(len(a.broken_refs or []) for a in artefacts)
    staleness = _capped(max((a.days_behind or 0) for a in artefacts), STALENESS_CAP_DAYS)
    churn = _capped(max((a.commits_since_update or 0) for a in artefacts), CHURN_CAP_COMMITS)
    repeated = {normalise_rule(d["text"]) for a in artefacts for d in a.duplicate_rules}
    undocumented = sum(1 for a in artefacts if not a.documented) / len(artefacts)
    tokens = sum(a.approx_tokens for a in artefacts)
    return {
        "conflicts": _capped(conflicts or 0, CONFLICTS_CAP),
        "broken_refs": _capped(broken, BROKEN_REFS_CAP),
        "drift": (staleness + churn) / 2,
        "duplication": _capped(len(repeated), DUPLICATION_CAP),
        "undocumented": undocumented,
        "size": _capped(max(tokens - SIZE_FREE_TOKENS, 0), SIZE_SPAN_TOKENS),
    }


def points(artefacts, conflicts: int | None = None) -> dict[str, float]:
    """Points each component contributes (weight x component), for the breakdown."""
    parts = components(artefacts, conflicts)
    return {name: WEIGHTS[name] * value for name, value in parts.items()}


def score(artefacts, conflicts: int | None = None) -> int | None:
    """Total score, rounded half up (37.5 -> 38). None if there are no artefacts.

    Without an AI review (``conflicts`` is None) the conflicting-rules weight is left
    out and the remaining points are scaled from 65 up to 100.
    """
    if not artefacts:
        return None
    total = sum(points(artefacts, conflicts).values())
    if conflicts is None:
        total *= 100 / (100 - WEIGHTS["conflicts"])
    # round(..., 6) first so floating-point noise (12.000000000000002) can't tip a .5.
    return math.floor(round(total, 6) + 0.5)


def band(total: int) -> str:
    if total >= HIGH_FROM:
        return "high"
    if total >= MODERATE_FROM:
        return "moderate"
    return "low"
