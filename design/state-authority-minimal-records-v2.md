# v2 State Authority and Minimal Durable Records

Status: design-only proposal for the future protocol v2. This document does not change the current Skill, JSON Schema,
validator, CLI, or any persisted v1 record.

This design is based on `design/adaptive-operating-modes-v2.md` at revision
`7a586b14df537f6d68e48c0ab16269f32dc346c4`. The current v1 contracts remain authoritative until a separately approved
adoption task establishes the v2 fence.

## 1. Decision and invariants

v2 has one rule for durable state: every mutable fact has exactly one normative owner. Other records may carry a stable
reference, revision, or digest to that owner, but may not become a second source of truth by copying the payload.

The authority reference for a fact is the tuple:

```text
(owner record kind, stable identity, record revision, value digest)
```

An omitted reference means that the record does not claim the fact. A mismatch between two records is actionable only when
the relationship requires them to describe the same current fact; otherwise the records describe different concerns and are
validated independently.

The design makes four boundaries explicit:

1. A Task Spec is the authority for immutable assignment content; a Delivery Plan is the authority for live scheduling.
2. A Worker Card is a short-lived lock/progress record, not a copy of the assignment or a release approval.
3. A Delivery Record owns handoff acceptance and `worker_commit_sha -> integrated_as_sha` mapping.
4. A Release Record owns candidate evidence; a Publication Record owns the externally visible action and its outcome.

Git remains authoritative for repository bytes, commits, trees, ancestry, reachability, and dirty/untracked state. Conversation
messages are transport projections only. No message, card, digest, or model label grants external authority.

The mode is an execution policy, not a quality grade. `FAST` is the default; `ISOLATED` is required for collaboration or
recovery risk; `STRICT` is required for consequence, authorization, production publication, policy-strict publication,
destructive, migration, audit, or explicit release risk. A mode upgrade stops the crossing activity and preserves the
checkpoint before creating the additional records.

## 2. Field-level authority matrix

The matrix splits fields that look similar but represent different facts. This avoids giving both a static declaration and a
live projection the same owner. `Reference` means an immutable pointer/digest is allowed; `Projection` means a derived view
may be regenerated; `Cache` means it is disposable and never evidence; `Forbidden` means the full value must not be copied.

