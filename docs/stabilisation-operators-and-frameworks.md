# Stabilisation Operators and VSL Constructs: How They Relate to Governance Frameworks

## What this document is, and what it deliberately is not

**This document does not claim compliance, either.** It is a companion to
[`governance-frameworks.md`](./governance-frameworks.md), extending the same exercise to two things that document
doesn't cover: the nine **Stabilisation Operators** (SO-1–SO-9, plus the SO-8b variant) from Paper 5 ("Toward a Basis
Representation of Drift Forensics"), and a construct-first index of the five VSL constructs already mapped there.

Nothing below asserts that using a Stabilisation Operator, or a VSL construct, satisfies any clause, article,
function, or control in any framework named. Every mapping is "an attempt at addressing this stated goal," in the
same sense `governance-frameworks.md` uses that phrase — not a proof, not a citation that settles anything, and not
a substitute for a qualified auditor looking at a real deployment.

## A distinction worth being precise about: SOs are not a vsl-core construct

The Stabilisation Operators are a **taxonomy of response strategies**, defined in Paper 5 at the level of "what kind
of correction does this drift class call for" — they are not, themselves, a class or function anywhere in
`vsl_core`. Cross-checked against `vsl-core-primitives.json`: the package implements `PreNode`, `Invariant`,
`AllowedState`/`InadmissibleState`, `AssuranceBasis`, `Cluster`, the identity layer (`IdentityKey`,
`request_re_enablement()`), `VerbaLedger`, and `VerbaCertificate`. There is no `StabilisationOperator` class.

So a direct "SO-4 satisfies framework X" claim would be citing something that isn't actually built. The honest
chain is three links, not two:

**Stabilisation Operator (Paper 5 taxonomy)** → **vsl-core primitive that structurally implements that kind of
response, if one exists** → **the framework language `governance-frameworks.md` already attempts to address with
that primitive.**

Where no vsl-core primitive implements a given SO today, that's stated plainly below — the same "we don't attempt
to address this" discipline `governance-frameworks.md` uses for ASI04, ASI06, and several others.

---

## Stabilisation Operators, mapped through vsl-core primitives to frameworks

| SO | Proposed function (Paper 5) | vsl-core primitive | Framework hooks (via that primitive, see `governance-frameworks.md`) |
|---|---|---|---|
| **SO-1** Boundary Enforcement | Active maintenance of a boundary between Allowed and Inadmissible States — a constraint that cannot be crossed without triggering a Pre-Node. Every boundary must state both what it blocks *and* what it permits (Two-Sided Gate Condition). | **`PreNode`**, directly — SO-1's own definition names the Pre-Node mechanism. Also `Invariant` for the always-on case. | OWASP ASI01/ASI02 (Example A), NIST GOVERN 1.7 ("deactivated when necessary"), EU AI Act Art. 9, IMDA Dimension 1 (bounding risk upfront) — all already attempted via `PreNode` in `governance-frameworks.md`. |
| **SO-2** Semantic Reanchoring | Reconnection of drifted meaning-representations to a stable reference point, identified from the system's own governance specification. | **None.** Reconnecting a meaning-representation is a model/inference-time operation; nothing in vsl-core's structural constructs (gate, hard rule, state classification) does this. | *We don't attempt a framework mapping for this SO* — there's no primitive under it to hang one on. |
| **SO-3** Distributional Rebalancing | Restoration of a target distribution by correcting weight drift across competing objectives. | **None.** Same reasoning as SO-2 — this is a training/inference-time correction, outside what a decision-gating library does. | *We don't attempt a framework mapping for this SO.* |
| **SO-4** Attractor Disruption | Precise breaking of an attractor's basin of attraction once the system has already entered it — distinct from SO-1 in that it acts after entry, not before. | **`Invariant.on_violation → TerminalState`**, loosely. An `Invariant` violation forcing immediate entry into a named `TerminalState` is the closest structural analogue to "breaking out of an already-entered state" that vsl-core has — though vsl-core's mechanism is a hard stop, not the more surgical "disrupt and continue" SO-4 describes. | EU AI Act Art. 14 ("halt in a safe state"), OWASP ASI01 ("pausing execution on unexpected goal shift") — both already attempted via `Invariant`/`TerminalState` (Example B) in `governance-frameworks.md`. Treat this row as a looser fit than the others; SO-4's "disrupt without halting" framing doesn't fully match vsl-core's halt-based mechanism. |
| **SO-5** Coherence Enforcement | Compelling internal consistency across the output space, imposed as a structural requirement. | **`Invariant`**, as a general always-on consistency rule — reasonable fit, not a precise one. | Same framework hooks as `Invariant` generally: EU AI Act Art. 14, NIST GOVERN. No stronger claim than that. |
| **SO-6** Signal Amplification | Strengthening the governance signal above the noise floor — reveals information already present rather than adding new information. | **None cleanly.** `AssuranceBasis` is the closest adjacent idea (it forces a stated basis rather than an asserted grade), but that's a measurement/grading primitive, not a signal-amplification one — the fit is weak enough that we're not asserting it. | *We don't attempt a framework mapping for this SO.* |
| **SO-7** Trajectory Redirection | Changing the system's path through state space without halting its motion — uses drift energy rather than opposing it. | **None.** vsl-core's model is binary: a transition either clears its gate/rule, or it doesn't (halt, escalate, retry). There's no "redirect a running trajectory while it continues" primitive. | *We don't attempt a framework mapping for this SO* — the redirect-without-halting mechanism the SO describes isn't something vsl-core builds today. |
| **SO-8** State Reinitialisation | Complete reset of accumulated state while preserving the governance specification — a new Instance with a new Identity Key. | **`request_re_enablement()`** (`identity.py`, `governance.py`), directly — this is close to a literal implementation of SO-8's own definition (Example C). | NIST MANAGE ("supersede, disengage, or deactivate"; "recovery"), EU AI Act Art. 14 (the human-authorised way back out), IMDA Dimension 2 (human accountability) — all already attempted via `request_re_enablement()` in `governance-frameworks.md`. |
| **SO-8b** Inversion Recapture | A State Reinitialisation variant where the energy of the Terminal State itself becomes the fuel for renewal. | **`request_re_enablement()`**, specifically when invoked on an `Instance` that entered a `TerminalState` — same primitive as SO-8, narrower trigger condition. | Same hooks as SO-8. No separate framework language distinguishes the "recapture" framing from plain reinitialisation. |
| **SO-9** Integrity Restoration | Reconstruction of the governance mechanism itself from verified anchors, invoked only when the monitoring or specification system has been compromised. | **`GovernanceAuthority` + `request_re_enablement()` with `Evidence`** (Example C) — a named human authority and structured evidence are the closest thing vsl-core has to "verified anchors." | OWASP ASI10 Rogue Agents ("recovery requiring fresh attestation and human approval") is the strongest single hook — SO-9's own definition ("invoked when the mechanism itself has been corrupted") is close to ASI10's own framing almost word for word. Also NIST GOVERN 1.5/1.7, IMDA Dimension 2. |

