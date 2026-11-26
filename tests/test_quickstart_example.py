"""The README quickstart is examples/quickstart.py: run it, so the README can't drift from the package."""

import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "quickstart.py"


def test_quickstart_allows_then_blocks():
    result = subprocess.run(
        [sys.executable, "-W", "error::FutureWarning", str(EXAMPLE)], capture_output=True, text=True, check=True
    )
    assert result.stdout.splitlines() == [
        "refunded $120 on A100",
        "blocked: Invariant 'refund-cap' violated",
    ]
    assert result.stderr == ""


def test_readme_record_snippet_reads_before_action():
    # The README's "Keep a record of each decision" snippet, as written there.
    import asyncio

    from vsl_core import Enforcement, Invariant, VerbaLedger
    from vsl_core.conformance.reference_adapter import PlainPythonReferenceAdapter

    def issue_refund(order_id, amount):
        return f"refunded ${amount} on {order_id}"

    ledger = VerbaLedger()

    async def within_cap(args):
        allowed = args["amount"] <= 500
        ledger.write_gate_decision(identity_key="refund-agent", primitive_name="refund-cap",
                                   allowed=allowed, decision_id=args["order_id"])
        return allowed

    cap = Invariant(name="refund-cap", description="Refunds of $500 or less.", rule=within_cap)
    gate = PlainPythonReferenceAdapter().compile_invariant(cap)

    async def refund(args):
        await gate(args)
        result = issue_refund(**args)
        ledger.write_action(identity_key="refund-agent", action_name="issue_refund",
                            decision_id=args["order_id"])
        return result

    asyncio.run(refund({"order_id": "A100", "amount": 120}))
    assert ledger.verify_integrity()
    assert ledger.enforcement("A100") == Enforcement.BEFORE_ACTION