| Mutable fact or current field family | v2 normative owner | Allowed appearances elsewhere | Required boundary |
| --- | --- | --- | --- |
| Mode choice and trigger that caused `FAST`, `ISOLATED`, or `STRICT` | Current request (ephemeral for FAST before a durability trigger); Operation Receipt after a FAST trigger; Delivery/Release Plan decision for `ISOLATED`/`STRICT` | Plan or release record reference | No absent Mode Decision Record owns pre-trigger FAST state. The trigger is recorded once; a title, model, worktree number, or confidence claim cannot select the mode. |
| User request, bounded objective, and requested outcome | Request / Mode Decision Record | Task Spec references the request digest | A changed objective creates a new assignment; it is not a status update. |
| Message identity (`task_id`, task revision, task-spec digest, source thread) | Task Spec publication record | Plan, Worker Card, handoff, and message reference | Equal identity requires equal digest; `plan_revision` is a fence, not identity. |
| Immutable assignment objective and current-state facts | Task Spec | Plan/Worker references by task identity and digest | Plan and cards must not restate an editable assignment payload. |
| Task Spec revision and `task_spec_digest` | Task Spec | Plan and cards as references | A changed executable payload gets a higher task revision and new digest. |
| Task Spec path and original `task_spec_plan_revision` | Task Spec publication history | Plan and cards as references | A grandfathered assignment keeps its original plan fence; a mutable path cannot rewrite history. |
| Owner role and responsibility boundary | Task Spec | Plan, Worker Card, handoff as references | A changed owner is a supersession, not an in-place revision. |
| Worktree and branch binding | Task Spec assignment | Plan and Worker Card as references; Git reports observed values | A changed worktree or branch requires a new assignment. |
| Frozen baseline and expected starting commit | Task Spec assignment | Plan and Worker Card as references; Git verifies the observed HEAD | Workers never synchronize to repair a baseline mismatch. |
| Allowed and forbidden paths | Task Spec | Plan and Worker Card as exact references | Path aliases, implicit directories, and scope expansion are invalid. |
| Declared inputs, outputs, and Master-derived outputs | Task Spec | Plan and cards reference digests; Master regenerates derived outputs | The input set is immutable for the assignment; derived values are never Worker authority. |
| Acceptance commands and success predicates for delivery | Task Spec | Worker Card may reference the acceptance digest; Delivery Record records checks run | A Worker report cannot silently change what acceptance means. |
| Model profile and selection reason | Task Spec assignment | Plan and Worker dispatch projection | Routing metadata is not authorization, capability, or evidence of an effective tier. |
| Static dependency declaration (`dependencies.blocked_by`) | Task Spec | Plan references the static graph | A changed dependency is executable content and requires a revised/superseding assignment. |
| Live unresolved blockers (`blocked_by`) | Delivery Plan | Worker/Master records reference the plan entry | This is a derived current projection of static dependencies and statuses; it is never copied into a Task Spec. |
| Dispatch status (`READY` through terminal states) | Delivery Plan | Message and card show a projection | Only Master changes it; terminal entries are append-only. |
| Dispatch wave and parallel claims | Delivery Plan (validated from Task Specs) | Task Spec and message references | The plan stores the validated scheduling projection; waves are not inferred from task order or worktree numbers. |
| Plan semantic revision (`plan_revision`) | Delivery Plan | Task Specs/cards/handoffs as a fence reference | Semantic changes advance it; status-only writes do not. |
| Plan persistence revision, timestamp, and digest | Delivery Plan | Master release lock stores the digest; messages may quote it | `record_revision` advances on every write and `plan_digest` is recomputed from the complete plan. |
| Worker lock state (`IDLE`, `ACTIVE`, `AWAITING_INTEGRATION`, `BLOCKED`) | Worker Card | Delivery Plan and messages reference it | A non-IDLE card locks only its own worktree; IDLE means active fields are cleared. |
| Worker Card assignment lock fields | Worker Card as a lock projection | Exact references to Task Spec/Plan | The card cannot edit assignment content; an identity mismatch blocks work. |
| Worker progress, blocker, recovery owner, and preserved-material note | Worker Card while the lock is held | Handoff/exception report references the card revision | A blocker is evidence for recovery, not a fake dependency edge. |
| Worker Card persistence revision and timestamp | Worker Card | Handoff may cite the snapshot digest | Each card write advances its own record fence. |
| Observed HEAD, changed paths, dirty state, untracked state, and file bytes | Git | Cards and reports record observed snapshots/digests | Git evidence is not inferred from a card; preserved user material is never cleaned automatically. |
| Worker commit and commit contents | Git commit object | Worker Card/handoff reference `worker_commit_sha` | A handed-off commit is immutable; rework creates a successor commit. |
| Handoff acceptance, rejection, and rework state | Delivery Record owned by Master | Master Card may project handoff state | `RECEIVED`, `INTEGRATED`, and `REWORK_REQUESTED` are history; a card cannot self-accept. |
| `worker_commit_sha -> integrated_as_sha` mapping | Delivery Record owned by Master | Worker Card `last_task` and reports reference it after acceptance | Integration complete is distinct from release approval. |
| Master delivery lock and current delivery Plan reference | Master Delivery Card | Plan and messages reference its digest | It identifies the delivery workflow; it cannot authorize publication. |
| Master Card persistence revision, timestamp, and delivery blocker | Master Delivery Card | Reports reference the snapshot | A Master Card transition cannot rewrite Worker handoff history. |
| Release task identity and selected integrated `release_head_sha` | Release Plan | Release evidence and publication receipt reference it | Candidate identity is exactly `(release_task_id, release_head_sha)`. |
| Gate registry, requiredness, definitions, check revisions, and runner policy | Versioned Gate Registry | Release Plan and Gate Evidence reference its digest and stable IDs | Requiredness is not inferred from evidence rows; registry changes fence affected evidence. |
| Per-Gate input sources, check results, provenance, and evidence digests | Release Evidence Record | Master Card may reference the evidence digest | Every current Gate independently binds its source, input, result, provenance, and exact head. |
| Candidate aggregate status and compatibility digest | Release Evidence Record | Master/release UI projection | `STALE` precedes `FAILED`; `PASSED` requires all current required Gates. |
| Release plan audit context (`plan_revision`, `plan_digest`) | Release Plan | Release Evidence and candidate reports reference it | These values are audit context, not extra candidate-key members and not blanket invalidators. |
| Publication intent and bounded action-time authorization | Publication Request / Authorization Envelope | Release Plan stores a digest and scope reference | Publication authority is separate from delivery and candidate evidence; default deny remains explicit. |
| Actual external action, remote reference, and publication outcome | Publication Record | Release report references the receipt | Only the authorized release role writes the outcome; a message cannot claim publication. |
| Runtime execution/job identity, resume decision, and result | Execution Receipt owned by the execution authority | Task/release records reference a non-secret receipt | A model profile is not a run grant; no run is created by this design. |
| Authorization envelope payload and digest | Action Authorization Envelope (embedded in the Task Spec for delivery actions) | Other records carry digest-only references | Four v2 grants remain independent; no target, route, budget, or expiry is borrowed. |
| Authorization use count and cost | Capability-specific Action Receipt | Cards report only used/not used | A zero-use default-deny envelope is not evidence that a capability was available. |
| Issuer, source thread, issue time, and conversation generation | Publication record for the decision being issued | Task Spec, Plan, and messages reference it | A rotated conversation may publish a new record, but it cannot rewrite the old source. |
| `supersedes_task_id` lineage | Assignment Lineage in the Delivery Plan | The successor Task Spec, handoffs, and reports carry an immutable edge reference | A successor has its own authority; lineage never transfers authorization. |
| Recovery decision, preserved material, and resulting lock state | Recovery Record owned by Master | Worker Card and reports reference the decision | Elapsed time, missing conversation, or a digest alone cannot authorize takeover. |
| Historical snapshot bytes and canonical snapshot digest | Append-only history for the record's normative owner | Every consumer may retain a digest/reference | Historical v1 and v2 snapshots are evidence; they are never edited to match a newer projection. |
| Conversation text, delivery acknowledgements, and UI title | No normative owner; transport/projection only | Any record may cite a message locator | Conversation loss must be recoverable from persisted records and Git, not from message replay. |

