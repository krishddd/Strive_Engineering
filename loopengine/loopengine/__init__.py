"""loopengine — the Python loop-engineering runtime.

A loop earns its name only if it has a *trigger*, a *verifier*, *external state*,
and a *stop/escalate* rule. This package supplies all four as reusable
infrastructure, and delegates the constraint-critical pieces (command guard,
budget brakes, grounded verification) to the Rust ``loopguard`` core.
"""

from .budget import Budget, BudgetExceeded
from .core import Loopguard, LoopguardUnavailable
from .state import StateStore
from .verifier import VerificationError, Verifier

__all__ = [
    "Budget",
    "BudgetExceeded",
    "Loopguard",
    "LoopguardUnavailable",
    "StateStore",
    "Verifier",
    "VerificationError",
]

__version__ = "0.1.0"
