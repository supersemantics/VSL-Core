"""Gate a tool call in 5 lines: the README quickstart, runnable as is.

    pip install super-semantics-vsl
    python quickstart.py
"""

import asyncio

from vsl_core import AssuranceBasis, F2Modification, Invariant, InvariantViolation
from vsl_core.conformance.reference_adapter import PlainPythonReferenceAdapter


def issue_refund(order_id: str, amount: float) -> str:  # your existing tool, unchanged
    return f"refunded ${amount} on {order_id}"


# The 5 lines: a rule, the gate built from it, and a call to the gate before the tool runs.
async def within_cap(args): return args["amount"] <= 500
cap = Invariant(name="refund-cap", description="Refunds of $500 or less.", rule=within_cap,
                assurance_basis=AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.NONE))
gate = PlainPythonReferenceAdapter().compile_invariant(cap)


async def refund(args: dict) -> str:
    await gate(args)  # raises InvariantViolation before the tool runs
    return issue_refund(**args)


async def main() -> None:
    print(await refund({"order_id": "A100", "amount": 120}))
    try:
        await refund({"order_id": "A200", "amount": 9000})
    except InvariantViolation as denied:
        print(f"blocked: {denied.reason}")


if __name__ == "__main__":
    asyncio.run(main())
