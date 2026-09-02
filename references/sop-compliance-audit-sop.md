# SOP Compliance Audit SOP

This is the runbook for auditing an operation that is actually being performed or has just been
performed under the Multi-Worktree Release method. It compares observed Git, worktree, conversation,
Plan, Task Spec, Card, handoff, authorization, and release evidence with the applicable human SOP and
existing Schema/validator contract. It adds no machine state, role registry, version authority, contract
field, or permission. `PASS`, `FAIL`, and `NOT_PROVEN` below are audit results, not persisted states.

The four execution SOPs remain authoritative for their own boundaries: the
[Conversation Rotation SOP](conversation-rotation-sop.md) is the sole conversation-lifecycle authority;
[Task Lifecycle SOP](task-lifecycle-sop.md) governs FAST/STRICT delivery;
[Release SOP](release-sop.md) governs integration, candidate, publication, closeout, and rollover; and
[Exception and Recovery SOP](exception-recovery-sop.md) governs safe stops. The governance SOPs in this
document set audit questions only and cannot override those procedures or persisted records.

## Ownership and audit triggers

The responsible owner audits evidence for the operation. Master owns audits of STRICT dispatch, Worker
handoffs, integration, release readiness, and MWR's own governance changes. A project's existing owner
or Master owns an adoption audit in that project. Only Master decides persistent role/conversation
rotation, Plan/Dispatch outcomes, integration, closeout, or release readiness; an auditor reports facts
and does not grant authority.

Audit at the earliest applicable boundary and repeat after any material change:

| Operation | Trigger and minimum decision |
| --- | --- |
| FAST | Before implementation and before any external write: prove every FAST condition, owned paths, bounded verification, and separate authorization. |
| STRICT dispatch | Before publication: reconcile Task Spec, Plan, worktree, branch, baseline, Card, dependency/ownership graph, model profile, authorization, and acceptance. |
| Worker execution/handoff | Before `ACTIVE`, before commit, and before handoff: verify identity, scope, preserved material, checks, immutable commit, and `AWAITING_INTEGRATION`. |
| Release | Before candidate approval, publication, push verification, closeout, and rollover: use the exact integrated HEAD and the Release SOP's separate boundaries. |
| Recovery | At the stop and before resumption: preserve evidence, classify the mismatch, and prove the selected Master decision and legal transition. |
| Adoption | Before enabling a project, after the pilot, and before wider use: prove inventory, ownership, state-root choice, version pin, pilot evidence, and exit path. |
| SOP change | Before review, before a release-batch freeze, and before integration/publication: prove the change class, affected contracts, compatibility, and governing-document fence. |
| Retention/retirement | Before archive, conversation retirement, worktree/branch retirement, or any deletion request: reconcile bindings, evidence, dirty material, references, and explicit authority. |
| Conversation rotation | At successor bootstrap and before predecessor archive: follow the Conversation Rotation SOP's complete confirmation and visibility checks. |

An audit is also required when a digest, revision, source, model, authorization, ownership, HEAD, or
status appears inconsistent. Do not wait for a convenient checkpoint to resolve an ambiguity.

## Entry criteria and minimum evidence

Define the audit target, owner, time boundary, and decision being requested. Then collect read-only
evidence from the authoritative sources before interpreting a message or human projection:

- absolute repository/worktree path, branch, full current `HEAD`, ancestry, status, dirty/untracked
  paths, and preserved user material;
- role, conversation generation, visible-binding result, Task/Plan/Card identities, record and semantic
  revisions, source thread, exact digests, handoffs, blockers, and current release identity;
- allowed and forbidden paths, dependency/ownership relationships, model profile, complete authorization
  envelope and digest, and the exact target for any requested external action;
- applicable SOP, Schema, validator result, acceptance commands, test output, commit subject/SHA,
  integration mapping, candidate/Gate evidence, archive bytes, or retention references; and
- the expected fact, observed fact, command or record that proves it, and the owner responsible for the
  next decision.

Missing, stale, ambiguous, conflicting, or unverifiable evidence is `NOT_PROVEN`; a prose assertion or
elapsed time cannot fill the gap. Never put secrets in the audit material.

## Audit procedure

1. Freeze the audit scope as a human snapshot: operation, identity, expected boundary, and evidence
   sources. This does not create a new record or freeze a release.
2. Read the applicable core SOP and this governance route. Compare persisted records and Git facts first;
   treat titles, Markdown projections, chat summaries, and branch-ahead counts as supporting evidence
   only.
