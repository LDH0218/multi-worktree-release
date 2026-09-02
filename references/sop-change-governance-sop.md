# SOP Change Governance SOP

This is the human procedure for creating, reviewing, editing, publishing, deprecating, and rolling
back one of the eight MWR SOPs. It separates editorial maintenance from normative governance change and
keeps a release batch on one proven SOP meaning. It adds no document registry, version authority,
machine state, Schema field, validator rule, role binding, or permission. Git history, the existing
Plan/Task/Card/handoff records, and the repository's current document set remain the evidence.

The four execution SOPs keep their existing boundaries: [Conversation Rotation SOP](conversation-rotation-sop.md)
alone governs conversation lifecycle; [Task Lifecycle SOP](task-lifecycle-sop.md) governs task delivery;
[Release SOP](release-sop.md) governs release boundaries; and [Exception and Recovery SOP](exception-recovery-sop.md)
governs stops. The four governance SOPs route audit, adoption, SOP change, and retention decisions but
cannot override those core procedures or persisted contracts.

## Trigger, owner, inputs, evidence, and outcomes

**Triggers.** Use this SOP before proposing or editing any MWR SOP, before classifying or reviewing a
change, before freezing a release batch that depends on the SOP, before integration or publication,
and when deprecating, rolling back, or discovering an in-flight semantic change.

**Owner.** The document owner proposes the change and supplies its rationale. Master owns the class,
scope, Task/Plan revision, compatibility decision, integration, and release-batch decision. A Worker
may edit only its assigned paths; a reviewer reports evidence and does not grant document or release
authority.

**Required inputs.** Read the current eight-SOP map, core SOP boundaries, `SKILL.md`, repository
instructions, methodology, templates, Schema, validator, relevant Plan/Task/Card/handoff and release
evidence, the exact source/baseline and complete diff, the proposed old and new rules, affected
triggers/owners/evidence/stops, compatibility and rollback path, reviewer, and any authorization or
release impact. A contract, runtime, v2, FAST, or release implementation request is out of scope for
this SOP.

**Retained evidence.** Keep the exact source and changed paths, old/new rule comparison, change class,
owner and reviewer, Task Spec/Plan identity and revision when applicable, baseline and commit, checks
and results, compatibility and release-freeze decision, integration mapping, deprecation route, and
rollback/stop decision in existing Git and task/review projections. Do not create an SOP registry or
silently rewrite a persisted record.

**Results.** `PASS` means the class, authority boundary, compatibility, evidence, and review are all
proven and the owner may take only the next already authorized step. `FAIL` means the proposal
contradicts a contract/SOP, changes meaning without the required STRICT revision, or a forbidden action
occurred; stop and preserve. `NOT_PROVEN` means a required source, owner, reviewer, compatibility fact,
authorization, or provenance item is missing, ambiguous, stale, or unverifiable; do not infer approval.
These labels are human review results, not machine states or permissions.

**Stop conditions.** Stop under the Exception and Recovery SOP for wrong identity, baseline, scope,
owner, worktree, generation, dependency, source, revision, digest, or Card state; dirty or overlapping
material; a semantic change disguised as editorial; missing review or authorization; an in-flight silent
change; a request to alter Schema, validator, state transitions, FAST/v2/release implementation, or
conversation-lifecycle authority; or any unsanctioned synchronization, execution, publication,
destructive action, deletion, cleanup, amendment, or scope expansion.

## Change classes and ownership

Classify before editing. If the class is uncertain, use STRICT and stop until the owner decides.

| Class | Examples | Route and review |
| --- | --- | --- |
| Editorial | Typo, grammar, translation, formatting, link repair, or clarification that preserves every trigger, owner, evidence requirement, authority boundary, state meaning, and decision. | A bounded local edit may use FAST only when all FAST conditions hold; otherwise use STRICT. Run link and contradiction checks. |
| Normative governance | New/changed trigger, owner, evidence, stop condition, recovery rule, retention obligation, model/auth boundary, adoption rule, compatibility promise, release boundary, or deprecation meaning. | STRICT. Master owns the task/Plan, independent review, integration, and release impact decision. |
| Contract or implementation | Schema, validator, state transition, authorization semantics, FAST implementation, v2 routing, release script, or runtime behavior. | Outside this SOP. Stop and request a separately scoped Master task; never smuggle it into a document change. |

The document owner proposes the change and supplies its rationale. Master decides whether it is editorial
or normative, which SOPs and persisted contracts are affected, whether a new Task Spec revision or
superseding task is required, and whether an in-flight release must stop. A Worker may edit only the
allowed paths of its current assignment; a handoff or message never grants document or release authority.

## 1. Propose and inspect the change

Before touching a file, read the current eight-SOP map, `SKILL.md`, README, AGENTS, methodology,
templates, Schema, validator, relevant Plans/Task Specs/Cards, and current release evidence. Record in
existing task or review evidence:

- the exact current source commit, document paths, owner, scope, and intended outcome;
- the old rule and proposed rule, with affected triggers, responsibilities, required evidence,
  decisions, stops, retention, and conversation-lifecycle boundaries;
- compatibility with v1 records, current state transitions, default-deny authorization, model routing,
  Candidate/Gate evidence, closeout/rollover, and the other seven SOPs;