For FAST, the current request is intentionally the sole ephemeral authority for the mode decision and bounded objective
before a durability trigger; no durable Mode Decision Record exists in that phase, and no missing record may be treated as
the owner. Git remains authoritative for the observed checkout and repository state. On the first durability trigger, one
Operation Receipt is materialized and becomes the normative durable owner for that FAST operation. For ISOLATED and STRICT,
the persisted Delivery Plan or Release Plan owns the mode decision. An owner name such as `Request / Mode Decision Record`
or `Action Authorization Record` denotes one logical record class, not two competing authorities. A concrete deployment may
store several record classes in one append-only file, but each fact still has one owner field and one revision/digest chain.
The current v1 Master Card is a composite projection; v2 must apply the rows above even if a transitional file still renders
delivery and release references together.

Two apparent duplications are intentional references rather than competing owners:

- A Plan entry's `task_spec_digest`, a Worker Card's assignment digest, and a handoff's task identity all point to the Task
  Spec. They do not own the assignment payload.
- A release record may cite the delivery mapping and the Plan digest, but it never promotes that delivery evidence into
  candidate or publication authority.

## 3. Minimum durable records by mode

### 3.1 FAST

FAST creates no Dispatch Plan, Task Spec, Worker Card, or Master Card by default. Before a durability trigger, the current
request is the sole ephemeral authority for the FAST mode decision and bounded objective; the current Git checkout is the
authority for observed repository state, and one atomic diff is sufficient when all FAST conditions hold. No durable Mode
Decision Record exists in this phase, so a missing record cannot be claimed as an owner. The request and checks can remain
in the current conversation for a one-generation, non-external operation.

Create exactly one compact Operation Receipt when any of these applies:

- the work crosses a conversation generation;
- an authorized external mutation occurs;
- recovery would otherwise depend on conversation history; or
- repository policy explicitly requires a receipt.

At the first trigger, materialize exactly one compact Operation Receipt. From that point it is the normative durable owner
of the FAST operation outcome and contains the objective, mode decision, baseline, changed paths, checks, authorization
digest and actual-use summary, result SHA or external reference, preserved material, and outcome. It replaces, rather than
abbreviates, the four-record collaboration protocol. It must not be used to hide a trigger that requires an ISOLATED or
STRICT upgrade.

No FAST Plan or Card is created for a bounded local documentation or implementation change that finishes in the current
conversation and needs no collaboration, recovery, or external mutation. The narrow FAST publication path is limited to an
explicitly repository-authorized, non-force, single-ref Git push that does not trigger STRICT; because it is an authorized
external mutation, it must materialize the compact receipt with the exact repository, ref, commit, authorization use, checks,
and outcome. It never covers a production release, tag, deployment, protected publication, or policy-strict publication. A
later upgrade starts from the observed checkpoint; it does not invent a historical Worker or release record for the earlier
FAST work.

### 3.2 ISOLATED

ISOLATED is the minimum mode for a separate Worker, persistent task, concurrent ownership, dependency/integration ordering,
contract or state-machine change, or interruption recovery. Its minimum durable set is:

1. one Delivery Plan for the live assignment graph and Dispatch states;
2. one immutable Task Spec for each delegated assignment;
3. one Worker Card only while a separately owned Worker lock or blocker exists; and
4. one Master-owned Delivery Record for each handoff and integration mapping.