3. Run bounded automated checks without performing the audited external action: Schema-first validator
   checks, digest recomputation, revision/state-transition checks, path and scope checks, dependency
   and parallel checks, Git reachability/ancestry/status checks, test commands, and Markdown/link checks
   where relevant.
4. Perform manual semantic checks: correct owner and one-to-one binding, complete evidence, no hidden
   authority transfer, no semantic overlap, no silent SOP change, no conversation-lifecycle bypass, and
   no archive/deletion or release-boundary confusion.
5. Evaluate every required criterion separately. Do not let an aggregate green result hide a missing
   required row, stale candidate, unproven provenance, or forbidden action.
6. Report the result to the owner. A failed or unproven audit stops the affected action before commit,
   execution, publication, deletion, synchronization, or release advancement.

Automated checks prove shape, integrity, and observable mechanics; they do not prove ownership intent,
semantic compatibility, user authorization, or that a conversation is genuinely unique. Manual checks
must not be replaced by a passing test suite.

## Audit outcomes

| Result | Meaning | Required action |
| --- | --- | --- |
| `PASS` | Every required fact is current, independently evidenced, and compatible with the applicable SOP and existing contract. | The owner may continue only within the already authorized boundary and next legal step. `PASS` itself grants no new authority. |
| `FAIL` | Evidence contradicts a requirement, a forbidden action occurred, or a required invariant is observably violated. | Stop and preserve. Master chooses the narrowest legal recovery, rework, supersession, cancellation, or release decision. |
| `NOT_PROVEN` | Evidence is missing, ambiguous, stale, partial, or unverifiable, including an unavailable dependency or authorization. | Treat as not accepted; stop the affected decision and request reconciliation. Do not downgrade it to `FAIL` or infer success. |

For a release candidate, `PASS` additionally requires current per-Gate evidence for the exact integrated
HEAD; infrastructure or provenance uncertainty is stale/`NOT_PROVEN` under the Release SOP, not a
successful failure result. For publication, a passed candidate still needs a fresh explicit publication
grant. For retention or deletion, an archive or closeout is evidence of retention only, never deletion
authority.

## Stop conditions

Use `STOP_AND_PRESERVE` through the [Exception and Recovery SOP](exception-recovery-sop.md) when any
of the following is observed:

- wrong HEAD, baseline, worktree, branch, role, generation, source, revision, digest, or Card state;
- unexpected dirty/untracked material, duplicate visible conversation, competing binding, dependency,
  ownership, or semantic scope overlap;
- missing, expired, ambiguous, or cross-capability authorization, unsupported model routing, or a
  request to infer authority from a title, message, test, candidate, closeout, or service tier;
- a required check, provenance item, archive byte, Gate, handoff mapping, version pin, or compatibility
  fact is absent or `NOT_PROVEN`;
- a proposed change would alter Schema, validator, state transitions, FAST/v2/release implementation,
  conversation lifecycle authority, or another forbidden path without a new Master assignment; or
- an operator proposes reset, rebase, merge, synchronization, push, publish, deletion, cleanup,
  unbounded retry, silent in-flight SOP change, or scope expansion without its separate authority.

The compact audit report is a human projection, not a fourth coordination record:

```text
SOP compliance audit
Operation and owner: <FAST | STRICT | RELEASE | RECOVERY | ADOPTION | SOP_CHANGE | RETENTION | ROTATION / OWNER>
Decision boundary: <WHAT_MUST_BE_PROVEN>
Identity and current HEAD: <TASK/PLAN/CARD/RELEASE / FULL_SHA>
Automated checks: <COMMAND / RESULT / EVIDENCE>
Manual checks: <OWNER/SCOPE/AUTHORITY/COMPATIBILITY / RESULT / EVIDENCE>
Required evidence: <COMPLETE / MISSING_OR_AMBIGUOUS_ITEMS>
Result: <PASS | FAIL | NOT_PROVEN>
Stop-and-preserve: <NONE | DETAILS>
Recovery owner and next legal decision: <MASTER_OR_EXISTING_OWNER / DECISION>
External, execution, publication, destructive actions used: <NONE_OR_EXACT_AUTHORIZED_ACTION>
```

An audit closes only when its result and all missing decisions are handed to the existing owner. It
does not archive conversations, clear Cards, change Dispatch, publish, delete, or authorize the next
operation.
