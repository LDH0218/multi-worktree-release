# v2 Policy Decisions: Approved Defaults

Status: approved design decisions for the future v2 protocol. The current v1 Skill, Schema, validator, CLI, and persisted
records remain authoritative. This document freezes policy meaning; it does not add executable behavior or change a v1
record.

Decision source: `01a04da3-c3d6-74a0-9019-f2ddabbff5e3` at Plan revision `28`.

The companion inputs are:

- `design/adaptive-operating-modes-v2.md` at revision `7a586b14df537f6d68e48c0ab16269f32dc346c4`;
- `design/state-authority-minimal-records-v2.md` at revision `d1437a3f4f86e4e6e8b1d26e26be2ea91a674ea7`.

The words **MUST**, **MUST NOT**, **ONLY**, and **MAY** below are normative for a future v2 adoption task. A later
implementation may choose the record encoding and storage location, but may not weaken these decisions.

## 1. Frozen policy decisions

### D1. The narrow FAST Git push path

FAST MAY include one Git push only when every condition below is true:

1. the repository has explicitly authorized this FAST path;
2. the action names exactly one repository, one ref, and one commit at action time;
3. the ref is an unprotected branch;
4. the push is non-force and fast-forward; and
5. no STRICT trigger applies to the outcome or the repository policy.

The push MUST persist one compact Operation Receipt. The receipt is the authority for the FAST push outcome after it is
materialized and MUST bind the repository, exact ref, exact commit, non-force mode, checks, authorization digest and actual
use, remote reference or observed outcome, and retry/uncertainty handling. A commit being present locally is not evidence
that it was pushed. A failed or uncertain push stops the path until the receipt is resolved under Section 3.

This is a narrow exception to the normal no-durable-record FAST path. It does not create a Dispatch Plan, Task Spec, Worker
Card, or Master Card. It does not authorize a push in this task; it defines the future v2 rule only.

### D2. Strict publication is fixed

The following outcomes MUST use STRICT and MUST NOT use the FAST push exception:

- a tag;
- a GitHub Release or equivalent release object;
- a deployment;
- production publication;
- a protected branch or protected ref;
- a force update;
- a multi-ref push; or
- any publication that repository policy marks strict.

STRICT binds the release candidate, Gate Registry, per-Gate evidence, bounded action authorization, and Publication Record to
the exact integrated head and externally visible outcome. A passed candidate is not publication authority. A delivery record
or a FAST receipt cannot be promoted into a production Publication Record.

### D3. Minimum mode for contract and recovery risk

The following changes are at least ISOLATED:

- collaboration contracts, including Plan, Task Spec, Worker Card, Master Card, or handoff semantics;
- Schema, validator-facing contract shape, or state transitions;
- authorization semantics or their enforcement, including execution, publication, or destructive-action checks;
- recovery rules or migration rules;
- candidate evidence or Gate semantics; and
- release certification.

ISOLATED becomes STRICT immediately when a strict consequence trigger also applies, such as production publication,
destructive or irreversible action, material remote mutation, compliance evidence, ambiguous/tampered state, or an explicit
STRICT request. A small diff does not remove a mode trigger.

### D4. FAST durability triggers

A one-generation, bounded local FAST operation with no collaboration, recovery need, or external mutation creates no Plan or Card
and normally no Operation Receipt. FAST MUST materialize one compact Operation Receipt when it:

- crosses a conversation generation;
- performs any authorized external mutation; or
- requires recovery because conversation history is no longer a sufficient source.

Repository policy MAY require the same receipt earlier. Before a trigger, the current request is the ephemeral authority for
the FAST objective and mode decision, and Git is authoritative for the observed checkout. After the first trigger, the
Operation Receipt is the normative durable owner; a missing record is never treated as an owner. The receipt replaces,
rather than abbreviates, the four-record collaboration protocol for that FAST operation.

### D5. Finding severity and scope

P0 and P1 findings block only the affected current outcome—such as the task, Gate, candidate, or publication decision—until
the finding is resolved or the affected outcome is explicitly cancelled. They do not silently block unrelated valid work.

P2 and P3 findings are recorded as outside-the-active-scope follow-up items. They MUST NOT expand the current task, Plan,
release, or Gate set without explicit user approval. A later task may address them with its own identity, scope, and gates.

### D6. The v1/v2 boundary

Every persisted v1 record is permanent read-only history. A v2 reader MAY validate, reference, and preserve a v1 record, but
MUST NOT rewrite it, bulk-migrate it, split its authorization, invent missing evidence, or replace its historical bytes with a
current file at the same path.

