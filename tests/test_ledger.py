import time
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from vsl_core.immudb_store import ImmuDBConfig, ImmuDBLedgerStore, ImmuDBSyncError
from vsl_core.exceptions import LedgerIntegrityError
from vsl_core.ledger import (
    DRIFT_DETECTED_KEY,
    HUMAN_AUTHORISED_TRANSITION,
    LEDGER_SCHEMA_VERSION,
    RE_ENABLEMENT,
    VERIFICATION_RESULT_KEY,
    GENESIS_HASH,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerEntryType,
    VerbaLedger,
    VerificationResult,
)


def test_bare_module_constants_match_enum_members():
    assert HUMAN_AUTHORISED_TRANSITION is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
    assert RE_ENABLEMENT is LedgerEntryType.RE_ENABLEMENT


class FakeImmuDBClient:
    def __init__(self):
        self.values = {}
        self.writes = 0
        self.fail = False
        self.fail_after_commit = False

    def verifiedGet(self, key):
        if self.fail:
            raise ConnectionError("offline")
        if key not in self.values:
            return None
        return SimpleNamespace(value=self.values[key], verified=True)

    def verifiedSet(self, key, value):
        self.values[key] = value
        self.writes += 1
        if self.fail_after_commit:
            raise TimeoutError("response lost")
        return SimpleNamespace(verified=True)


def test_immudb_dual_write_preserves_identical_entries(tmp_path):
    client = FakeImmuDBClient()
    config = ImmuDBConfig(username="writer", password="secret")
    store = ImmuDBLedgerStore(tmp_path / "ledger.jsonl", config, client=client)
    ledger = VerbaLedger(store)
    first = ledger.write_monitor(identity_key="sys-1", drift_detected=False)
    second = ledger.write_monitor(identity_key="sys-2", drift_detected=True)
    assert [json.loads(value) for value in client.values.values()] == [first.to_dict(), second.to_dict()]
    assert list(store.entries_for_identity("sys-1")) == [first]
    assert store.last_entry() == second
    assert ledger.verify_integrity()
    assert store.sync() == 0
    assert client.writes == 2


def test_immudb_failure_retains_local_entry_and_restart_syncs(tmp_path):
    client = FakeImmuDBClient()
    client.fail = True
    config = ImmuDBConfig(username="writer", password="secret")
    path = tmp_path / "ledger.jsonl"
    store = ImmuDBLedgerStore(path, config, client=client)
    with pytest.raises(ImmuDBSyncError) as caught:
        VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    assert caught.value.entry == store.last_entry()
    assert len(list(store.all_entries())) == 1
    client.fail = False
    reopened = ImmuDBLedgerStore(path, config, client=client)
    assert reopened.sync() == 1
    assert reopened.sync() == 0
    assert len(client.values) == 1


def test_immudb_uncertain_commit_is_not_duplicated_on_retry(tmp_path):
    client = FakeImmuDBClient()
    client.fail_after_commit = True
    store = ImmuDBLedgerStore(
        tmp_path / "ledger.jsonl", ImmuDBConfig(username="writer", password="secret"), client=client
    )
    with pytest.raises(ImmuDBSyncError):
        VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    client.fail_after_commit = False
    assert store.sync() == 0
    assert client.writes == 1


def test_immudb_sync_refuses_conflicting_remote_entry(tmp_path):
    client = FakeImmuDBClient()
    store = ImmuDBLedgerStore(
        tmp_path / "ledger.jsonl", ImmuDBConfig(username="writer", password="secret"), client=client
    )
    VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    key = next(iter(client.values))
    client.values[key] = b"conflicting data"
    with pytest.raises(LedgerIntegrityError, match="conflicts"):
        store.sync()
    assert client.values[key] == b"conflicting data"


def test_immudb_sync_refuses_truncated_local_chain(tmp_path):
    client = FakeImmuDBClient()
    path = tmp_path / "ledger.jsonl"
    store = ImmuDBLedgerStore(path, ImmuDBConfig(username="writer", password="secret"), client=client)
    VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    path.write_text("", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="ahead"):
        store.sync()


