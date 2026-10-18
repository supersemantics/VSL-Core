"""VerbaLedger.write_gate_decision: the standard record of one gate's decision."""

import ast
import inspect

import pytest

import vsl_core
from vsl_core import (
    ASSURANCE_RULES_VERSION,
    ROBUST_GAMMA_DEFAULT_THRESHOLD,
    ROBUST_GAMMA_HIGH_STAKES_THRESHOLD,
    GammaEstimate,
)
from vsl_core import ledger as ledger_module
from vsl_core.ledger import (
    DRIFT_DETECTED_KEY,
    GATE_ALLOWED_KEY,
    PRIMITIVE_NAME_KEY,
    RULES_VERSION_KEY,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerEntryType,
    VerbaLedger,
)


@pytest.fixture
def ledger():
    return VerbaLedger(InMemoryLedgerStore())


def test_pre_node_decision_records_gamma_and_the_bar_applied(ledger):
    estimate = GammaEstimate(gamma_hat=1.3)
    entry = ledger.write_gate_decision(
        identity_key="refund-agent",
        primitive_name="refund-within-policy",
        estimate=estimate,
        gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
        decision_id="d-1",
    )

    assert entry.entry_type is LedgerEntryType.MONITOR
    assert entry.decision_id == "d-1"
    assert entry.payload == {
        "gamma_hat": 1.3,
        "delta_estimation_error": 0.0,
        "robust_gamma": 1.3,
        "gamma_threshold": ROBUST_GAMMA_DEFAULT_THRESHOLD,
        "required_gamma_hat": ROBUST_GAMMA_DEFAULT_THRESHOLD,
        PRIMITIVE_NAME_KEY: "refund-within-policy",
        GATE_ALLOWED_KEY: True,
        RULES_VERSION_KEY: ASSURANCE_RULES_VERSION,
        DRIFT_DETECTED_KEY: False,
    }


def test_allowed_is_computed_with_the_gates_own_check(ledger):
    denied = ledger.write_gate_decision(
        identity_key="a",
        primitive_name="payment",
        estimate=GammaEstimate(gamma_hat=1.15),
        gamma_threshold=ROBUST_GAMMA_HIGH_STAKES_THRESHOLD,
    )
    assert denied.payload[GATE_ALLOWED_KEY] is False
    assert denied.payload[DRIFT_DETECTED_KEY] is True

    with_delta = ledger.write_gate_decision(
        identity_key="a",
        primitive_name="budget",
        estimate=GammaEstimate(gamma_hat=1.15, delta_estimation_error=0.1),
        gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
    )
    assert with_delta.payload[GATE_ALLOWED_KEY] is True
    assert with_delta.payload["required_gamma_hat"] == ROBUST_GAMMA_DEFAULT_THRESHOLD


def test_invariant_decision_needs_only_allowed(ledger):
    entry = ledger.write_gate_decision(
        identity_key="email-agent",
        primitive_name="no-external-recipients",
        allowed=False,
    )
    assert entry.payload == {
        PRIMITIVE_NAME_KEY: "no-external-recipients",
        GATE_ALLOWED_KEY: False,
        RULES_VERSION_KEY: ASSURANCE_RULES_VERSION,
        DRIFT_DETECTED_KEY: True,
    }


def test_contradictory_allowed_is_refused(ledger):
    with pytest.raises(ValueError, match="contradicts"):
        ledger.write_gate_decision(
            identity_key="a",
            primitive_name="refund",
            allowed=True,
            estimate=GammaEstimate(gamma_hat=0.5),
            gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
        )
    assert list(ledger.store.all_entries()) == []


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"primitive_name": "", "allowed": True}, "primitive_name"),
        ({"primitive_name": "g", "estimate": GammaEstimate(gamma_hat=2.0)}, "gamma_threshold"),
        ({"primitive_name": "g", "gamma_threshold": 1.1, "allowed": True}, "without an estimate"),
        ({"primitive_name": "g"}, "allowed=True/False"),
        ({"primitive_name": "g", "allowed": "yes"}, "allowed=True/False"),
    ],
)
def test_incomplete_records_are_refused(ledger, kwargs, message):
    with pytest.raises(ValueError, match=message):
        ledger.write_gate_decision(identity_key="a", **kwargs)


def test_extra_payload_cannot_overwrite_the_record(ledger):
    entry = ledger.write_gate_decision(
        identity_key="a",
        primitive_name="refund",
        estimate=GammaEstimate(gamma_hat=0.5),
        gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
        extra_payload={
            "order_id": "o-7",
            GATE_ALLOWED_KEY: True,
            DRIFT_DETECTED_KEY: False,
            PRIMITIVE_NAME_KEY: "other",
            RULES_VERSION_KEY: "1999.01",
            "gamma_hat": 9.0,
        },
    )
    assert entry.payload["order_id"] == "o-7"
    assert entry.payload[GATE_ALLOWED_KEY] is False
    assert entry.payload[DRIFT_DETECTED_KEY] is True
    assert entry.payload[PRIMITIVE_NAME_KEY] == "refund"
    assert entry.payload[RULES_VERSION_KEY] == ASSURANCE_RULES_VERSION
    assert entry.payload["gamma_hat"] == 0.5


def test_records_round_trip_through_a_persistent_store(tmp_path):
    path = tmp_path / "ledger.jsonl"
    VerbaLedger(JsonlLedgerStore(path)).write_gate_decision(
        identity_key="a",
        primitive_name="refund",
        estimate=GammaEstimate(gamma_hat=2.0, delta_estimation_error=0.0),
        gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
    )

    reopened = VerbaLedger(JsonlLedgerStore(path))
    (entry,) = reopened.store.all_entries()
    assert entry.payload[GATE_ALLOWED_KEY] is True
    assert reopened.verify_integrity()


def test_rules_version_is_exported():
    assert vsl_core.ASSURANCE_RULES_VERSION == ASSURANCE_RULES_VERSION == "2026.10"


def test_ledger_module_still_never_imports_metrics():
    tree = ast.parse(inspect.getsource(ledger_module))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 1
    }
    assert imported == {"exceptions", "rules_version"}