The Worker Card is not necessary for a Master-only change with no Worker lock. Once a Worker is active, omitting the card is
not a cost optimization; it removes the recovery source and is invalid. After accepted integration, the card may return to
IDLE with a compact `last_task` reference while the Plan and Delivery Record retain the authoritative history.

ISOLATED does not create candidate evidence or a publication receipt by default. A successful handoff means that the intended
delivery is integrated and tested proportionately; it does not mean that the integrated tree is releasable.

### 3.3 STRICT

STRICT is required for production release, tag, deployment, protected publication, publication that repository policy marks
strict, destructive or irreversible action, authorization semantics, ambiguous/possibly tampered state, data migration,
external mutation with material consequence, multiple release systems, compliance/audit evidence, or an explicit strict
request. It reuses valid delivery records and adds:

1. a Release Plan selecting one immutable `(release_task_id, release_head_sha)` candidate;
2. a versioned Gate Registry and self-contained per-Gate Release Evidence record;
3. a bounded authorization/action record for any external, destructive, execution, or publication capability; and
4. a Publication Record only if a publication action is actually authorized and attempted.

A STRICT audit that does not publish has no Publication Record. A STRICT release with no delegated Worker has no Worker Card;
it still has a Release Plan and release evidence, and it need not manufacture a Delivery Plan for work that was not delegated.
A release cannot infer authorization, provenance, or publication success from an ISOLATED Delivery Record.

The adaptive-modes exception is deliberately narrow: an explicitly repository-authorized non-force single-ref Git push may
remain FAST only when the push itself does not meet any STRICT condition. It still requires exact action-time authorization
and the compact FAST Operation Receipt. Production releases, tags, deployments, protected refs, and any publication that
repository policy marks strict remain STRICT.

| Record | FAST | ISOLATED | STRICT |
| --- | --- | --- | --- |
| Request / Mode Decision | Current context; receipt only when required | Persisted decision in Delivery Plan | Persisted decision in Release Plan and delivery reference |
| Delivery Plan | None by default | Required for collaboration or recovery | Reused when delivery exists; release selection is separate |
| Task Spec | None by default | One per Worker assignment | Same, or none when no Worker is involved |
| Worker Card | None | Only for an active Worker lock/blocker | Same rule; never a release authority |
| Delivery Record | Git/receipt only | Required for handoff and integration mapping | Reused as input, never promoted |
| Release Plan/Gate Registry | None | None by default | Required for candidate certification |
| Release Evidence | None | None by default | Required for current candidate Gates |
| Publication Record | Not created; the explicitly authorized non-force single-ref Git push uses a required compact Operation Receipt | Not created by integration | Required only for an attempted STRICT publication |
| Recovery source | Git, request, optional receipt | Plan + Task Specs + cards + Git + Delivery Record | All delivery records plus Release/Publication/Action records |

## 4. Delivery and release lifecycle boundary

The two workflows share references, not authority:

```text
request/mode decision
  -> Task Spec + Delivery Plan
  -> Worker lock and owned checks
  -> handoff RECEIVED
  -> worker_commit_sha -> integrated_as_sha
  -> DELIVERY COMPLETE

immutable integrated head
  -> Release Plan selects release_task_id + release_head_sha
  -> Gate Registry and independent per-Gate evidence
  -> all current required Gates pass
  -> CANDIDATE PASSED
  -> action-time publication authorization
  -> Publication Receipt
  -> PRODUCTION PUBLISHED
```

The three completion states have different owners and evidence:

| State | Minimum proof | Owner | What it does not prove |
| --- | --- | --- | --- |
| Delivery complete | Accepted handoff and `worker_commit_sha -> integrated_as_sha` | Delivery Record / Master | It does not prove any release Gate or publication permission. |
| Candidate passed | Current required Gates pass on the exact `release_head_sha`, with complete per-Gate evidence | Release Evidence Record / Master | It does not start or complete publication. |
| Production published | Action-time authorization plus a Publication Record bound to the exact artifact/ref and observed outcome | Authorized release role | It does not retroactively make an earlier candidate or delivery record current. |

Any integrated-tree change creates a new candidate identity and stales all old candidate evidence. Same-tree or patch-equivalent
content does not permit evidence reuse when the release head changes. On the same head, a complete source map may selectively
invalidate only affected Gates; missing membership, ambiguous mapping, or unverifiable provenance uses whole-candidate
`STALE`. Status-only Plan bookkeeping is not itself a Gate input unless a Gate explicitly consumes it.

Publication is never an implicit final step of integration. A candidate may remain `PASSED` without a publication attempt, and
a publication receipt may not be synthesized from a `PASSED` status.

In this lifecycle, `PRODUCTION PUBLISHED` is the STRICT production-release boundary. A policy-approved FAST Git push is a
narrow, separately receipted Git publication outcome and must not be labeled as a production release or used to bypass the
STRICT boundary.

