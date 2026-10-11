"""SYNTHETIC-only application harness; never a production execution adapter."""

from .application import SimulationApplication
from .storage import temporary_sandbox

__all__ = ["SimulationApplication", "temporary_sandbox"]
