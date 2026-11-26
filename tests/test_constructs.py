import asyncio
import uuid
import warnings

import pytest

from vsl_core.constructs import (
    ASSURANCE_BASIS_DEPRECATION,
    AllowedState,
    Fallback,
    InadmissibleState,
    Invariant,
    PreNode,
    TerminalState,
    register_invariant,
    registered_invariants,
)
from vsl_core.metrics import AssuranceBasis, AssuranceLevel, F2Modification, GammaEstimate

_LEGACY_BASIS = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL)


async def _always_true(_candidate_input) -> bool:
    return True


async def _stub_monitor(_candidate_input) -> GammaEstimate:
    return GammaEstimate(gamma_hat=2.0)


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _no_warnings(build):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return build()


def test_allowed_state_construction():
    state = _no_warnings(lambda: AllowedState(
        name="factual_response",
        description="Model output is factually supported",
        measurement="D_KL(P_t || P_A) < 0.15 nats",
        validity_conditions=("token_probability_factual > token_probability_hallucination",),
    ))
    assert len(state.validity_conditions) == 1


def test_allowed_state_assurance_level_is_not_a_constructor_argument():
    with pytest.raises(TypeError):
        AllowedState(
            name="x",
            description="d",
            assurance_level=AssuranceLevel.HIGH,  # type: ignore[call-arg]
            measurement="m",
        )


def test_allowed_state_old_positional_order_fails_loudly():
    # 0.3.x order: (name, description, assurance_basis, measurement).
    with pytest.raises(TypeError, match="positional arguments changed in 0.4.0"):
        AllowedState("s", "d", _LEGACY_BASIS, "m")  # type: ignore[arg-type]


def test_allowed_state_new_positional_order_works():
    state = _no_warnings(lambda: AllowedState("s", "d", "m", ("c",)))
    assert state.measurement == "m"
    assert state.validity_conditions == ("c",)


def test_inadmissible_state_construction():
    state = InadmissibleState(
        name="hallucination_attractor",
        description="Model converges to factually unsupported output",
        signature="P_t(x_hallucination) > P_t(x_factual) for 3 consecutive steps",
    )
    assert state.energy_gap_proxy is None


def test_fallback_defaults_match_spec():
    fallback = Fallback()
    assert fallback.on_failure == "INCREASE_DELTA"
    assert fallback.delta_factor == 1.5
    assert fallback.max_retries == 3
    assert fallback.on_max_retries == "AUTOMATION_DENIED"


def test_invariant_cannot_be_bypassed_defaults_true():
    invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true)
    assert invariant.cannot_be_bypassed is True
    assert invariant.scope == "ALL_STATES"


def test_constructs_need_no_assurance_basis_and_warn_about_nothing():
    _no_warnings(lambda: Invariant(name=_unique_name("inv"), description="d", rule=_always_true))
    _no_warnings(lambda: PreNode(name="gate", description="d", monitor=_stub_monitor))


@pytest.mark.parametrize(
    "build",
    [
        lambda: Invariant(name="inv", description="d", rule=_always_true, assurance_basis=_LEGACY_BASIS),
        lambda: PreNode(name="gate", description="d", monitor=_stub_monitor, assurance_basis=_LEGACY_BASIS),
        lambda: AllowedState(name="s", description="d", measurement="m", assurance_basis=_LEGACY_BASIS),
    ],
)
def test_passing_assurance_basis_warns_and_is_ignored(build):
    with pytest.warns(FutureWarning) as caught:
        construct = build()
    assert str(caught[0].message) == ASSURANCE_BASIS_DEPRECATION
    # The warning points at the caller, not at vsl-core internals.
    assert caught[0].filename == __file__
    assert construct.assurance_basis is _LEGACY_BASIS


def test_deprecation_warning_never_mentions_f2():
    assert "F2" not in ASSURANCE_BASIS_DEPRECATION
    assert "f2" not in ASSURANCE_BASIS_DEPRECATION.lower()


def test_assurance_level_is_deprecated_and_none_when_not_passed():
    node = PreNode(name="gate", description="d", monitor=_stub_monitor)
    with pytest.warns(FutureWarning):
        assert node.assurance_level is None