## 5. Minimal JSON-shaped records

The following examples illustrate the v2 ownership shape. They are not additions to the current v1 Schema and are not
executable records until a later adoption task defines their exact contract. Every digest below is illustrative but has the
required `sha256:` form.

### 5.1 FAST Operation Receipt

```json
{
  "record_kind": "fast-operation-receipt",
  "schema_version": 2,
  "record_revision": 1,
  "updated_at": "2026-08-30T10:00:00Z",
  "mode": "FAST",
  "objective": "Update one bounded local document",
  "baseline_sha": "39e8970daf7038881e6fac4f66950083d1a3c435",
  "changed_paths": ["docs/example.md"],
  "checks": [{"id": "diff-check", "result": "PASS"}],
  "authorization": {"envelope_digest": "sha256:1111111111111111111111111111111111111111111111111111111111111111", "used": false},
  "result_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "preserved_material": [],
  "outcome": "COMPLETED"
}
```

No Plan or Card is needed for this example because it completes in one generation, has no Worker, and performs no external
mutation. If the conversation disappears before completion, the receipt is either absent (the operation is not claimed as
complete) or is checked against Git; it is never reconstructed as a success from a message.

### 5.2 ISOLATED delivery bundle

The immutable Task Spec owns the assignment. The Delivery Plan owns only the live scheduling projection:

```json
{
  "record_kind": "task-spec",
  "schema_version": 2,
  "task_id": "docs-state-authority",
  "task_spec_revision": 1,
  "task_spec_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  "task_spec_plan_revision": 2,
  "owner_role": "state-authority-design",
  "worktree": "/worktrees/docs-state-authority",
  "branch": "codex/state-authority",
  "frozen_baseline_sha": "39e8970daf7038881e6fac4f66950083d1a3c435",
  "allowed_paths": ["design/state-authority-minimal-records-v2.md"],
  "acceptance_digest": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
  "authorization_envelope_digest": "sha256:4444444444444444444444444444444444444444444444444444444444444444"
}
```

```json
{
  "record_kind": "delivery-plan",
  "schema_version": 2,
  "record_revision": 3,
  "plan_revision": 2,
  "plan_digest": "sha256:5555555555555555555555555555555555555555555555555555555555555555",
  "tasks": [{
    "task_id": "docs-state-authority",
    "task_spec_revision": 1,
    "task_spec_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "dispatch_status": "PUBLISHED",
    "dispatch_wave": 1,
    "blocked_by": []
  }]
}
```

```json
{
  "record_kind": "worker-card",
  "schema_version": 2,
  "record_revision": 4,
  "state": "ACTIVE",
  "task_ref": {"task_id": "docs-state-authority", "task_spec_revision": 1, "task_spec_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222"},
  "plan_revision": 2,
  "worktree": "/worktrees/docs-state-authority",
  "baseline_sha": "39e8970daf7038881e6fac4f66950083d1a3c435",
  "authorization_envelope_digest": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
  "blocker": null,
  "worker_commit_sha": null
}
```

After the Worker commits, the Worker Card moves to `AWAITING_INTEGRATION`; the Delivery Record then owns acceptance and the
mapping:

```json
{
  "record_kind": "delivery-record",
  "schema_version": 2,
  "record_revision": 5,
  "handoff": {
    "task_id": "docs-state-authority",
    "task_spec_revision": 1,
    "task_spec_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "worker_commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "integrated_as_sha": "cccccccccccccccccccccccccccccccccccccccc",
    "state": "INTEGRATED"
  },
  "accepted_checks_digest": "sha256:6666666666666666666666666666666666666666666666666666666666666666"
}
```

### 5.3 STRICT release and publication records

The Release Plan selects a candidate without changing the delivery records:

```json
{
  "record_kind": "release-plan",
  "schema_version": 2,
  "record_revision": 1,
  "release_task_id": "release-2026-08-30",
  "release_head_sha": "cccccccccccccccccccccccccccccccccccccccc",
  "delivery_ref": {"task_id": "docs-state-authority", "integrated_as_sha": "cccccccccccccccccccccccccccccccccccccccc"},
  "gate_registry_digest": "sha256:7777777777777777777777777777777777777777777777777777777777777777",
  "publication_authorization_digest": null
}
```

