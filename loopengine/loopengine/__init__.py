"""loopengine — the Python loop-engineering runtime.

A loop earns its name only if it has a *trigger*, a *verifier*, *external state*,
and a *stop/escalate* rule. This package supplies all four as reusable
infrastructure, and delegates the constraint-critical pieces (command guard,
budget brakes, grounded verification) to the Rust ``loopguard`` core.
"""

from .assisted import AssistedFixLoop, AssistedResult, ScriptMaker
from .authoring import (
    AuditReport,
    CostEstimate,
    audit_spec,
    estimate_cost,
    scaffold_spec,
)
from .budget import Budget, BudgetExceeded
from .compaction import (
    Compactor,
    CompactionResult,
    Message,
    Notebook,
    estimate_tokens,
    extractive_summary,
)
from .connectors import ConnectorError, GuardedConnector, HttpMCPTransport, build_connector
from .consistency import ConsensusResult, majority_vote
from .scheduler import AnomalyVerdict, Scheduler, TickSummary, detect_anomaly, parse_interval
from .core import Loopguard, LoopguardUnavailable
from .makers import AnthropicClient, LLMMaker, OpenAICompatibleClient, make_maker
from .reflexion import Critique, ReflexionResult, run_reflexion
from .state import StateStore
from .validate import SpecInvalid, validate_spec
from .verifier import VerificationError, Verifier
from .worktree import Worktree, WorktreeError

__all__ = [
    "AssistedFixLoop",
    "AssistedResult",
    "ScriptMaker",
    "ConnectorError",
    "GuardedConnector",
    "HttpMCPTransport",
    "build_connector",
    "Scheduler",
    "TickSummary",
    "AnomalyVerdict",
    "detect_anomaly",
    "parse_interval",
    "Budget",
    "BudgetExceeded",
    "AuditReport",
    "CostEstimate",
    "audit_spec",
    "estimate_cost",
    "scaffold_spec",
    "Compactor",
    "CompactionResult",
    "Message",
    "Notebook",
    "estimate_tokens",
    "extractive_summary",
    "ConsensusResult",
    "majority_vote",
    "Loopguard",
    "LoopguardUnavailable",
    "AnthropicClient",
    "OpenAICompatibleClient",
    "LLMMaker",
    "make_maker",
    "Critique",
    "ReflexionResult",
    "run_reflexion",
    "StateStore",
    "SpecInvalid",
    "validate_spec",
    "Verifier",
    "VerificationError",
    "Worktree",
    "WorktreeError",
]

__version__ = "0.1.0"
