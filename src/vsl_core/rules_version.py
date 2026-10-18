"""The version of the assurance rules this package applies.

"Assurance rules" means the decisions vsl-core makes on a caller's behalf:
how GammaEstimate.sufficient() judges a Gamma estimate against a threshold,
and how AssuranceBasis.derived_level turns F1/F2 into an AssuranceLevel.

The version is written into every gate-decision ledger record
(VerbaLedger.write_gate_decision), so a record can always be read under the
rules that produced it, even after a later release changes one. Bump it
whenever either rule changes meaning, and say what changed in CHANGELOG.md.

Deliberately a module of its own with no imports: vsl_core.ledger depends
only on exceptions.py and this constant, so the Ledger subtree stays
vendorable on its own.
"""

ASSURANCE_RULES_VERSION: str = "2026.10"