```json
{
  "record_kind": "release-evidence",
  "schema_version": 2,
  "record_revision": 2,
  "release_task_id": "release-2026-08-30",
  "release_head_sha": "cccccccccccccccccccccccccccccccccccccccc",
  "gate_registry_digest": "sha256:7777777777777777777777777777777777777777777777777777777777777777",
  "gates": [
    {"gate_id": "targeted-tests", "gate_revision": 1, "required": true, "status": "PASSED", "input_digest": "sha256:8888888888888888888888888888888888888888888888888888888888888888", "evidence_digest": "sha256:9999999999999999999999999999999999999999999999999999999999999999"},
    {"gate_id": "optional-audit", "gate_revision": 1, "required": false, "status": "PASSED", "input_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "evidence_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
  ],
  "status": "PASSED"
}
```

```json
{
  "record_kind": "publication-record",
  "schema_version": 2,
  "record_revision": 1,
  "release_task_id": "release-2026-08-30",
  "release_head_sha": "cccccccccccccccccccccccccccccccccccccccc",
  "authorization_envelope_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "target": {"kind": "publication", "id": "protected-main", "transport": "remote", "scope": {"paths": ["refs/heads/main"], "refs": ["refs/heads/main"]}},
  "action": "NOT_STARTED",
  "external_reference": null,
  "outcome": null
}
```

The publication example remains a non-event until a separately authorized release role changes it. A `PASSED` release record
does not fill `external_reference` or `outcome`.

## 6. v1 read-only boundary, migration fence, and safe downgrade

### 6.1 v1 is immutable history

v1 records are read-only evidence. A v2 reader may validate a v1 Plan, Task Spec, Worker Card, Master Card, or candidate
record using the v1 contract and preserve its exact bytes and canonical digest. It must not rewrite v1 fields to make them
look like v2, infer missing Gate identity, split one flat authorization into multiple grants, or replace an unavailable
historical Task Spec with the current file at the same path.

The v1-to-v2 adapter is deliberately narrow:

- it first validates the complete v1 source and retains its original digest;
- only a canonical all-denied v1 authorization may be mechanically represented as canonical all-denied v2;
- allowed, ambiguous, expired-for-execution, or noncanonical v1 authority requires a new superseding Task Spec or explicit
  action record; the old v1 envelope is not reinterpreted;
- aggregate-only v1 candidate evidence remains a preserved legacy audit waypoint and cannot become current per-Gate evidence;
- a new v2 record references the v1 record and migration decision but does not mutate or delete the v1 record.

### 6.2 Protocol and migration fence

Before the first executable v2 assignment, Master persists one protocol fence containing:

```text
protocol_major + protocol_minor + schema identity + validator commit
```

The fence is an interpretation boundary, not a global rewrite marker. All records created at or after the fence use the v2
authority model. Older digest-preserved v1 records remain below the fence and are validated only under their original rules.

A migration is safe only when it proves all of the following:

1. the old record is complete, byte-preserved, and digest-verified;
2. the v2 record has a new identity or an explicit immutable source reference, never an in-place v1 rewrite;
3. all assignment, owner, baseline, authorization, and release identities are unchanged unless Master publishes a valid
   superseding task;
4. every current release Gate has fresh source/input/result/provenance evidence when legacy evidence is being retired; and
5. the migration cannot claim a result, permission, or publication that the old record did not prove.

If any condition is unknown, keep the v1 record as history and block the affected current action. A v1 record can be read
after the fence, but it cannot silently become the current v2 authority.

### 6.3 Downgrade is a new checkpoint, not erasure

Downgrading the operating mode is a recovery/cost decision and never a way around a failed Gate. Existing v2 and v1 evidence
remains retained under its original mode and fence.

`STRICT -> ISOLATED` is permitted only when no strict external, destructive, paid, or publication action has started; strict
authority is revoked or expired; the candidate is explicitly abandoned; no P0/P1 issue remains hidden; and the remaining
outcome is delivery-only. Candidate evidence stays historical and is not relabelled as an ISOLATED success.

`ISOLATED -> FAST` is permitted only after every Worker is integrated, cancelled, or IDLE; no concurrent work, dependency,
dirty alternate worktree, or unresolved handoff remains; and the remaining operation independently meets every FAST
condition. The new FAST checkpoint does not delete the Plan, Task Specs, cards, or Delivery Records.

No downgrade is permitted after a publication, destructive, irreversible, or paid remote mutation starts; while a release or
Worker lock remains active; while a P0/P1 finding is unresolved; after a failed Gate when the purpose is to avoid rerunning or
fixing it; or when repository policy sets a higher minimum mode.

## 7. Conversation-loss and partial-state recovery

Recovery starts with read-only inspection of the durable source, not with a replay of messages. The recovery owner records the
old and new revisions, preserved material, evidence, and resulting lock state before taking any action.