v2 begins only at a newly protocol-fenced cycle. The fence identifies the protocol version, Schema identity, and validator
identity used by that cycle. Existing v1 history remains available for compatibility and audit but does not become v2 state by
being reread. A migration design may define read-only adapters and forward references; it may not rewrite or batch-convert the
v1 history.

## 2. Deterministic mode selection and transitions

Choose the highest mode required by the facts before starting the action. FAST is the default only while all FAST conditions
hold; D1 is the sole external Git exception. The minimum records are:

| Situation | Mode | Minimum durable source |
| --- | --- | --- |
| One-generation local work, one bounded diff, no collaboration, recovery, or external mutation | FAST | Current request plus Git; no Plan/Card and normally no receipt |
| D1-approved non-force single-ref push to an unprotected branch | FAST | Current request plus Git, then one compact Operation Receipt |
| Persistent Worker, concurrent ownership, dependency/integration order, contract risk, or interruption recovery | ISOLATED | Delivery Plan, immutable Task Spec, Worker Card while locked, and Master Delivery Record |
| Production/release/tag/deployment/protected/force/multi-ref/policy-strict publication or another strict trigger | STRICT | Release Plan, Gate Registry and evidence, action authorization, and Publication Record if attempted |

An upgrade is mandatory as soon as its trigger is discovered:

1. stop before the action that crosses the boundary;
2. preserve the current Git tree, external state, checks, and material;
3. create only the records required by the destination mode; and
4. continue only after the new mode's identity, scope, baseline, and authorization preflight passes.

FAST to ISOLATED creates the Delivery Plan/Task Spec/Worker records from the observed checkpoint. FAST or ISOLATED to STRICT
freezes the release inputs and creates release-specific evidence and exact action authorization before the strict action.
An upgrade is prospective: it does not invent cards, executions, or evidence for earlier valid lighter-mode work.

Downgrade is recovery and cost control, never a way to bypass a finding or failed Gate:

- STRICT to ISOLATED is allowed only when no strict external or destructive action has started, strict authority is revoked or
  expired, the candidate is explicitly abandoned, and the remaining outcome is delivery-only. Existing strict evidence stays
  historical.
- ISOLATED to FAST is allowed only after every Worker is integrated, cancelled, or IDLE; no concurrent work, dependency,
  dirty alternate worktree, or unresolved handoff remains; and the remaining operation independently meets every FAST
  condition. The downgrade starts a new FAST checkpoint and does not erase isolated history.
- No downgrade is allowed after production/publication, destructive, or paid remote mutation begins; while a release or
  Worker lock remains active; while a P0/P1 is unresolved; to avoid rerunning a failed Gate; or when repository policy fixes a
  higher minimum mode.

If a downgrade condition cannot be proved, remain in the current mode or cancel the outcome safely.

## 3. FAST Operation Receipt and uncertain push outcomes

The receipt is one logical append-only record with revisions, not a second authorization path. Its minimum policy shape is:

```json
{
  "record_kind": "fast-operation-receipt",
  "mode": "FAST",
  "objective": "bounded objective",
  "repository": "repository identity",
  "ref": "refs/heads/topic",
  "commit_sha": "full commit SHA",
  "force": false,
  "checks": [{"id": "required-check", "result": "PASS"}],
  "authorization": {"envelope_digest": "sha256:...", "used": true},
  "remote": {"outcome": "SUCCEEDED", "ref": "remote ref or null"},
  "retry": {"attempt": 1, "uncertainty_resolved": true},
  "outcome": "COMPLETED"
}
```

The JSON is illustrative, not a v2 Schema. A receipt for local FAST work may set the external-action fields to null or omit
the push-specific projection according to the future encoding, but a D1 push MUST retain the exact repository, ref, commit,
authorization use, and remote outcome.

An error, timeout, disconnect, or contradictory response that does not prove whether the remote changed is `UNCERTAIN`. The
deterministic resolution is:

1. stop issuing writes and append a receipt revision with `outcome: UNCERTAIN`; preserve the exact original repository, ref,
   commit, non-force flag, checks, authorization, and local state;
2. inspect the exact remote ref before any retry; do not infer the result from a local commit or message;
3. if the remote ref already equals the exact commit, finalize the same receipt as `ALREADY_PRESENT`/`COMPLETED` and do not
   retry;
4. if the remote ref is unchanged at the verified pre-push state, the original authorization is still current and unexpired,
   and D1 still holds, allow at most one retry with the same exact repository, ref, commit, non-force mode, and authorization;
