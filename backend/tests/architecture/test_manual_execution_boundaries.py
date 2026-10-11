"""Discover the isolated M1 manifest and stdlib regressions in existing architecture CI."""

import sys
import unittest

from conftest import REPO_ROOT


def test_offline_execution_has_no_architecture_debt(architecture_checker):
    result = architecture_checker.evaluate(
        REPO_ROOT,
        constraints_path=REPO_ROOT / "architecture/execution-constraints.toml",
        debt_path=REPO_ROOT / "architecture/execution-debt.toml",
    )
    assert result.passed
    assert not result.violations
    assert not result.debt


def test_offline_execution_regressions():
    """No app import, DB or provider fixture; unittest is the domain's only runner."""
    original_path = sys.path[:]
    try:
        suite = unittest.defaultTestLoader.discover(
            str(REPO_ROOT / "execution/tests"), top_level_dir=str(REPO_ROOT),
        )
        result = unittest.TestResult()
        suite.run(result)
        assert result.testsRun > 0
        assert result.wasSuccessful(), result.errors + result.failures
    finally:
        sys.path[:] = original_path
