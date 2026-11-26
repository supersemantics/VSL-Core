import pytest

from vsl_core import ACTION_KEY, DRIFT_DETECTED_KEY, Enforcement, VerbaLedger


def _gate(ledger, decision, allowed, name="refund-cap"):
    return ledger.write_gate_decision(
        identity_key="refund-agent", primitive_name=name, allowed=allowed, decision_id=decision
    )


def _action(ledger, decision, name="issue_refund"):
    return ledger.write_action(identity_key="refund-agent", action_name=name, decision_id=decision)


def test_allow_then_action_is_before_action():
    ledger = VerbaLedger()
    _gate(ledger, "d1", True)
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.BEFORE_ACTION


def test_action_with_no_gate_record_is_after_action():
    ledger = VerbaLedger()
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.AFTER_ACTION


def test_action_recorded_before_the_gate_is_after_action():
    ledger = VerbaLedger()
    _action(ledger, "d1")
    _gate(ledger, "d1", True)
    assert ledger.enforcement("d1") == Enforcement.AFTER_ACTION


def test_action_after_a_deny_is_after_action():
    ledger = VerbaLedger()
    _gate(ledger, "d1", False)
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.AFTER_ACTION


def test_deny_with_no_action_held():
    ledger = VerbaLedger()
    _gate(ledger, "d1", False)
    assert ledger.enforcement("d1") == Enforcement.BEFORE_ACTION


def test_allow_with_no_action_record_is_not_observed():
    ledger = VerbaLedger()
    _gate(ledger, "d1", True)
    assert ledger.enforcement("d1") == Enforcement.NOT_OBSERVED


def test_unknown_decision_is_not_observed():
    assert VerbaLedger().enforcement("missing") == Enforcement.NOT_OBSERVED


def test_deny_then_allow_retry_then_action_is_before_action():
    ledger = VerbaLedger()
    _gate(ledger, "d1", False)
    _gate(ledger, "d1", True)
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.BEFORE_ACTION


def test_every_gate_must_allow_before_the_action():
    ledger = VerbaLedger()
    _gate(ledger, "d1", True, name="refund-cap")
    _gate(ledger, "d1", False, name="fraud-check")
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.AFTER_ACTION
    assert ledger.enforcement("d1", primitive_name="refund-cap") == Enforcement.BEFORE_ACTION
    assert ledger.enforcement("d1", primitive_name="fraud-check") == Enforcement.AFTER_ACTION


def test_a_second_action_without_a_fresh_allow_still_counts_the_earlier_allow():
    # Each action is judged by the latest record of each gate before it.
    ledger = VerbaLedger()
    _gate(ledger, "d1", True)
    _action(ledger, "d1")
    _gate(ledger, "d1", False)
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.AFTER_ACTION


def test_other_decisions_do_not_interfere():
    ledger = VerbaLedger()
    _gate(ledger, "d1", True)
    _action(ledger, "d2")
    _action(ledger, "d1")
    assert ledger.enforcement("d1") == Enforcement.BEFORE_ACTION
    assert ledger.enforcement("d2") == Enforcement.AFTER_ACTION


def test_enforcement_by_decision():
    ledger = VerbaLedger()
    _gate(ledger, "ok", True)
    _action(ledger, "ok")
    _action(ledger, "skipped")
    _gate(ledger, "pending", True)
    ledger.write_monitor(identity_key="refund-agent", drift_detected=False, decision_id="plain-monitor")
    assert ledger.enforcement_by_decision() == {
        "ok": Enforcement.BEFORE_ACTION,
        "skipped": Enforcement.AFTER_ACTION,
        "pending": Enforcement.NOT_OBSERVED,
    }


def test_action_record_shape():
    entry = _action(VerbaLedger(), "d1")
    assert entry.payload[ACTION_KEY] == {"name": "issue_refund"}
    assert entry.payload[DRIFT_DETECTED_KEY] is False
    assert entry.decision_id == "d1"


def test_action_record_keys_cannot_be_overwritten():
    entry = VerbaLedger().write_action(
        identity_key="a", action_name="issue_refund", decision_id="d1",
        extra_payload={ACTION_KEY: "forged", DRIFT_DETECTED_KEY: True, "amount": 40},
    )
    assert entry.payload[ACTION_KEY] == {"name": "issue_refund"}
    assert entry.payload[DRIFT_DETECTED_KEY] is False
    assert entry.payload["amount"] == 40


@pytest.mark.parametrize("kwargs", [{"decision_id": ""}, {"action_name": " "}])
def test_write_action_rejects_missing_fields(kwargs):
    args = {"identity_key": "a", "action_name": "issue_refund", "decision_id": "d1", **kwargs}
    with pytest.raises(ValueError):
        VerbaLedger().write_action(**args)


def test_action_records_do_not_break_the_audit():
    ledger = VerbaLedger()
    _gate(ledger, "d1", True)
    _action(ledger, "d1")
    report = ledger.audit()
    assert report.all_passed
    assert len(report.checks_passed) == 5
    assert ledger.verify_integrity()


def test_enforcement_survives_a_jsonl_round_trip(tmp_path):
    from vsl_core import JsonlLedgerStore

    path = tmp_path / "decisions.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    _gate(ledger, "d1", True)
    _action(ledger, "d1")
    reloaded = VerbaLedger(JsonlLedgerStore(path))
    assert reloaded.enforcement("d1") == Enforcement.BEFORE_ACTION