def test_immudb_sync_refuses_tampered_local_chain(tmp_path):
    client = FakeImmuDBClient()
    path = tmp_path / "ledger.jsonl"
    store = ImmuDBLedgerStore(path, ImmuDBConfig(username="writer", password="secret"), client=client)
    VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    path.write_text(path.read_text(encoding="utf-8").replace("sys-1", "sys-9"), encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="corrupted"):
        store.sync()
    assert client.writes == 1


def test_immudb_config_from_env_and_password_is_not_in_repr(monkeypatch):
    monkeypatch.setenv("IMMUDB_USERNAME", "writer")
    monkeypatch.setenv("IMMUDB_PASSWORD", "private-password")
    monkeypatch.setenv("IMMUDB_PORT", "4322")
    monkeypatch.setenv("IMMUDB_DATABASE", "auditdb")
    config = ImmuDBConfig.from_env()
    assert config.port == 4322
    assert config.database == "auditdb"
    assert "private-password" not in repr(config)


def test_immudb_config_requires_credentials(monkeypatch):
    monkeypatch.delenv("IMMUDB_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="IMMUDB_PASSWORD"):
        ImmuDBConfig.from_env()


def test_immudb_sdk_connection_is_lazy_and_uses_supplied_settings(tmp_path, monkeypatch):
    client = FakeImmuDBClient()
    client.login = Mock()
    client.shutdown = Mock()
    factory = Mock(return_value=client)
    root_factory = Mock()
    monkeypatch.setitem(sys.modules, "immudb", SimpleNamespace(ImmudbClient=factory))
    monkeypatch.setitem(sys.modules, "immudb.client", SimpleNamespace(PersistentRootService=root_factory))
    config = ImmuDBConfig(
        username="writer", password="secret", host="audit-host", port=4322,
        database="auditdb", timeout=3, public_key_file="server.pem",
    )
    with ImmuDBLedgerStore(tmp_path / "ledger.jsonl", config) as store:
        factory.assert_not_called()
        assert store.sync() == 0
        factory.assert_called_once_with(
            "audit-host:4322", rs=root_factory.return_value, timeout=3, publicKeyFile="server.pem"
        )
        root_factory.assert_called_once_with(str(tmp_path / "ledger.jsonl.immudb-state"))
        client.login.assert_called_once_with("writer", "secret", database=b"auditdb")
    client.shutdown.assert_called_once()


def test_immudb_sdk_login_failure_closes_client(tmp_path, monkeypatch):
    client = SimpleNamespace(login=Mock(side_effect=ConnectionError("offline")), shutdown=Mock())
    monkeypatch.setitem(sys.modules, "immudb", SimpleNamespace(ImmudbClient=Mock(return_value=client)))
    monkeypatch.setitem(sys.modules, "immudb.client", SimpleNamespace(PersistentRootService=Mock()))
    store = ImmuDBLedgerStore(tmp_path / "ledger.jsonl", ImmuDBConfig(username="writer", password="secret"))
    with pytest.raises(ImmuDBSyncError):
        store.sync()
    client.shutdown.assert_called_once()


def test_immudb_read_proof_failure_does_not_overwrite(tmp_path):
    client = FakeImmuDBClient()
    store = ImmuDBLedgerStore(
        tmp_path / "ledger.jsonl", ImmuDBConfig(username="writer", password="secret"), client=client
    )
    client.verifiedGet = Mock(return_value=SimpleNamespace(value=b"untrusted", verified=False))
    with pytest.raises(LedgerIntegrityError, match="proof"):
        store.sync()
    assert client.writes == 0


def test_immudb_write_proof_failure_reports_committed_local_entry(tmp_path):
    client = FakeImmuDBClient()
    client.verifiedSet = Mock(return_value=SimpleNamespace(verified=False))
    store = ImmuDBLedgerStore(
        tmp_path / "ledger.jsonl", ImmuDBConfig(username="writer", password="secret"), client=client
    )
    with pytest.raises(ImmuDBSyncError) as caught:
        VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    assert caught.value.entry == store.last_entry()
    assert isinstance(caught.value.__cause__, LedgerIntegrityError)


def test_immudb_concurrent_stores_share_one_chain(tmp_path):
    client = FakeImmuDBClient()
    config = ImmuDBConfig(username="writer", password="secret")
    path = tmp_path / "ledger.jsonl"
    stores = [ImmuDBLedgerStore(path, config, client=client) for index in range(4)]

    def write_entry(index):
        return VerbaLedger(stores[index % 4]).write_monitor(identity_key="sys-1", drift_detected=False)

    with ThreadPoolExecutor(max_workers=4) as executor:
        entries = list(executor.map(write_entry, range(12)))
    assert sorted(entry.sequence for entry in entries) == list(range(12))
    assert len(client.values) == 12
    assert VerbaLedger(stores[0]).verify_integrity()


def test_immudb_namespaces_keep_independent_ledgers_separate(tmp_path):
    client = FakeImmuDBClient()
    for namespace in ("agent-one", "agent-two"):
        config = ImmuDBConfig(username="writer", password="secret", namespace=namespace)
        store = ImmuDBLedgerStore(tmp_path / (namespace + ".jsonl"), config, client=client)
        VerbaLedger(store).write_monitor(identity_key=namespace, drift_detected=False)
    assert len(client.values) == 2


@pytest.mark.parametrize("missing_code", ["NOT_FOUND", "UNKNOWN"])
def test_immudb_grpc_not_found_is_missing_but_other_errors_propagate(tmp_path, missing_code):
    grpc = pytest.importorskip("grpc")

    class RemoteError(grpc.RpcError):
        def __init__(self, status, message="key not found"):
            self.status = status
            self.message = message

        def code(self):
            return self.status

        def details(self):
            return self.message

    client = FakeImmuDBClient()
    client.verifiedGet = Mock(side_effect=RemoteError(getattr(grpc.StatusCode, missing_code)))
    store = ImmuDBLedgerStore(
        tmp_path / "ledger.jsonl", ImmuDBConfig(username="writer", password="secret"), client=client
    )
    VerbaLedger(store).write_monitor(identity_key="sys-1", drift_detected=False)
    assert client.writes == 1
    for status, message in (
        (grpc.StatusCode.PERMISSION_DENIED, "key not found"),
        (grpc.StatusCode.UNKNOWN, "connection failed"),
    ):
        client.verifiedGet.side_effect = RemoteError(status, message)
        with pytest.raises(ImmuDBSyncError):
            store.sync()
    assert client.writes == 1


@pytest.mark.parametrize("settings", [{"port": 0}, {"timeout": 0}, {"timeout": float("nan")}, {"namespace": " "}])
def test_immudb_config_rejects_invalid_settings(settings):
    with pytest.raises(ValueError):
        ImmuDBConfig(username="writer", password="secret", **settings)


def test_seven_entry_types_exist():
    assert {e.value for e in LedgerEntryType} == {
        "MONITOR",
        "PRE_NODE",
        "VERIFICATION",
        "TERMINAL",
        "SPECIFICATION_UPDATE",
        "HUMAN_AUTHORISED_TRANSITION",
        "RE_ENABLEMENT",
    }


def test_in_memory_write_chains_entries_and_verifies():
    ledger = VerbaLedger(InMemoryLedgerStore())
    e1 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    e2 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    assert e1.sequence == 0
    assert e2.sequence == 1
    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.entry_hash
    assert ledger.verify_integrity() is True


def test_empty_ledger_verifies_true():
    ledger = VerbaLedger()
    assert ledger.verify_integrity() is True


def test_jsonl_store_round_trips_and_verifies(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "SUFFICIENT"})

    # Re-instantiate fresh, over the same file, proving persistence not an in-memory artifact.
    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is True
    assert len(list(reopened.store.all_entries())) == 3


