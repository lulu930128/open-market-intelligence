from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts" / "check-architecture.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("omi_architecture_checker", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load architecture checker from {CHECKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def architecture_checker():
    return _load_checker()


@pytest.fixture(scope="session")
def architecture_evaluation(architecture_checker):
    return architecture_checker.evaluate(REPO_ROOT)
