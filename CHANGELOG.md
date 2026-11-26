# Changelog

What changed in each release, and why. Newest first.

## 0.4.0 (unreleased): enforcement is computed, not declared

### Changed: constructs no longer take an assurance claim

**Before:** `PreNode`, `Invariant` and `AllowedState` required
`assurance_basis=AssuranceBasis(f1_pre_commitment=..., f2_modification=...)`, and derived a
HIGH/MEDIUM/LOW `assurance_level` from it. Developers had to pick an F2 value, and nothing could check
the value they picked.

**After:** constructs need only their name, description and rule or monitor. `assurance_basis` is
optional and ignored: passing one raises a `FutureWarning` and changes nothing. `assurance_level`
still exists, warns, and returns `None` unless a basis was passed. `AssuranceBasis`,
`F2Modification` and `AssuranceLevel` still import. All of these are removed in 1.0. Positional
arguments are unchanged for `PreNode` and `Invariant`. On `AllowedState`, `assurance_basis` became
keyword-only, so the order is now `(name, description, measurement, validity_conditions)`; a call
in the 0.3.x positional order raises `TypeError` instead of silently putting the basis into
`measurement`.

**Compatibility:** adapters released before 0.4.0 read `construct.assurance_basis.f2_modification`.
A construct built without a basis holds a placeholder, so those reads keep working and never look
like a FULL claim. The placeholder has its own private type, so it is still recognised after
`copy.deepcopy()` or pickling. The conformance suite no longer passes a basis.

### Added: action records and `enforcement()`

`VerbaLedger.write_action(identity_key=..., action_name=..., decision_id=...)` records that a guarded
action ran: a MONITOR entry (`drift_detected` False) with an `ACTION_KEY` (`"action"`) payload of
`{name}`. `VerbaLedger.enforcement(decision_id)` compares the decision's gate records with its action
records and returns an `Enforcement`: `BEFORE_ACTION`, `AFTER_ACTION` or `NOT_OBSERVED`.
`enforcement_by_decision()` does it for every decision. No new entry type: every ledger store
accepts the records as is. `audit()` keeps its five checks.

### Fixed: action and handover records no longer count as monitoring

`audit(max_monitor_gap_seconds=...)` used to count every MONITOR entry when looking for gaps,
including handover records (0.3.0) and now action records. Frequent actions could hide a real gap
in monitoring. The gap check now skips both; gate decisions and plain monitor entries still count.
A ledger with handovers can therefore fail `no_monitoring_gaps` where 0.3.x passed it, when the
only records in a gap were handovers.

**Why:** a declared level said what the developer believed, not what happened. Whether a gate ran
before its action is a fact the ledger can show, so vsl-core now computes it from the records.
vsl-core does not calculate F2: it can't be declared, only measured from how the model behaves at
the guarded call. The README, guide, troubleshooting, governance-frameworks doc and
`vsl-core-primitives.json` no longer ask anyone to declare it.

The assurance rules version stays `2026.10`: the Gamma rule it covers is unchanged.

## 0.3.2 (2026-11-14, tag `v0.3.2`): quickstart, gate a tool call in 5 lines

The code is unchanged from 0.3.1.

**Before:** the README opened with what vsl-core is and isn't, then sent new readers to a long guide.
There was no short, runnable path from `pip install` to a blocked tool call.

**After:** a "Quickstart: gate a tool call in 5 lines" section near the top of the README: a rule, an
`Invariant`, the gate, and the call before the tool, with each line explained in plain language. It
also shows how to record each decision in the ledger, and points to the framework adapters and the
starter templates. The same code is in `examples/quickstart.py`, and a test runs it, so the README
can't drift from the package.