- whether the proposal changes executable content, a release input, or only wording; and
- the required checks, reviewer, release-batch impact, rollback path, and any missing evidence.

Do not infer an SOP's authority from its filename, ordering, heading, or a copied template. If the
proposed rule conflicts with a persisted record or core SOP, report `NOT_PROVEN`/`FAIL` and route it to
Master; do not “fix” the record from the document.

## 2. Review and compatibility gate

Review the complete diff, not only the new paragraph. Use automated checks for JSON Schema/contract and
unit validation, digest or revision checks where records are involved, Markdown links/headings, and
`git diff --check`. Perform manual checks for:

- one authority owner per decision and no role/conversation registry added;
- complete evidence and explicit `PASS`/`FAIL`/`NOT_PROVEN` handling, with missing evidence conservative;
- no new machine state, contract field, authorization borrowing, model/service-tier confusion, or
  publication/closeout/deletion shortcut;
- no contradiction among the eight SOPs, with the Conversation Rotation SOP still sole lifecycle
  authority and the core task/release/recovery SOPs retaining their boundaries;
- compatibility with retained v1 records and historical evidence, including terminal immutability and
  exact candidate/closeout rules; and
- scope, ownership, dependency, baseline, worktree, and preserved material.

An automated pass cannot prove semantic compatibility or user authorization. A missing check, source,
reviewer, or provenance item is `NOT_PROVEN`, not a pass.

## 3. Freeze the governing SOP for a release batch

Once a Task Spec/Plan is published, a Worker is active, a handoff is awaiting integration, or a release
candidate/Gate is being evaluated, treat the governing SOP and its semantic inputs as frozen for that
operation. Do not silently apply a new meaning halfway through the batch.

- A purely editorial correction that demonstrably changes no decision meaning may be reviewed and
  integrated under the existing task boundary, with the complete diff and checks recorded.
- A normative change requires a new STRICT task/Plan revision or a superseding task when objective,
  owner, worktree, frozen baseline, authority, or release identity changes. Preserve the predecessor
  evidence and use successor commits; never amend a handed-off commit.
- Master decides whether affected work continues under the old frozen SOP, is gated, is reworked, or is
  superseded. A new integrated HEAD invalidates release-candidate evidence under the Release SOP.
- Candidate approval, closeout, or an existing authorization cannot make an in-flight SOP change
  retroactive or authorize publication.

The freeze is a human decision over existing records, not a new state or lock field.

## 4. Publish, deprecate, and record history

After review, Master integrates the scoped change and records its commit, Task Spec/Plan identity,
handoff, checks, and any Worker-to-Master mapping in the existing projections. Use the commit SHA and
existing Git/document history as the change record; do not create a second SOP registry or authoritative
version record. If the repository already has release notes or a changelog, update it only when the
current assignment explicitly allows it.

Deprecation is a documented routing decision, not deletion:

1. Identify the replacement SOP or existing core authority and the exact boundary being retired.
2. Prove that current records, links, templates, and in-flight releases have a compatible route.
3. Mark or route the old document through a reviewed STRICT change, preserving it until the retention
   policy and any explicit deletion decision are satisfied.
4. Keep the Conversation Rotation SOP unchanged as the sole conversation-lifecycle authority unless a
   separately authorized governance change explicitly addresses that authority.

Do not remove a deprecated file, history, link, or record automatically. A document can be deprecated
while still retained for historical interpretation.

## 5. Rollback and stop conditions

If a change is rejected, incompatible, incomplete, or discovered after integration to have changed
meaning unexpectedly, stop the affected operation and use the [Exception and Recovery SOP](exception-recovery-sop.md).
Rollback is a new reviewed, scoped change or the existing repository's reversible mechanism; it is not
`reset`, branch switching, deletion, cleanup, force-push, or amendment of an immutable handoff. Re-run
compatibility, contract, scope, and affected release checks after the rollback. If the prior meaning or
evidence cannot be proven, report `NOT_PROVEN` and retain the current records and material.

Stop immediately for wrong identity/baseline, dirty or overlapping material, missing ownership or
review, a semantic change disguised as editorial, a forbidden-path request, an in-flight silent change,
contract/runtime/v2/release implementation scope, missing authorization, or any proposed deletion or
unbounded external action. This SOP never authorizes synchronization, execution, publication,
destructive action, or automatic cleanup.

Compact review evidence may use this human projection; it is not a persisted machine record:

```text
SOP change review
Documents and owner: <PATHS / RESPONSIBLE ROLE>
Class: <EDITORIAL | NORMATIVE | CONTRACT_OR_IMPLEMENTATION_OUT_OF_SCOPE>
Current source/baseline: <COMMIT_OR_DIGEST>
Affected triggers, owners, evidence, and core boundaries: <DETAILS>
Release-batch freeze impact: <NONE | GATE/PLAN/TASKS_AND_DECISION>
Compatibility checks: <AUTOMATED / MANUAL / RESULTS>
Result: <PASS | FAIL | NOT_PROVEN>
Integration/rollback owner: <MASTER_OR_EXISTING_OWNER>
Deletion or external authority used: <NONE_OR_EXACT_SEPARATE_AUTHORITY>
```