def test_tamper_detection_flips_one_byte_in_payload(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"marker": "TAMPER_TARGET_VALUE"})
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "SUFFICIENT"})
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.HUMAN_AUTHORISED_TRANSITION, identity_key="sys-1", payload={})

    # Step 0: untouched chain verifies True -- this alone is not the test.
    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    # Flip exactly one byte inside a string value -- same length, still valid JSON.
    raw = path.read_bytes()
    assert b"TAMPER_TARGET_VALUE" in raw
    tampered = raw.replace(b"TAMPER_TARGET_VALUE", b"TAMPER_TARGET_VALUX", 1)
    assert tampered != raw
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    # Fresh instantiation over the same (now-tampered) file.
    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False

    # Diagnosability: audit() must still run without raising on a tampered chain.
    report = reopened.audit()
    assert report is not None


def test_tamper_detection_catches_prev_hash_mutation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # Mutate the prev_hash field's value in the second line only, keeping JSON valid
    # (a hex hash string of the same length, guaranteed different from the real one).
    import json

    second = json.loads(lines[1])
    real_prev_hash = second["prev_hash"]
    mutated_prev_hash = ("f" if real_prev_hash[0] != "f" else "0") + real_prev_hash[1:]
    second["prev_hash"] = mutated_prev_hash
    lines[1] = json.dumps(second, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_write_refuses_to_extend_a_chain_with_a_corrupted_last_entry(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"marker": "TAMPER_TARGET_VALUE"})

    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"TAMPER_TARGET_VALUE", b"TAMPER_TARGET_VALUX", 1))

    corrupted = VerbaLedger(JsonlLedgerStore(path))
    with pytest.raises(LedgerIntegrityError):
        corrupted.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})