**Why:** the README is the PyPI page. Someone arriving there should be able to gate a real tool call
in a minute, and see what the gate does and does not claim (it blocks; it doesn't steer a model).

## 0.3.1 — published on PyPI (2026-11-13, tag `v0.3.1`)

The first version on PyPI: `pip install super-semantics-vsl` (imported as `vsl_core`). The code is
unchanged from 0.3.0.

**Before:** vsl-core was installed from GitHub (`pip install git+https://github.com/supersemantics/VSL-Core.git`),
and its README said it was not yet on PyPI. Its links to `docs/` were relative, so they would break on
the PyPI page, which shows the README.

**After:** the README gives `pip install super-semantics-vsl`, its links point to GitHub, and the
package lists its repository, changelog and issue tracker. A pushed release tag publishes to PyPI from
GitHub Actions through Trusted Publishing (`.github/workflows/publish.yml`): the tests run, the tag is
checked against the version, and no token is stored anywhere.

**Why:** an install from a registry, with a version, is what most people expect; and adapters on PyPI
can't depend on a GitHub URL (PyPI rejects direct-URL dependencies).

## 0.3.0 — handover records

### Added: `write_handover()` and `HANDOVER_KEY`

One agent handing part of a decision to another is now recorded. `VerbaLedger.write_handover(identity_key=..., to_identity_key=..., decision_id=..., reason=..., cluster_key=...)` writes a MONITOR entry (`drift_detected` False: a handover is not drift) whose payload carries `handover` = `{from_identity, to_identity, reason}` under the shared `decision_id` and, for a declared Cluster, its `cluster_key`. The receiving agent passes that entry's `entry_id` as `caused_by` on its first `write_gate_decision()`, so the decision trace reads as one causal chain across both agents.

**Why.** Multi-agent failures are interactions: each agent's own gate can pass while the hand-off between them goes unchecked. Before this, a decision shared by two agents showed both agents' records but nothing marked where one handed over to the other, so no one could check that the receiver gated what it was handed. No new entry type and no ledger schema change: every ledger store accepts it as is. The assurance rules version stays `2026.10`.

### Documentation

- The README's "The ledger doesn't write itself" section now shows `write_handover()` with the receiver's `caused_by`, since the README is the practical guide adapters point to.
- The README no longer links a separate hosted ledger package as a storage option; it says any store implementing `LedgerStore` plugs in the same way.

## Unreleased — documentation only

No code behaviour changes, and the assurance rules version stays `2026.10`: `derived_level` and `sufficient()` are untouched.

### Corrected: how F2 is explained

F2 is judged at the call the gate guards — what the application does to the model there — and is never earned by the gate itself. A gate that only allows or blocks, with nothing shaped at the guarded call, is `NONE`; the application's own system prompt, RAG context or input redaction makes it `PARTIAL`; `FULL` needs a model whose internals the application controls.

**Why.** Several examples labelled gates `F2Modification.FULL` (and so `HIGH`) because they "directly determine whether the call happens" — the worked example and retrofit case study in `docs/building-with-vsl-core.md`, examples A and B in `docs/governance-frameworks.md`, and canonical patterns A and B in `docs/vsl-core-primitives.json`. Deciding whether an action happens is F1, not F2, so those gates are `NONE` (`LOW`). Because the primitives file and the building guide are meant to be handed to AI coding assistants, the overclaim would have been copied into new agents. The README and docstrings also said a gate before a hosted model API is `PARTIAL` because the gate "can only rewrite the prompt"; the `PARTIAL` comes from the prompt the application sends, not from the gate.

### Added: level versus enforcement

The README, `AssuranceLevel` and `AssuranceBasis` now state that the level measures influence on the model only. A gate with F1=True and F2=`NONE` derives `LOW` and still blocks every action it denies; report enforcement (F1) separately rather than raising F2.

### Added: what a Gamma value means today

README and the `GammaEstimate` docstring: monitors return a gate score in Gamma units; build it as a ratio where 1.0 means break-even, fail closed with 0.0, never use a raw 0–1 confidence, label fixed 2.0/0.0 returns as pass/fail encodings, use an `Invariant` for absolute rules, and record decisions with `write_gate_decision()`. Two matching common mistakes added to `vsl-core-primitives.json`.

## 0.2.0 — assurance rules version 2026.10

### Changed: how a Gamma threshold is applied (behaviour change only when `delta_estimation_error` > 0)

`GammaEstimate.sufficient(threshold)` now passes when `gamma_hat` is strictly greater than `max(threshold, 1 + delta_estimation_error)`.

**Why.** A threshold already includes an estimation-error allowance: 1.1 is the 10% allowance (`ROBUST_GAMMA_DEFAULT_THRESHOLD`'s own comment says so), 1.2 is 20%. The old check divided `gamma_hat` by `(1 + delta)` and then compared the result with the threshold, so a declared delta was counted on top of the allowance the threshold already held. With `delta_estimation_error=0.1` and the default threshold, the gate required `gamma_hat > 1.21` instead of `1.1`. The new rule is the source spec's robust condition (robust Gamma above 1) with the threshold as the minimum allowance: a declared delta only raises the bar when it is larger than that allowance.

| `gamma_hat` | delta | threshold | Before | Now |
|---|---|---|---|---|
| any | 0 | any | unchanged | unchanged |
| 1.15 | 0.1 | 1.1 | denied (needed > 1.21) | allowed (needs > 1.1) |
| 1.15 | 0.2 | 1.1 | denied (needed > 1.32) | denied (needs > 1.2) |
| 1.25 | 0.2 | 1.1 | denied (needed > 1.32) | allowed (needs > 1.2) |

**Who is affected.** Only monitors that set `delta_estimation_error` above 0. Their gates now allow some estimates they previously denied. Monitors that leave delta at its default of 0 behave exactly as before, and exactly on the bar still does not pass.

New: `GammaEstimate.required_gamma_hat(threshold)` returns the bar `gamma_hat` must exceed. `robust_gamma()` is unchanged.

### Added: `VerbaLedger.write_gate_decision()`

One standard record of a gate's decision, so every agent records gates the same way: a `MONITOR` entry with `primitive_name` (the gate's declared name), `allowed`, `rules_version` and `drift_detected` (`not allowed`). For a PreNode, pass the monitor's `GammaEstimate` and the PreNode's `gamma_threshold`: `allowed` is computed with the gate's own `sufficient()` check, and the record also carries `gamma_hat`, `delta_estimation_error`, `robust_gamma`, `gamma_threshold` and `required_gamma_hat`. For an Invariant, pass `allowed`. A record that contradicts the gate's own check, or that is missing the gate name or threshold, is refused with `ValueError`. The payload keys are exported as `PRIMITIVE_NAME_KEY`, `GATE_ALLOWED_KEY` and `RULES_VERSION_KEY`.

As before, nothing is written automatically: recording a gate's decision is still a call your own code makes.

### Added: `ASSURANCE_RULES_VERSION`

`"2026.10"`, exported from `vsl_core` and written into every gate-decision record. It identifies the rules vsl-core applied: how `sufficient()` judges Gamma, and how `AssuranceBasis.derived_level` turns F1/F2 into a level. It will be bumped, with an entry here, whenever either rule changes meaning, so older records can always be read under the rules that produced them.

The Ledger module still imports nothing from the rest of the package except `exceptions.py` and the import-free `rules_version.py`, so it stays vendorable on its own.

## 0.1.0

Initial release: VSL constructs, F1/F2 `AssuranceBasis`, Gamma and the other metrics, the hash-chained `VerbaLedger` with in-memory, JSONL and optional immudb stores, the Drift Class catalog, and the adapter conformance suite.
