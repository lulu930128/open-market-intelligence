from __future__ import annotations

import ast

import pytest

from conftest import REPO_ROOT


def test_intentional_get_side_effect_is_rejected(
    architecture_checker, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = ast.parse(
        """@router.get("/sample")
def get_sample(refresh: bool = False):
    return refresh_sample(refresh=refresh)
"""
    )
    fake_path = REPO_ROOT / "backend" / "app" / "routers" / "intentional_fixture.py"
    monkeypatch.setattr(
        architecture_checker,
        "iter_rule_files",
        lambda _repo_root, _rule: (fake_path,),
    )
    monkeypatch.setattr(
        architecture_checker,
        "parse_python",
        lambda _path: (tree, architecture_checker.PythonFactCollector()),
    )
    violations = architecture_checker.check_get_side_effects(
        REPO_ROOT,
        {
            "id": "get_side_effect",
            "side_effect_call_prefixes": ["refresh_"],
            "side_effect_keywords": ["refresh"],
        },
    )
    assert len(violations) == 2
    assert {item.key.rule for item in violations} == {"get_side_effect"}


def test_current_get_side_effects_are_frozen_to_exact_debt(
    architecture_evaluation,
) -> None:
    actual = {
        item.key
        for item in architecture_evaluation.violations
        if item.key.rule == "get_side_effect"
    }
    declared = {
        item.key
        for item in architecture_evaluation.debt
        if item.key.rule == "get_side_effect"
    }
    assert actual == declared
