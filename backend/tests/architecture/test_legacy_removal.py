from __future__ import annotations

from conftest import REPO_ROOT


def test_historical_architecture_review_does_not_return_to_root() -> None:
    assert not (REPO_ROOT / "ARCHITECTURE_REVIEW.md").exists()
    assert (
        REPO_ROOT
        / "docs"
        / "archive"
        / "architecture"
        / "ArchitectureReview-20260714.md"
    ).exists()


def test_legacy_root_path_rule_has_no_violation(architecture_evaluation) -> None:
    assert not [
        item
        for item in architecture_evaluation.violations
        if item.key.rule == "legacy_root_architecture_review"
    ]
