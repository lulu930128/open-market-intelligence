"""Factory-only synthetic ASGI test app. No runtime application singleton."""

from .gateway import build_test_app
from .security import SyntheticAuth
from .policy import SyntheticFixturePolicy

__all__ = ['build_test_app', 'SyntheticAuth', 'SyntheticFixturePolicy']
