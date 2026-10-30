"""write_handover(): one agent handing part of a decision to another."""
import pytest

from vsl_core.ledger import HANDOVER_KEY, LedgerEntryType, VerbaLedger


def test_handover_is_a_non_drift_monitor_linked_to_the_receivers_check():
    ledger = VerbaLedger()
    handover = ledger.write_handover(
        identity_key="planner", to_identity_key="dispatcher", decision_id="d-1",
        reason="dispatch the switching plan", cluster_key="cluster-abc",
    )
    assert handover.entry_type == LedgerEntryType.MONITOR
    assert handover.payload[HANDOVER_KEY] == {
        "from_identity": "planner", "to_identity": "dispatcher", "reason": "dispatch the switching plan"}
    assert handover.payload["drift_detected"] is False
    assert (handover.decision_id, handover.cluster_key) == ("d-1", "cluster-abc")

    check = ledger.write_gate_decision(
        identity_key="dispatcher", primitive_name="switching-safety", allowed=True,
        decision_id="d-1", cluster_key="cluster-abc", caused_by=handover.entry_id,
    )
    assert check.caused_by == handover.entry_id
    assert ledger.verify_integrity()
    # A handover is not drift, so it needs no follow-up of its own.
    assert "drift_flagged_monitor_has_pre_node" in ledger.audit().checks_passed


def test_handover_needs_a_decision_and_a_different_receiver():
    ledger = VerbaLedger()
    with pytest.raises(ValueError):
        ledger.write_handover(identity_key="a", to_identity_key="b", decision_id="", reason="r")
    with pytest.raises(ValueError):
        ledger.write_handover(identity_key="a", to_identity_key="a", decision_id="d", reason="r")


def test_extra_payload_cannot_overwrite_the_handover():
    ledger = VerbaLedger()
    entry = ledger.write_handover(
        identity_key="a", to_identity_key="b", decision_id="d", reason="r",
        extra_payload={HANDOVER_KEY: "forged", "drift_detected": True, "note": "kept"},
    )
    assert entry.payload[HANDOVER_KEY]["to_identity"] == "b"
    assert entry.payload["drift_detected"] is False and entry.payload["note"] == "kept"
