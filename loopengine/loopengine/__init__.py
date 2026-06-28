"""loopengine — the Python loop-engineering runtime.

A loop earns its name only if it has a *trigger*, a *verifier*, *external state*,
and a *stop/escalate* rule. This package supplies all four as reusable
infrastructure, and delegates the constraint-critical pieces (command guard,
budget brakes, grounded verification) to the Rust ``loopguard`` core.
"""

from .budget import Budget, BudgetExceeded
from .consistency import ConsensusResult, majority_vote
from .core import Loopguard, LoopguardUnavailable
from .reflexion import Critique, ReflexionResult, run_reflexion
from .state import StateStore
from .validate import SpecInvalid, validate_spec
from .verifier import VerificationError, Verifier

__all__ = [
    "Budget",
    "BudgetExceeded",
    "ConsensusResult",
    "majority_vote",
    "Loopguard",
    "LoopguardUnavailable",
    "Critique",
    "ReflexionResult",
    "run_reflexion",
    "StateStore",
    "SpecInvalid",
    "validate_spec",
    "Verifier",
    "VerificationError",
]

__version__ = "0.1.0"