def test_assurance_level_still_returns_a_passed_basis_level_until_1_0():
    with pytest.warns(FutureWarning):
        invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true, assurance_basis=_LEGACY_BASIS)
    with pytest.warns(FutureWarning):
        assert invariant.assurance_level == AssuranceLevel.HIGH


def test_adapters_released_before_0_4_0_can_still_read_the_placeholder():
    # vsl-langgraph 0.1.x, vsl-maf 0.2.x and vsl-ros2 0.1.x read
    # construct.assurance_basis.f2_modification and compare it with FULL.
    # A construct built without a basis must keep that read working and
    # must never look like a FULL claim.
    node = PreNode(name="gate", description="d", monitor=_stub_monitor)
    invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true)
    for construct in (node, invariant):
        assert construct.assurance_basis.f2_modification != F2Modification.FULL


@pytest.mark.parametrize("copier", ["deepcopy", "pickle"])
def test_placeholder_survives_copying(copier):
    import copy
    import pickle

    node = PreNode(name="gate", description="d", monitor=_stub_monitor)
    invariant = Invariant(name="inv-copy", description="d", rule=_always_true)
    for construct in (node, invariant):
        if copier == "deepcopy":
            copied = copy.deepcopy(construct)
        else:
            copied = pickle.loads(pickle.dumps(construct.assurance_basis))
            copied = type(construct)(**{**construct.__dict__, "assurance_basis": copied})
        with pytest.warns(FutureWarning, match="assurance_level is deprecated"):
            assert copied.assurance_level is None


def test_a_caller_basis_equal_in_value_to_the_placeholder_still_warns():
    same_values = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.NONE)
    with pytest.warns(FutureWarning):
        Invariant(name="inv-eq", description="d", rule=_always_true, assurance_basis=same_values)


def test_invariant_on_violation_defaults_to_none():
    invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true)
    assert invariant.on_violation is None


def test_invariant_on_violation_round_trips_when_set():
    terminal = TerminalState(name="governance_failure_terminal", description="d")
    invariant = Invariant(
        name=_unique_name("inv"),
        description="d",
        rule=_always_true,
        on_violation=terminal,
    )
    assert invariant.on_violation is terminal
    assert invariant.on_violation.name == "governance_failure_terminal"


def test_terminal_state_requires_human_authorised_transition_by_default():
    terminal = TerminalState(name="t", description="d", entry_conditions=("gamma < 0.8",))
    assert terminal.requires_human_authorised_transition is True


def test_pre_node_construction_with_defaults():
    node = PreNode(name="gate", description="d", monitor=_stub_monitor)
    assert node.gamma_threshold == 1.1
    assert node.fallback.max_retries == 3


def test_pre_node_positional_arguments_unchanged():
    # Positional order is the same as 0.3.x: name, description, monitor.
    node = PreNode("gate", "d", _stub_monitor)
    assert node.monitor is _stub_monitor


def test_pre_node_rejects_negative_max_retries():
    with pytest.raises(ValueError):
        PreNode(name="gate", description="d", monitor=_stub_monitor, fallback=Fallback(max_retries=-1))


def test_pre_node_rejects_non_positive_delta_factor():
    with pytest.raises(ValueError):
        PreNode(name="gate", description="d", monitor=_stub_monitor, fallback=Fallback(delta_factor=0))


def test_register_invariant_and_lookup():
    name = _unique_name("registered")
    invariant = Invariant(name=name, description="d", rule=_always_true)
    register_invariant(invariant)
    assert invariant in registered_invariants()


def test_register_invariant_rejects_duplicate_name():
    name = _unique_name("dup")
    invariant_a = Invariant(name=name, description="a", rule=_always_true)
    invariant_b = Invariant(name=name, description="b", rule=_always_true)
    register_invariant(invariant_a)
    with pytest.raises(ValueError):
        register_invariant(invariant_b)


def test_drift_monitor_protocol_call_shape():
    # No pytest-asyncio dependency in this zero-third-party-dep package --
    # drive the coroutine directly via asyncio.run().
    estimate = asyncio.run(_stub_monitor("some input"))
    assert isinstance(estimate, GammaEstimate)
    assert estimate.sufficient()