def test_audit_all_checks_pass_on_a_well_formed_chain():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", instance_id="inst-1", payload={"drift_detected": True})
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", instance_id="inst-1", payload={"result": "INSUFFICIENT"})
    ledger.write(LedgerEntryType.SPECIFICATION_UPDATE, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.HUMAN_AUTHORISED_TRANSITION, identity_key="sys-1", payload={})

    report = ledger.audit()
    assert report.all_passed is True
    assert report.checks_failed == ()


def test_audit_catches_drift_flagged_monitor_with_no_pre_node():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", instance_id="inst-1", payload={"drift_detected": True})
    # No PRE_NODE follows.
    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" in report.checks_failed
    assert report.violations["drift_flagged_monitor_has_pre_node"]


def test_audit_catches_pre_node_with_no_verification():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={})
    report = ledger.audit()
    assert "pre_node_has_verification" in report.checks_failed


def test_audit_catches_insufficient_verification_with_no_spec_update():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "INSUFFICIENT"})
    report = ledger.audit()
    assert "insufficient_verification_has_specification_update" in report.checks_failed


def test_audit_catches_terminal_with_no_human_authorised_transition():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    report = ledger.audit()
    assert "terminal_has_human_authorised_transition" in report.checks_failed


def test_audit_monitoring_gap_check_requires_explicit_parameter():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    report_without_param = ledger.audit()
    assert "no_monitoring_gaps" not in report_without_param.checks_failed


def test_issue_certificate_none_on_failed_audit():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    assert ledger.issue_certificate() is None


def test_issue_certificate_present_on_passed_audit_and_carries_disclaimer():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    cert = ledger.issue_certificate()
    assert cert is not None
    assert cert.audit_report.all_passed is True
    assert "does not guarantee" in cert.NOTE
    assert "does not guarantee" in str(cert)
    assert cert.certificate_hash


def test_write_monitor_uses_the_canonical_drift_detected_key():
    ledger = VerbaLedger()
    entry = ledger.write_monitor(identity_key="sys-1", drift_detected=True)
    assert entry.payload[DRIFT_DETECTED_KEY] is True


def test_write_monitor_extra_payload_cannot_clobber_drift_detected_key():
    ledger = VerbaLedger()
    entry = ledger.write_monitor(identity_key="sys-1", drift_detected=True, extra_payload={DRIFT_DETECTED_KEY: False})
    assert entry.payload[DRIFT_DETECTED_KEY] is True