**Summary: 6 of the 10 SO entries (SO-1, SO-4, SO-5, SO-8, SO-8b, SO-9) route through an actual vsl-core primitive
and inherit that primitive's existing framework attempts. 4 (SO-2, SO-3, SO-6, SO-7) don't correspond to anything
vsl-core implements today, and no framework mapping is attempted for them.** That 6-of-10 split is the honest
answer, not a rounding-up.

---

## The five VSL constructs, construct-first

`governance-frameworks.md` is organised framework-first (nine sections, each listing which primitives might apply).
This is the same information, reorganised construct-first, as a navigation aid — every line below is a restatement
of something already in that document, not a new claim. See the original for the exact quoted framework text and
the full caveats around each.

| Construct | Frameworks where it appears in `governance-frameworks.md` |
|---|---|
| **Pre-Node** (`PreNode`) | OWASP ASI01, ASI02, ASI05 · NIST MEASURE (via `AssuranceBasis`, always paired with a `PreNode`) · EU AI Act Art. 9, Art. 15 · IMDA Dimension 1 · SOC 2 CC7 · OWASP LLM06 (excessive autonomy half) |
| **Invariant** | EU AI Act Art. 14 (paired with `TerminalState`) · OWASP ASI01 (goal-shift escalation) |
| **Allowed State / Inadmissible State** | Underlies every framework row that cites `PreNode` or `Invariant` — every classified outcome resolves to one of these two, so they're implicit wherever a gate or rule is cited rather than called out as a separate row in the source document. |
| **Terminal State** | EU AI Act Art. 14 (the halt-to-safe-state mechanism) · NIST GOVERN 1.7 (deactivation) |
| **(Identity layer /** `request_re_enablement()` **— not a construct in the same sense, included for completeness)** | NIST GOVERN, MANAGE · EU AI Act Art. 14 · OWASP ASI09, ASI10 · IMDA Dimension 2 · SOC 2 CC6 |

---

## What this document does not claim

Same list as `governance-frameworks.md`, extended:

- It does not claim any Stabilisation Operator satisfies, maps to, or complies with any framework requirement.
  Every hook above is "an attempt," inherited from the underlying vsl-core primitive's own existing attempt — never
  a new, independent claim about the SO itself.
- It does not stretch a mapping for SO-2, SO-3, SO-6, or SO-7 just to have something in every row. Four of ten
  having no honest primitive to hang a framework hook on is stated as-is.
- It does not claim the SO-4 and SO-5 rows are as solid as SO-1, SO-8, SO-8b, or SO-9 — they're flagged as looser
  fits because the underlying primitive only partially matches the SO's own stated behaviour.
- It does not claim vsl-core, the Stabilisation Operator taxonomy, or this document has been reviewed by anyone
  with actual authority to make a compliance determination. Same closing note as `governance-frameworks.md`: that
  determination belongs to a qualified outside reader looking at a real deployment.
