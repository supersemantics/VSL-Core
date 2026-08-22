# Troubleshooting

Every entry below was actually triggered against the real, installed `vsl-core` — not reasoned about from reading the code. This is the human-readable counterpart to [`vsl-core-primitives.json`](vsl-core-primitives.json)'s `common_mistakes` array, which is written for an AI coding assistant to consume, not for browsing on GitHub. One correction surfaced in the process: the JSON's entry for mistake A claims setting `assurance_level` raises `TypeError` — the real, reproduced exception is `FrozenInstanceError` (below).

| Symptom | Jump to |
|---|---|
| `FrozenInstanceError` setting `assurance_level` | [A](#a-setting-assurance_level-directly) |
| `AssuranceBasis.derived_level` won't go above `MEDIUM` no matter what you set `f2_modification` to try to force it | [B](#b-f2partial-caps-at-medium-cannot-be-forced-to-high) |
| A gate raised, but no `TerminalState`/ledger entry exists anywhere | [C](#c-a-terminalstateledger-write-does-not-happen-automatically) |
| `audit()` reports a check passed, but it matched the wrong entry | [D](#d-omitting-caused_by-lets-audit-correlate-the-wrong-entry) |
| Recovering whether a violation also halted the system by parsing `reason` text | [E](#e-terminal_state_name-is-a-direct-field) |
| `Instance._re_enable()` "works" with no authority involved | [F](#f-_re_enable-vs-request_re_enablement-both-work-only-one-is-audited) |
| Expecting `vsl_core.catalog` to scan your code and flag drift | [G](#g-the-drift-class-catalog-is-data-not-a-scanner) |

---

## A: setting `assurance_level` directly

**Symptom:**
```
FrozenInstanceError: cannot assign to field 'assurance_level'
```

**Cause:** `assurance_level` is a read-only `@property`, derived from `assurance_basis.derived_level` — it exists so a `PreNode`/`Invariant`/`AllowedState` can't claim a trust level without stating the F1/F2 facts that justify it. But the class itself is also a frozen dataclass, and Python's frozen-dataclass `__setattr__` override intercepts the assignment before it would even get to the "this is a property with no setter" complaint — so the actual exception is `dataclasses.FrozenInstanceError`, not the `TypeError` a plain read-only property would normally raise.

**Fix:** don't. Set `assurance_basis` at construction time with real F1/F2 facts; `assurance_level` follows automatically.

**Reproduced:**
```python
pn = PreNode(name="p", description="x", monitor=..., assurance_basis=BASIS)
pn.assurance_level = "HIGH"
```
```
FrozenInstanceError: cannot assign to field 'assurance_level'
```

---

## B: F2=PARTIAL caps at MEDIUM, cannot be forced to HIGH

**Symptom:** `AssuranceBasis.derived_level` returns `MEDIUM` even though you believe the mechanism deserves `HIGH`.

**Cause:** this is the F1/F2 table working as designed, not a bug — `F1=True` + `F2Modification.PARTIAL` is structurally capped at `MEDIUM`. The canonical case: a `PreNode` blocking a call to a hosted LLM API satisfies F1 (it runs before the call), but can only touch the prompt or sampling parameters, never logits or weights behind the API — that's `PARTIAL`, not `FULL`, no matter how confident you are in the check.

**Fix:** if the mechanism genuinely only touches a prompt/parameter, its ceiling is `MEDIUM` — that's accurate, not a shortfall to work around. `HIGH` requires the intervention to actually modify the mechanism producing the output (`F2Modification.FULL`): logit adjustment, activation steering, fine-tuning, constitutional training.

**Reproduced:**
```python
AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.PARTIAL).derived_level
# AssuranceLevel.MEDIUM
AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL).derived_level
# AssuranceLevel.HIGH
```

---

## C: a `TerminalState`/ledger write does not happen automatically

**Symptom:** a gate raises `InvariantViolation`/`AutomationDeniedException` correctly, but no `VerbaLedger` entry exists anywhere afterward, and nothing that looks like "the system halted" is recorded.

**Cause:** vsl-core does not intercept anything. The compiled gate raising is the only automatic part — writing a `TERMINAL` entry, actually halting further execution, and calling `request_re_enablement()` are all things the calling application must do explicitly after catching the exception. An `Invariant` naming a `TerminalState` via `on_violation` only means the *exception* records which `TerminalState` was entered (`terminal_state_name`) — it does not enter it on your behalf.

**Fix:** catch the exception, and in that `except` block, explicitly call `ledger.write(LedgerEntryType.TERMINAL, ...)` (or your own equivalent). See [`building-with-vsl-core.md`](building-with-vsl-core.md)'s "know what's automatic and what you write yourself."

**Reproduced:**
```python
try:
    await gate("candidate")
except InvariantViolation as e:
    print(f"gate raised: {e}")
print(f"ledger entries after the raise: {len(list(ledger.store.all_entries()))}")
```
```
gate raised: Invariant 'hard-rule' violated -- entering terminal state 'halt' (identity_key='conformance-test')
ledger entries after the raise: 0
```

---

## D: omitting `caused_by` lets `audit()` correlate the wrong entry

**Symptom:** `audit()` reports a check as passed, but the entry that satisfied it has nothing to do with the decision it's supposedly resolving.

**Cause:** without `caused_by`, `audit()`'s cross-referencing checks fall back to "same `identity_key`/`instance_id` and a later timestamp" — which is a heuristic, not a real causal link. Two unrelated decisions in flight on the same identity (a drift-flagged `MONITOR` entry and a completely unrelated `PRE_NODE` entry that merely comes later) can satisfy each other's check purely by timing.

**Fix:** populate `caused_by` with the exact `entry_id` an entry actually resolves whenever more than one decision can be in flight per identity/instance — `_causally_resolves()` treats an explicit `caused_by` as authoritative and stops considering unrelated entries a match, even if they'd otherwise coincidentally fit the timestamp heuristic.

**Reproduced** (a drift-flagged `MONITOR` entry and an unrelated `PRE_NODE` entry, no `caused_by` set):
```python
ledger.write_monitor(identity_key=str(identity), drift_detected=True)
ledger.write(LedgerEntryType.PRE_NODE, identity_key=str(identity), payload={"unrelated": "task"})
report = ledger.audit()
```
```
'drift_flagged_monitor_has_pre_node' in report.checks_passed -> True
# the unrelated PRE_NODE satisfied the check purely by coming later on the same identity
```

---

## E: `terminal_state_name` is a direct field

**Symptom:** code parsing `InvariantViolation.reason` (the free-text string) for the phrase "entering terminal state" to figure out whether a violation also halted the system.

**Cause:** this used to be the only way to recover that information, but isn't anymore — `InvariantViolation.terminal_state_name` is a real, structured field (`str | None`), set whenever the violated `Invariant.on_violation` named a `TerminalState`.

**Fix:** read `exc.terminal_state_name` directly.

**Reproduced:**
```python
except InvariantViolation as e:
    print(e.terminal_state_name)  # 'halt'
    print(e.reason)               # "Invariant 'hard-rule' violated -- entering terminal state 'halt'"
```

---

## F: `_re_enable()` vs `request_re_enablement()` — both work, only one is audited

**Symptom:** re-enablement "works" (a new `Instance` is produced) without any `GovernanceAuthority` or `Evidence` having been involved.

**Cause:** `Instance._re_enable()` is the bare mechanism — directly callable with just an `Evidence` object, no authority check. The leading underscore is deliberate (it was a public `re_enable()` until an external review flagged it as an easy accidental-bypass risk), but Python can't turn that into an actual guarantee — nothing stops the direct call.

**Fix:** always go through `governance.request_re_enablement()`, which pairs the new `Instance` with the `HumanAuthorisedTransition` record that authorises it — you cannot get one without the other through this path.

**Reproduced:**
```python
bypassed = instance._re_enable(evidence=evidence)   # succeeds, no authority anywhere
new_instance, transition = request_re_enablement(instance, authority, authorised_by="j.doe", evidence=evidence)
# also succeeds, but now transition.authorised_by='j.doe', transition.authority.name='Risk Committee' exist as a record
```
Nothing in `vsl-core` prevented the first call — same non-enforcement shape as `AutomationDeniedException`'s "cannot be silently caught."

---

## G: the Drift Class catalog is data, not a scanner

**Symptom:** expecting `vsl_core.catalog` to inspect your code or agent traffic and flag drift on its own.

**Cause:** it's a reference taxonomy — 45 Drift Classes and their Legion detection *heuristic definitions* (pattern strings, confidence tier, description), not executable detection logic. `only_validated_heuristics()` returns a `dict` of pattern definitions your own monitor/rule function could choose to check against — it doesn't scan anything itself. And **94% of the catalog's heuristics are self-labeled `SPECULATIVE`**; only 7 (concentrated in `DC-E13`, `DC-I11`, and the orphan `CLUSTER-HANDOVER` entry) carry real confidence (`only_validated_heuristics()` returns exactly these).

**Fix:** treat every match as "worth a human looking at," never as a confirmed finding, and call `catalog.loader.validate()` if you want the catalog's own known data-quality caveats before relying on any of it.

**Reproduced** (`only_validated_heuristics()`'s actual shape — pattern strings, not a running check):
```python
{'DC-E13': [('L1', LegionHeuristic(pattern_type='agent_handover_no_prenode',
    patterns=('.run(', '.invoke(', '.execute(', '.predict(', 'kickoff(', 'initiate_chat('),
    confidence='HIGH', description="...")), ...], 'DC-I11': [...], 'CLUSTER-HANDOVER': [...]}
```
`validate()`'s real, current findings:
```
- metadata.total_drift_classes claims 36 but the real computed count is 45. Do not trust the metadata field.
- legion_patterns.json contains ['CLUSTER-HANDOVER'] with no corresponding entry in drift_classes.json.
- 10 drift classes have zero Legion detection heuristics defined at all (mostly tier B/C/D, a coverage gap, not a data error).
```

---

## Still stuck?

- [`README.md`](../README.md) — construct-to-object mapping, the F1/F2 distinction, package layout.
- [`building-with-vsl-core.md`](building-with-vsl-core.md) — the decision heuristic, the five-step lifecycle, a full worked example.
- [`vsl-core-primitives.json`](vsl-core-primitives.json) — exact, structured facts for every primitive; every code sample in it has been executed against the real package.