5. if the remote ref differs, cannot be verified, the authorization expired, or any STRICT trigger appeared, do not retry;
   block the outcome and require Master recovery or a newly scoped authorization/mode decision; and
6. after the one permitted retry, any new uncertainty is blocked rather than retried again. Record the final remote ref or
   the verified absence and the exact outcome in the existing receipt chain.

No retry may change the ref, commit, force flag, target repository, number of refs, or authorization envelope. No second
receipt may hide a first uncertain attempt. A deterministic remote rejection may be recorded as rejected without claiming a
push; retrying it requires a new decision rather than an implicit loop.

## 4. Conversation-loss and recovery rules

Conversation text is a transport projection, not recovery authority.

| Lost state | Recovery source and action | Forbidden shortcut |
| --- | --- | --- |
| Local FAST ends without a receipt | Inspect Git HEAD, status, diff, and preserved material. Treat unrecorded work as unfinished and start a new checkpoint if needed. | Do not reconstruct a success receipt from the last message. |
| FAST receipt exists but Git differs | Compare baseline, changed paths, result SHA, and receipt digest to Git. Mark it unverified and block or create a fresh scoped operation. | Do not amend the receipt or discard the difference automatically. |
| FAST push is uncertain | Preserve the receipt and local state; inspect the exact remote ref before applying Section 3. | Do not blindly retry, switch refs, force push, or infer remote success. |
| ISOLATED delivery loses its conversation | Recover from Plan, Task Spec, Worker/Master Cards, Delivery Record, Git, and preserved material. Master assigns recovery or takeover if needed. | Elapsed time does not authorize takeover, cleanup, or a new commit. |
| STRICT release loses its conversation | Recover release identity, Gate evidence, action authorization, Publication Record, delivery records, and exact integrated head. | Do not infer candidate, authorization, or publication success from a delivery message. |

Any mismatch in identity, revision, path, digest, baseline, or authorization stops recovery. A dirty or untracked worktree is
preserved as user material. Only Master may invalidate a historical task, assign a takeover, or publish a superseding task.

## 5. Four result boundaries

These results are intentionally separate and cannot be inferred from one another:

| Result | Required proof | Does not prove |
| --- | --- | --- |
| `DELIVERY COMPLETE` | Master accepts the handoff, records `worker_commit_sha -> integrated_as_sha`, and runs proportionate delivery checks on the integrated tree. | Candidate validity, Git push, publication authorization, or production visibility. |
| `CANDIDATE PASSED` | The exact immutable `release_task_id + release_head_sha` has complete current required Gate evidence and all required Gates pass. | Any remote mutation or production publication. |
| `GIT PUSHED` | The exact remote ref is verified at the exact commit. A D1 push uses its compact FAST receipt; a STRICT push also uses the applicable action/publication records. | A release, tag, deployment, protected-branch approval, or production publication unless those separate STRICT records prove it. |
| `PRODUCTION PUBLISHED` | STRICT action-time authorization plus a Publication Record bound to the exact release artifact/ref and observed external outcome. | Retroactive validity of an earlier candidate or delivery record. |

Integration never implies a push. A passed candidate never implies a push or publication. A verified Git push never implies a
production release. Any integrated-tree change creates a new candidate identity and invalidates old release evidence.

## 6. Remaining implementation parameters and next artifact

The following are intentionally open implementation parameters only; choosing them MUST NOT change D1–D6:

- the canonical serialization, field names, append-only storage, and retention period for Operation Receipts;
- the repository-policy location and approval workflow that declares the D1 FAST push path;
- the remote-ref observation adapter, timeout classification, and receipt-revision writer;
- the exact mapping from a finding to an affected task, Gate, candidate, or publication result;
- protocol version numbering, fence syntax, and the v1 read-only adapter interface; and
- the report and UI projection for the four result boundaries.

The next artifact is the **v1/v2 migration and protocol-freeze design**. It will define the fence, read-only compatibility,
forward references, and adoption checkpoints. It MUST precede any Schema or validator implementation work. This document does
not select a publication provider, create authorization, change the current CLI, or authorize external actions.

## 7. Non-goals

- rewriting or bulk-migrating v1 history;
- adding v2 fields to the current Schema or validator;
- changing the current Skill or CLI in this decision task;
- turning P2/P3 follow-up into implicit scope;
- treating a receipt, delivery handoff, branch name, or model profile as publication authority; or
- performing a push, release, deployment, execution, synchronization, or other external action.