def test_write_verification_uses_the_canonical_result_key():
    ledger = VerbaLedger()
    entry = ledger.write_verification(identity_key="sys-1", result=VerificationResult.INSUFFICIENT)
    assert entry.payload[VERIFICATION_RESULT_KEY] == "INSUFFICIENT"


def test_audit_checks_pass_using_entries_written_via_convenience_methods():
    ledger = VerbaLedger()
    ledger.write_monitor(identity_key="sys-1", instance_id="inst-1", drift_detected=True)
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={})
    ledger.write_verification(identity_key="sys-1", instance_id="inst-1", result=VerificationResult.INSUFFICIENT)
    ledger.write(LedgerEntryType.SPECIFICATION_UPDATE, identity_key="sys-1", payload={})

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" not in report.checks_failed
    assert "insufficient_verification_has_specification_update" not in report.checks_failed


def test_audit_still_supports_raw_literal_payload_keys_for_backward_compat():
    # Existing callers writing raw dicts with the literal string keys must
    # keep working -- the constants' values are unchanged, just now named.
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": True})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "INSUFFICIENT"})
    report = ledger.audit()
    assert "insufficient_verification_has_specification_update" in report.checks_failed


def test_audit_without_caused_by_can_false_pass_on_interleaved_decisions():
    # Documents a real limitation of the timestamp-based fallback, not a
    # desired behavior: two unrelated decisions on the same identity/
    # instance can be confused. A drift-flagged MONITOR for "payment" is
    # followed by an unrelated PRE_NODE for "email" -- without caused_by,
    # check2 can't tell them apart and incorrectly reports the payment
    # drift as resolved. The next test proves caused_by fixes exactly this.
    ledger = VerbaLedger()
    ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, extra_payload={"decision": "payment"}
    )
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={"decision": "email"})

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" not in report.checks_failed


def test_audit_with_caused_by_correctly_catches_interleaved_decision_violation():
    ledger = VerbaLedger()
    payment_monitor = ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, extra_payload={"decision": "payment"}
    )
    # An unrelated PRE_NODE for a different decision, explicitly marked as
    # caused by something other than the payment monitor.
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by="some-other-monitor-entry-id",
        payload={"decision": "email"},
    )

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" in report.checks_failed
    assert payment_monitor.entry_id in report.violations["drift_flagged_monitor_has_pre_node"]


def test_audit_with_caused_by_correctly_resolves_the_right_decision():
    ledger = VerbaLedger()
    payment_monitor = ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, extra_payload={"decision": "payment"}
    )
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by=payment_monitor.entry_id,
        payload={"decision": "payment"},
    )
    # An unrelated interleaved decision, correctly not confused with the above.
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by="some-other-monitor-entry-id",
        payload={"decision": "email"},
    )

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" not in report.checks_failed


def test_tamper_detection_catches_decision_id_mutation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, decision_id="DECISION_MARKER_VALUE"
    )

    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    raw = path.read_bytes()
    assert b"DECISION_MARKER_VALUE" in raw
    tampered = raw.replace(b"DECISION_MARKER_VALUE", b"DECISION_MARKER_VALUX", 1)
    assert tampered != raw
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_tamper_detection_catches_caused_by_mutation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write_monitor(identity_key="sys-1", instance_id="inst-1", drift_detected=True)
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by="CAUSED_BY_MARKER_VALUE",
        payload={},
    )

    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    raw = path.read_bytes()
    assert b"CAUSED_BY_MARKER_VALUE" in raw
    tampered = raw.replace(b"CAUSED_BY_MARKER_VALUE", b"CAUSED_BY_MARKER_VALUX", 1)
    assert tampered != raw
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_from_dict_defaults_missing_causal_fields_to_none():
    # Simulates loading an entry persisted before decision_id/caused_by
    # existed -- must not raise a KeyError, and must default cleanly.
    from vsl_core.ledger import LedgerEntry

    legacy_data = {
        "entry_id": "e1",
        "sequence": 0,
        "entry_type": "MONITOR",
        "identity_key": "sys-1",
        "cluster_key": None,
        "instance_id": None,
        "payload": {},
        "timestamp": 0.0,
        "prev_hash": GENESIS_HASH,
        "entry_hash": "irrelevant-for-this-test",
    }
    entry = LedgerEntry.from_dict(legacy_data)
    assert entry.decision_id is None
    assert entry.caused_by is None