| Scenario | Recovery source and expected proof | Safe action | Forbidden shortcut |
| --- | --- | --- | --- |
| FAST conversation disappears before completion | Git HEAD/status/diff and any Operation Receipt | Treat unrecorded work as unfinished; preserve the checkout and begin a new checkpoint if needed | Do not infer completion from the last message or create a fake receipt. |
| FAST receipt exists but Git differs | Receipt digest, baseline, changed paths, result SHA, and Git inspection | Mark the receipt unverified and block or create a fresh scoped operation | Do not amend the receipt or discard the difference automatically. |
| ISOLATED Worker is `ACTIVE` and conversation is lost | Delivery Plan, exact Task Spec, Worker Card, Git baseline/status, and authorization digest | A new generation may inspect and continue only after all identities match; preserve the lock and material | Do not switch branch, synchronize, reset, or change the assignment from a message. |
| Worker is `AWAITING_INTEGRATION` | Worker Card, Delivery Record, reachable immutable commit, and Plan entry | Verify the commit and wait for Master, or follow an explicit Master rework/supersession | Do not amend, force-push, or mark integrated locally. |
| Worker is `BLOCKED` | Blocker kind, text, blocked time, recovery owner, changed paths, and preserved material | Keep the blocker and ask Master for a recorded recovery decision | Elapsed time is not takeover authority; do not clean the worktree. |
| Master conversation is lost while delivery is active | Plan, all Task Specs, Worker Cards, Delivery Records, and Git | A rotated Master can inspect and publish a new plan/status revision through the normal fence | Do not remove handoffs, rewrite source identity, or infer candidate/publication success. |
| A Plan/Card write is partial or has a digest mismatch | Exact persisted bytes, temp-file/atomicity evidence when available, and prior snapshot | Stop, retain the prior valid snapshot and preserved material, and mark the affected action blocked | Do not merge fields from the message, current path, or another snapshot. |
| Candidate evidence survives a conversation loss | Release Plan, Gate Registry, per-Gate sources, exact `release_head_sha`, and evidence digests | Revalidate every Gate; stale or unverifiable evidence is rerun or marked `STALE` | Do not promote a remembered `PASSED` status or use a different head. |
| v1 history is found during v2 recovery | Original v1 bytes/digest, protocol fence, migration decision, and authority classification | Keep v1 read-only and create a separately bound v2 successor only if migration conditions hold | Do not rewrite v1, synthesize missing fields, or use v1 authority after expiry. |

The recovery invariant is conservative: a missing source can prevent a current action, but a conversation can never fill a
missing source. Dirty or untracked material is preserved and named in the recovery record.

## 8. Non-goals

This design deliberately does not:

- modify the current `SKILL.md`, JSON Schema, validator, CLI flags, templates, or persisted v1 records;
- define executable v2 field syntax beyond the ownership shape and JSON-shaped examples above;
- rewrite, backfill, normalize, or delete v1 history;
- infer a release candidate or publication from a delivery handoff, Git branch name, model profile, or conversation message;
- grant external calls, executions, publication, destructive operations, synchronization, or scope expansion;
- choose a model, claim an effective scheduler tier, or make mode selection depend on model choice;
- replace Git as the source for repository bytes, commit identity, ancestry, reachability, dirty state, or untracked material;
- introduce an automatic cleanup, takeover, timeout, retry, or state-repair policy;
- define a second cost state machine or require a full Plan/Card protocol for every FAST operation;
- make optional Gate evidence a release requirement unless a later release policy explicitly says so;
- merge delivery and release certification into one status or one mutable record; or
- decide the repository's external publication mechanism or production ownership.

## 9. Unresolved policy decisions

The following decisions remain explicit inputs to adoption; conservative defaults apply until Master records a choice:

1. Are tags ever allowed on a lightweight FAST path, or are tags always STRICT as the adaptive-modes design recommends?
2. Is a FAST Operation Receipt required for every push, or only when the work crosses a conversation/recovery boundary?
3. Which protected branches and release systems require action-time confirmation in addition to a persisted publication grant?
4. Which repository-local triggers force ISOLATED for a nominally FAST contract-adjacent change?
5. Where are append-only snapshots retained and how long are v1/v2 evidence, preserved untracked material, and publication
   receipts retained?
6. Is the Master Card kept as a delivery-only projection, or is it split into a Delivery Card and a Release Card before the
   v2 fence? The authority model requires the split even if the storage file remains one projection temporarily.
7. Which role owns the Gate Registry, and how are registry revisions approved when an optional Gate is added or removed?
8. Must a local publication use a separate Publication Record even when it cannot mutate remote state, or may a policy-approved
   FAST receipt be sufficient?

These are policy choices, not reasons to weaken the single-owner rule or to reinterpret v1 history.

## 10. Staged implementation order

