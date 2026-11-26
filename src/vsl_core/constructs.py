"""Layer 2 executable VSL constructs: AllowedState, InadmissibleState,
Fallback, Invariant, PreNode, TerminalState.

This module must NEVER import any agent-framework package (`agents`,
`langgraph`, `langchain`, or similar) or any model-provider SDK (`openai`,
`anthropic`, or similar). It is the most likely module to accidentally
regain such a coupling later if someone adds a "convenience" method that
assumes a particular framework's call shape -- don't. Any adapter-specific
compile step (turning a PreNode/Invariant into a framework's own guardrail
type) belongs in a separate `vsl-<framework>` package, never here.
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from .metrics import AssuranceBasis, AssuranceLevel, F2Modification, GammaEstimate, ROBUST_GAMMA_DEFAULT_THRESHOLD

@dataclass(frozen=True)
class _NotStatedBasis(AssuranceBasis):
    """The placeholder's own type, so it is recognised by isinstance and
    stays recognisable after copy.deepcopy() or pickling (an identity check
    would not). Never equal to a caller's AssuranceBasis: dataclass equality
    compares the class too."""


# Placeholder held by a construct whose caller did not pass assurance_basis
# (the normal case from 0.4.0). It exists only so adapters released before
# 0.4.0, which read `construct.assurance_basis.f2_modification`, keep
# working against this release. It states nothing: assurance_level returns
# None for it. Removed in 1.0 along with the field.
_NOT_STATED = _NotStatedBasis(f1_pre_commitment=True, f2_modification=F2Modification.NONE)

ASSURANCE_BASIS_DEPRECATION: str = (
    "assurance_basis is no longer used; enforcement is computed from the ledger "
    "(VerbaLedger.enforcement). Remove it; it will be rejected in 1.0."
)


def _warn_if_basis_passed(basis: AssuranceBasis) -> None:
    # Called from a construct's __post_init__: this function, __post_init__
    # and the generated __init__ sit between the warning and the caller.
    if not isinstance(basis, _NotStatedBasis):
        warnings.warn(ASSURANCE_BASIS_DEPRECATION, FutureWarning, stacklevel=4)


def _deprecated_level(basis: AssuranceBasis) -> AssuranceLevel | None:
    warnings.warn(
        "assurance_level is deprecated and will be removed in 1.0; vsl-core no longer "
        "reports an assurance level. Use VerbaLedger.enforcement(decision_id).",
        FutureWarning,
        stacklevel=3,
    )
    if isinstance(basis, _NotStatedBasis):
        return None
    return basis.derived_level


@dataclass(frozen=True)
class AllowedState:
    """A state meeting all required prerequisites, Constraints, rules, and
    validity conditions.

    `assurance_basis` is deprecated and ignored (see Invariant).
    """

    name: str
    description: str
    measurement: str
    validity_conditions: tuple[str, ...] = ()
    assurance_basis: AssuranceBasis = field(default=_NOT_STATED, kw_only=True)

    def __post_init__(self) -> None:
        # 0.3.x order was (name, description, assurance_basis, measurement).
        # A positional 0.3.x call would otherwise put the basis into
        # measurement without any error.
        if isinstance(self.measurement, AssuranceBasis) or isinstance(self.validity_conditions, str):
            raise TypeError(
                "AllowedState's positional arguments changed in 0.4.0: it is now "
                "AllowedState(name, description, measurement, validity_conditions). "
                "Pass measurement by keyword and drop assurance_basis."
            )
        _warn_if_basis_passed(self.assurance_basis)

    @property
    def assurance_level(self) -> AssuranceLevel | None:
        """Deprecated: returns the level of a passed assurance_basis, else None."""
        return _deprecated_level(self.assurance_basis)


@dataclass(frozen=True)
class InadmissibleState:
    """A state that must not occur -- corresponds to a Drift Node."""

    name: str
    description: str
    signature: str
    energy_gap_proxy: str | None = None


@dataclass(frozen=True)
class Fallback:
    """A deterministic recovery/termination action when a State is invalid
    or a Pre-Node cannot be satisfied.
    """

    on_failure: str = "INCREASE_DELTA"
    delta_factor: float = 1.5
    max_retries: int = 3
    on_max_retries: str = "AUTOMATION_DENIED"


class DriftMonitor(Protocol):
    """Framework-agnostic monitor signature. An adapter's compile step is
    responsible for constructing whatever `candidate_input` means in its
    own framework's terms before calling this.
    """

    async def __call__(self, candidate_input: Any) -> GammaEstimate: ...


class FormationLayerIntervention(Protocol):
    """Framework-agnostic formation-layer intervention signature."""

    async def __call__(self, delta_factor: float) -> bool: ...


@dataclass(frozen=True)
class Invariant:
    """A persistent Constraint that cannot be bypassed. Violation triggers
    IMMEDIATE_TERMINAL_STATE per the spec, not an ordinary Fallback.

    `assurance_basis` is deprecated and ignored: passing it raises a
    FutureWarning and changes nothing. Whether a gate held before its
    action is computed from the ledger (VerbaLedger.enforcement), not
    declared.

    on_violation names which TerminalState that immediate transition is
    into. It's optional (an Invariant can exist before its Terminal State
    is decided), but when set, an adapter catching InvariantViolation for
    this Invariant should treat entry into on_violation as automatic --
    that's what "violation triggers immediate Terminal State" means.
    """

    name: str
    description: str
    rule: Callable[[Any], Awaitable[bool]]
    assurance_basis: AssuranceBasis = _NOT_STATED
    scope: str = "ALL_STATES"
    cannot_be_bypassed: bool = True
    on_violation: TerminalState | None = None

    def __post_init__(self) -> None:
        _warn_if_basis_passed(self.assurance_basis)

    @property
    def assurance_level(self) -> AssuranceLevel | None:
        """Deprecated: returns the level of a passed assurance_basis, else None."""
        return _deprecated_level(self.assurance_basis)


@dataclass(frozen=True)
class TerminalState:
    """A state from which no further automated transitions are permitted."""

    name: str
    description: str
    entry_conditions: tuple[str, ...] = ()
    requires_human_authorised_transition: bool = True


@dataclass(frozen=True)
class PreNode:
    """A mandatory prerequisite that must be satisfied before transitioning
    into a target State -- the central VERBA construct. Every Pre-Node is
    an Eligibility Condition: a State transition without a satisfied
    Pre-Node is, by definition, Drift.

    `assurance_basis` is deprecated and ignored (see Invariant).
    """

    name: str
    description: str
    monitor: DriftMonitor
    assurance_basis: AssuranceBasis = _NOT_STATED
    gamma_threshold: float = ROBUST_GAMMA_DEFAULT_THRESHOLD
    intervention: FormationLayerIntervention | None = None
    fallback: Fallback = field(default_factory=Fallback)

    @property
    def assurance_level(self) -> AssuranceLevel | None:
        """Deprecated: returns the level of a passed assurance_basis, else None."""
        return _deprecated_level(self.assurance_basis)

    def __post_init__(self) -> None:
        _warn_if_basis_passed(self.assurance_basis)
        if self.fallback.max_retries < 0:
            raise ValueError("Fallback.max_retries must be >= 0.")
        if self.fallback.delta_factor <= 0:
            raise ValueError("Fallback.delta_factor must be > 0.")


_invariant_registry: list[Invariant] = []
_invariant_registry_lock = threading.Lock()


def register_invariant(invariant: Invariant) -> None:
    """Register an Invariant in the module-level registry.

    Raises ValueError on a duplicate name rather than silently overwriting
    -- silently replacing a governance Invariant is exactly the kind of
    silent failure Design Principle P3 ("explicit failure conditions")
    forbids.
    """
    with _invariant_registry_lock:
        if any(existing.name == invariant.name for existing in _invariant_registry):
            raise ValueError(f"An Invariant named {invariant.name!r} is already registered.")
        _invariant_registry.append(invariant)


def registered_invariants() -> tuple[Invariant, ...]:
    with _invariant_registry_lock:
        return tuple(_invariant_registry)