def test_decision_id_and_caused_by_round_trip_through_jsonl(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    monitor = ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, decision_id="dec-1"
    )
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        decision_id="dec-1",
        caused_by=monitor.entry_id,
        payload={},
    )

    reopened = VerbaLedger(JsonlLedgerStore(path))
    entries = list(reopened.store.all_entries())
    assert entries[0].decision_id == "dec-1"
    assert entries[1].decision_id == "dec-1"
    assert entries[1].caused_by == monitor.entry_id
    assert reopened.verify_integrity() is True


def test_write_stamps_current_schema_version():
    ledger = VerbaLedger()
    entry = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    assert entry.schema_version == LEDGER_SCHEMA_VERSION


def test_bare_ledger_entry_construction_does_not_assume_a_schema_version():
    # A LedgerEntry built directly (not through VerbaLedger.write()) should
    # not silently claim the current schema version -- only write() stamps
    # it, so a bare construction (e.g. reconstructing a legacy entry) stays
    # honest about not actually knowing which version it was written under.
    from vsl_core.ledger import LedgerEntry

    entry = LedgerEntry(entry_type=LedgerEntryType.MONITOR, identity_key="sys-1")
    assert entry.schema_version is None


def test_tamper_detection_catches_schema_version_mutation(tmp_path):
    import json

    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})

    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    lines = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    assert data["schema_version"] == LEDGER_SCHEMA_VERSION
    data["schema_version"] = "9.9"
    lines[0] = json.dumps(data, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_current_checkpoint_none_on_empty_ledger():
    ledger = VerbaLedger()
    assert ledger.current_checkpoint() is None


def test_current_checkpoint_matches_last_entry_and_updates_on_new_writes():
    ledger = VerbaLedger()
    e1 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    cp1 = ledger.current_checkpoint()
    assert cp1 is not None
    assert cp1.sequence == e1.sequence
    assert cp1.entry_hash == e1.entry_hash

    e2 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    cp2 = ledger.current_checkpoint()
    assert cp2.sequence == e2.sequence
    assert cp2.entry_hash == e2.entry_hash
    assert cp2.sequence != cp1.sequence
    assert cp2.entry_hash != cp1.entry_hash


def test_jsonl_store_is_safe_under_concurrent_writers_from_separate_instances(tmp_path):
    # Each worker builds its OWN JsonlLedgerStore pointed at the same file --
    # exactly the shape of race that a threading.RLock scoped to one Python
    # object cannot prevent, and that _CrossProcessFileLock now closes.
    # Before that lock existed, this was a real, reproducible way to corrupt
    # the chain (duplicate/skipped sequence numbers from two writers reading
    # the same last_entry() before either appended).
    import concurrent.futures

    path = tmp_path / "ledger.jsonl"
    writes_per_worker = 25
    workers = 4

    def write_many(worker_id: int) -> None:
        ledger = VerbaLedger(JsonlLedgerStore(path))
        for _ in range(writes_per_worker):
            ledger.write_monitor(identity_key=f"worker-{worker_id}", drift_detected=False)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(write_many, w) for w in range(workers)]
        for f in futures:
            f.result()

    final = VerbaLedger(JsonlLedgerStore(path))
    entries = list(final.store.all_entries())
    assert len(entries) == writes_per_worker * workers
    assert final.verify_integrity() is True
    # Sequence numbers must be a contiguous 0..N-1 run with no duplicates or
    # gaps -- exactly what a lost race would corrupt.
    assert sorted(e.sequence for e in entries) == list(range(writes_per_worker * workers))