The order intentionally starts with policy, storage, and observed recovery behavior. It does not begin by changing the Schema
or validator.

### Phase 0 — Approve the authority vocabulary

- Ratify the mode triggers, severity/stopping rules, owner matrix, delivery/release boundary, and unresolved policy choices.
- Choose the protocol major/minor identity and the first migration-fence plan revision.
- Exit criterion: one signed decision record names the owners and has no unresolved ownership collision.

### Phase 1 — Build a read-only fixture and inventory corpus

- Inventory representative FAST, ISOLATED, STRICT, v1, recovery, rework, candidate, and publication histories.
- Record expected owner, reference, projection, cache, and forbidden-copy classifications without changing runtime behavior.
- Include missing-conversation, partial-write, dirty-worktree, stale-head, legacy-authority, and optional-Gate fixtures.
- Exit criterion: every fixture has one expected source of truth and an explicit blocked result for missing/ambiguous sources.

### Phase 2 — Persist owner records and references

- Add append-only writers/readers for the Operation Receipt, Delivery Plan, Task Spec, Worker Card, Delivery Record, Release
  Plan, Release Evidence, and Publication Record using the authority matrix.
- Add canonical digest computation, source references, revision fences, and atomic persistence around the records, while keeping
  the current v1 contract and CLI unchanged.
- Exit criterion: records can be written, reopened, and recovered from without conversation text; no record copies an owned
  payload as a second authority.

### Phase 3 — Implement lifecycle projections and recovery flows

- Connect Worker locks, Master handoffs, integration mappings, candidate selection, and publication receipts to their owning
  records.
- Exercise IDLE/ACTIVE/AWAITING/BLOCKED recovery, supersession, grandfathering, v1 preservation, mode upgrade, and safe
  downgrade using the Phase 1 corpus.
- Exit criterion: each transition has a durable before/after snapshot and a deterministic stop outcome for mismatch.

### Phase 4 — Add the v1 read-only adapter and protocol fence

- Read and digest-check v1 records without rewriting them.
- Permit only the canonical default-deny v1 authority adapter; route ambiguous or allowed legacy authority to a superseding
  task and preserve the old record.
- Exit criterion: migration is idempotent, v1 bytes/digests remain unchanged, and no legacy result is promoted without fresh
  v2 evidence.

### Phase 5 — Freeze the v2 Schema

- Translate the already exercised owner records into an exact recursive Schema with explicit nullable branches, enums, digest
  rules, and additional-property behavior.
- Verify the Schema against the Phase 1 corpus and the persisted protocol fence.
- Exit criterion: the Schema expresses the observed authority boundaries without requiring historical v1 rewrites.

### Phase 6 — Implement validator and public CLI behavior

- Add standalone Schema-first validation, current cross-record checks, historical pair checks, and explicit `NOT_RUN` output
  behind the stable CLI facade.
- Add negative tests for identity drift, revision/time regression, terminal rewrite, owner mismatch, stale candidate evidence,
  ambiguous migration, partial writes, optional-Gate omission, and unauthorized publication.
- Exit criterion: all accepted and rejected Phase 1 fixtures produce the declared result and no compatibility path silently
  changes active v2 meaning.

### Phase 7 — Pilot and adopt

- Pilot one FAST operation, one ISOLATED delivery, and one STRICT release with the declared cost and safety measurements.
- Master reviews the integrated tree, recomputes derived evidence, and adopts v2 only after all pilots meet their gates.
- Exit criterion: the adoption record names the active fence; older v1 records remain read-only and the publication role remains
  separately authorized.

No phase permits a Worker to synchronize, merge, rebase, reset, push, publish, or broaden authorization implicitly. Any change
to an authority boundary is a new, explicitly published task or protocol cycle.

## 11. Adoption checklist

Before v2 becomes normative, Master should be able to answer “yes” to all of these questions:

- Does every mutable fact in the matrix have one owner and a digest/reference path?
- Can a reviewer distinguish a delivery-complete tree, a passed candidate, and a published production outcome?
- Can recovery proceed from persisted records and Git after every listed conversation-loss scenario?
- Are v1 records byte-preserved, immutable, and safely fenced from current v2 authority?
- Can mode upgrades and downgrades be proved without erasing evidence or bypassing a failed Gate?
- Are optional Gates visible without accidentally changing the ordinary required-Gate aggregate semantics?
- Does the authorization record keep the four capabilities independent and default-deny when unused?
- Are publication and external action receipts separately attributable to the authorized role?
- Do current and historical readers report unknown or missing relationships as blocked/`NOT_RUN`, not as implied success?

Until these answers are evidenced by the later phases, retain the current v1 contracts and the conservative defaults from the
adaptive operating-modes design.
