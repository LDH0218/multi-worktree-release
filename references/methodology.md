# Multi-Conversation, Multi-Worktree Release Method

Use this reference to design, adopt, or review the collaboration model. Repository-owned governance takes precedence over
these reusable defaults.

## Identity model

Keep eight identities distinct:

| Identity | Lifetime | Rotation effect |
| --- | --- | --- |
| Responsibility role | Long-lived | None |
| Conversation generation | Replaceable context | Changes |
| Git worktree | Long-lived workspace | None |
| Git branch | Repository policy | None |
| Frozen commit baseline | Per task | Only an explicit sync/replacement changes it |
| Product workflow/module | Product architecture | None |
| Runtime execution/job | Per run | None |
| External authorization | Per bounded action | Never inherited |

Conversation generations such as `Master-1.1` and `Platform-2.0` are human context labels only.

## Topology and responsibility

The minimum useful topology has an integration role and one or more responsibility Workers:

```text
Shared/platform Worker ──┐
                         ├──> Master integrated tree ──> release-candidate gates
Domain/workflow Worker ──┘
```

Create worktrees from stable ownership boundaries, not from the desired number of agents. Split another Worker only when the
new role has durable contract ownership, an independent change cadence, and little file overlap.

Executable messages follow a star topology. Workers may exchange discovery evidence but route all executable cross-layer
instructions, baselines, synchronization, and rework through Master.

## Task Dependency and Dispatch Plan

The Task Dependency and Dispatch Plan is the normative coordination model for a release batch. It is not required to be a
visual graph; structured text, YAML, a table, or a diagram are all valid representations. A dependency edge `A -> B` means
that task B is blocked by task A.

The normative recovery record is machine-readable and persisted in the Master worktree before dispatch. Repository governance
may name another durable location; otherwise use:

```text
<MASTER_WORKTREE>/.codex/multi-worktree-release/
├── dispatch-plan.json
└── tasks/
    └── <task-id>.json
```

This directory is Master-local by default because it contains absolute paths and live coordination state. Adoption records
whether repository policy tracks or ignores it; neither choice authorizes cleanup. Conversation messages, tables, YAML
renderings, and diagrams are projections of these records and cannot replace them. A task card may stay compact because the
complete task specification is recoverable from its persisted task-spec path and digest.

The default plan path is `<MASTER_WORKTREE>/.codex/multi-worktree-release/dispatch-plan.json`; task specifications use absolute
paths beneath `<MASTER_WORKTREE>/.codex/multi-worktree-release/tasks/`.

[contracts.schema.json](contracts.schema.json) is the machine-field and enum authority. The examples in this document and
[templates.md](templates.md) are human-readable projections and must remain schema-equivalent.

The plan is versioned and contains at least:

```yaml
schema_version: 1
record_revision: <positive-integer>
plan_revision: <positive-integer>
plan_digest: <sha256-digest>
issued_at: <rfc3339-timestamp>
updated_at: <rfc3339-timestamp>
release_task_id: <id>
issued_by: <master-source-thread-id>
state_root: <absolute-path>
task_specs_root: <absolute-path>
tasks:
  - task_id: <id>
    task_spec_revision: <positive-integer>
    task_spec_digest: <sha256-digest>
    task_spec_path: <absolute-path>
    task_spec_plan_revision: <positive-integer>
    revision_decision: NEW | GRANDFATHER | REVISE | SUPERSEDE | CANCELLED
    owner_role: <role>
    worktree: <absolute-path>
    branch: <branch>
    expected_head: <full-sha>
    acceptance_digest: <sha256-digest>
    authorization_envelope_digest: <sha256-digest>
    dispatch_status: READY | GATED | PUBLISHED | BLOCKED | INTEGRATED | SUPERSEDED | CANCELLED
    dispatch_wave: <positive-integer>
    blocked_by: [<task-id>]
    parallel_with: [<task-id>]
validation:
  unique_task_ids: <PASS/FAIL>
  known_dependency_references: <PASS/FAIL>
  acyclic_dependencies: <PASS/FAIL>
  worktree_preflight: <PASS/FAIL>
  semantic_ownership_overlap: <NONE OR LIST>
  persisted_task_specs: <PASS/FAIL>
  task_spec_digests: <PASS/FAIL>
  plan_digest: <PASS/FAIL>
  atomic_persistence: <PASS/FAIL>
ready_wave: <positive-integer-or-null>
blocked_tasks: [<task-id>]
```

Before publishing a wave, Master validates that task IDs are unique, every dependency reference is known, no dependency cycle
exists, every target worktree is available and matches its task card, and semantic file or contract ownership does not overlap.
Mechanical overlap in generated outputs is allowed only when Master owns regeneration from the integrated sources. Master
normalizes `parallel_with` symmetrically and computes waves from unresolved `blocked_by` edges. It also verifies every persisted
task-spec path and digest, the plan digest, and the completion of each atomic replacement before sending a task message.

Tasks with no unresolved blockers and no semantic overlap may be published in the same wave. A task with unresolved blockers
remains `GATED` and is not published. A worktree preflight failure removes only that task from the current wave; it does not
delay independent tasks.

Any semantic plan change increments `plan_revision`. If an affected task's dependencies, dispatch wave, allowed behavior,
inputs, outputs, acceptance, or other executable content changes in scope, increment `task_spec_revision` and recompute
`task_spec_digest`. A changed objective, owner, worktree, frozen baseline, or authority boundary creates a new task with
`supersedes_task_id`; it is never an in-place revision. Older plan or task revisions for an affected task are rejected.

`plan_revision` is a fencing token and is not part of message identity. An unaffected active task may keep its existing task
revision only when Master records `GRANDFATHER` in the new plan, verifies that its complete persisted task-spec digest is
unchanged, preserves the task spec's original `task_spec_plan_revision`, and sends no altered executable assignment. `NEW` and
`REVISE` entries bind their task spec to the current plan revision. Terminal `SUPERSEDE` and `CANCELLED` entries preserve the
last issued task-spec plan revision and digest. A status-only plan update changes none of these fields.

`record_revision` increments on every persisted plan write, including status-only changes; `plan_revision` increments only for
semantic plan changes. Compute `plan_digest` with the canonical structured-data digest rule, setting `plan_digest` to `null`
while hashing. Persist each complete task specification first by writing a sibling temporary file, flushing it when supported,
and atomically renaming it to the final path. Verify `task_spec_digest`, then persist the plan with the same atomic-replacement
pattern, verify `plan_digest`, and only then publish the message. A partial write or digest mismatch stops dispatch.

Separate three completion states:

| State | Evidence | Authority |
| --- | --- | --- |
| Integration complete | `worker_commit_sha → integrated_as_sha` | Master |
| Release candidate passed | gates on `release_head_sha` | Master |
| Production release complete | release-system evidence under a current authorization | Authorized release role |

## Core invariants

1. One long-lived role has one explicit absolute worktree and branch.
2. Conversation rotation reuses the worktree and branch; it does not copy uncommitted files.
3. Every task freezes a full commit SHA.
4. Workers never independently merge, rebase, reset, or synchronize Master.
5. Master performs a read-only discovery gate before publishing implementation work.
6. Workers run owned-layer tests and affected shared-contract tests; Master alone declares cross-layer release readiness.
7. A downstream Worker may do Discovery while an upstream contract is unfrozen, but not speculative implementation.
8. External calls, runs, publication, deletion, and scope expansion are default-deny and never inherited.
9. Historical evidence and preserved untracked material follow retention policy, not cleanliness preferences.
10. Cross-task messages transport the full assignment; local task cards persist compact state.
11. A handed-off commit is immutable. Rework creates a successor commit.
12. Final derived evidence is recomputed from the integrated Master tree.
13. A non-IDLE task card is a lock on that worktree only, not a global release lock.
14. A plan or task revision change fences the affected task; independent unchanged tasks may continue only under an explicitly
    verified current plan entry.
15. Any new integrated change invalidates all release-candidate evidence until the integrated-tree evidence is recomputed and
    release-candidate gates rerun.
16. Messages and state never contain secrets.

## Lifecycle

```text
Read-only bootstrap
→ Master discovery and ownership decision
→ versioned Task Dependency and Dispatch Plan
→ publish the current ready wave (one or more parallel tasks)
→ Worker verifies identity and baseline
→ Worker task card = ACTIVE
→ implementation, checks, atomic commit
→ structured handoff
→ Worker task card = AWAITING_INTEGRATION
→ Master patch and contract review
→ integration
→ recompute the plan and publish the next ready wave when blockers clear
→ integrated-tree projection regeneration
→ targeted, shared, base-relative, and release-candidate gates
→ Master sends integration mapping and candidate HEAD
→ accepted Worker returns to IDLE; rework Worker returns to ACTIVE
→ optional conversation rotation
```

Explicit branches:

- Worker-owned defect: publish a rework revision; preserve the original handoff commit.
- Stale baseline or changed scope: publish a synchronization task or a replacement with `supersedes_task_id`.
- Mechanical generated-output conflict: Master integrates sources and regenerates the derived output.
- Ambiguous ownership or correct value: mark `BLOCKED`, preserve evidence, and request a decision.
- Cancellation: stop new work, inspect current state, preserve user changes, record the outcome, then release the lock.
- Unexpected dependency or assignment error: stop the affected Worker, preserve evidence, revise or supersede the affected task,
  and leave independent tasks running when their plan entries remain valid.
- Plan revision: reject stale messages for affected tasks; publish a new revision or a superseding task through Master.
- Candidate invalidation: clear or mark stale all candidate evidence after an integrated-tree HEAD change. A plan,
  authorization, acceptance, or projection change invalidates the gates whose inputs changed. Unintegrated Worker rework does
  not change the candidate. Rerun required gates from the integrated tree.

## Canonical authorization envelope

Every executable task, non-IDLE Worker card, rework request, and persisted task specification uses the same complete
authorization envelope. All fields are required. A denied capability remains explicit as `false`, `null`, or `0`; a missing
field is invalid and never grants authority.

```yaml
authorization:
  schema_version: 1
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: null
  controlled_input: null
  controlled_input_digest: null
  route: null
  provider: null
  max_calls: 0
  max_cost: 0
  cost_unit: null
  fresh_execution_required: true
  resume_execution_id: null
  expires_at: null
  envelope_digest: null
```

When a capability is allowed, `target`, `controlled_input`, `controlled_input_digest`, route/provider, applicable limits, and
an RFC 3339 `expires_at` must be concrete. `max_cost` is a non-negative integer count and `cost_unit` identifies the exact
atomic unit, such as `USD-cent` or a provider credit. `resume_execution_id: null` prohibits resumption. A non-null resume ID
authorizes only that exact execution and only when the task explicitly permits resumption; `fresh_execution_required: true`
and a non-null resume ID are mutually exclusive. Secrets are never valid controlled inputs or state-card values.

Digests use `sha256:<64-lowercase-hex>`. Structured digest inputs use only null, booleans, integers, strings, arrays, and objects
with string keys; floating-point values are invalid and decimals use strings or integer units. Hash UTF-8 JSON with object keys
recursively sorted, arrays kept in order, strings preserved exactly as stored, and no insignificant whitespace. For files or
byte streams, hash the exact bytes. Compute `envelope_digest` over the authorization object with `envelope_digest` itself set
to `null`. The digest is an integrity check, not a grant of authority. Any change to the authorization envelope is an
authority-boundary change and requires a superseding task rather than an in-place revision.

Compute `task_spec_digest` with the same structured-data rule over the complete persisted task specification, with
`task_spec_digest` itself set to `null`. Messages may render that specification as prose, but they must carry its digest and may
not change executable meaning. An equal task identity with a different task-spec digest is invalid, not a revision.

## Task publication contract

An executable task should contain:

```yaml
schema_version: 1
task_id: <stable-id>
task_spec_revision: <positive-integer>
task_spec_digest: <sha256-digest>
task_spec_path: <absolute-path>
plan_revision: <positive-integer>
dispatch_wave: <positive-integer>
source_thread_id: <issuing-master-task-id>
issued_at: <timestamp>
supersedes_task_id: <id-or-null>
generation: <role-generation>
owner_role: <role>
worktree: <absolute-path>
branch: <branch>
expected_head: <full-sha>
task_class: <class>
objective: <one-outcome>
current_state: <verified-facts>
allowed_paths: [<path>]
forbidden_paths: [<path>]
inputs:
  - path: <formal-input>
    revision: <revision-or-digest>
outputs: [<expected-artifact-or-interface>]
derived_outputs:
  recompute_on_master: [<projection-or-index>]
dependencies:
  upstream_commits: [<sha>]
  parallel_with: [<task-id>]
  blocked_by: [<task-id>]
authorization:
  schema_version: 1
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: null
  controlled_input: null
  controlled_input_digest: null
  route: null
  provider: null
  max_calls: 0
  max_cost: 0
  cost_unit: null
  fresh_execution_required: true
  resume_execution_id: null
  expires_at: null
  envelope_digest: null
acceptance: [<targeted-test>, <layer-audit>, <base-relative-audit>, <diff-check>]
commit_message: <message>
stop_conditions: [<baseline-mismatch>, <overlapping-dirty-files>, <unexpected-dependency>, <wrong-assignment>,
  <wrong-scope>, <wrong-worktree>, <ambiguity>, <missing-authorization>]
```

The task must say both what to do and what not to do. The recipient should not need to invent scope, authority, inputs, or
acceptance criteria.

## Durable state cards

Worker card:

```yaml
schema_version: 1
state: IDLE | ACTIVE | AWAITING_INTEGRATION | BLOCKED
record_revision: <positive-integer>
updated_at: <rfc3339-timestamp>
task_id: <id-or-null>
task_spec_revision: <integer-or-null>
task_spec_digest: <sha256-digest-or-null>
task_spec_path: <absolute-path-or-null>
plan_revision: <integer-or-null>
dispatch_wave: <integer-or-null>
source_thread_id: <thread-id-or-null>
issued_at: <timestamp-or-null>
supersedes_task_id: <id-or-null>
worker_generation: <generation-or-null>
frozen_baseline_sha: <full-sha-or-null>
allowed_paths: [<path>]
forbidden_paths: [<path>]
authorization:
  schema_version: 1
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: null
  controlled_input: null
  controlled_input_digest: null
  route: null
  provider: null
  max_calls: 0
  max_cost: 0
  cost_unit: null
  fresh_execution_required: true
  resume_execution_id: null
  expires_at: null
  envelope_digest: null
acceptance_commands: [<command>]
blocker_kind: DEPENDENCY | ASSIGNMENT | BASELINE | OWNERSHIP | ENVIRONMENT | AUTHORITY | WORKTREE | null
blocked_since: <timestamp-or-null>
recovery_owner: <role-or-thread-or-null>
blocker: <text-or-null>
worker_commit_sha: <full-sha-or-null>
integrated_as_sha: <full-sha-or-null>
release_head_sha: <full-sha-or-null>
last_task:
  task_id: <id-or-null>
  task_spec_revision: <integer-or-null>
  task_spec_digest: <sha256-digest-or-null>
  outcome: COMPLETED | CANCELLED | SUPERSEDED | null
  worker_commit_sha: <full-sha-or-null>
  integrated_as_sha: <full-sha-or-null>
```

Master card uses a list; never concatenate multiple SHAs into one field:

```yaml
schema_version: 1
state: IDLE | ACTIVE | BLOCKED
record_revision: <positive-integer>
updated_at: <rfc3339-timestamp>
release_task_id: <id-or-null>
plan_revision: <integer-or-null>
dispatch_plan_path: <absolute-path-or-null>
dispatch_plan_digest: <sha256-digest-or-null>
frozen_baseline_sha: <full-sha-or-null>
worker_handoffs:
  - task_id: <worker-task-id>
    task_spec_revision: <positive-integer>
    task_spec_digest: <sha256-digest>
    plan_revision: <positive-integer>
    dispatch_wave: <positive-integer>
    source_thread_id: <thread-id>
    role: <role>
    frozen_baseline_sha: <full-sha>
    authorization_envelope_digest: <sha256-digest>
    acceptance_digest: <sha256-digest>
    worker_commit_sha: <full-sha>
    integrated_as_sha: <full-sha-or-null>
    state: RECEIVED | INTEGRATED | REWORK_REQUESTED
candidate_evidence:
  release_head_sha: <full-sha-or-null>
  gate_input_digest: <sha256-digest-or-null>
  status: NONE | STALE | PASSED | FAILED
  checks:
    - command: <command>
      result: PASS | FAIL
      evidence_digest: <sha256-digest>
blocker: <text-or-null>
```

## State transitions

Only Master changes Dispatch status. Allowed transitions are:

| From | To | Required evidence |
| --- | --- | --- |
| `GATED` | `READY` | All blockers resolved; dependency and worktree preflight pass |
| `READY` | `PUBLISHED` | Task spec and plan persisted atomically; digests and preflight pass; message sent |
| `GATED` or `READY` | `CANCELLED` or `SUPERSEDED` | Master decision and preserved-state check |
| `PUBLISHED` | `BLOCKED` | Worker exception report or Master-verified blocker |
| `BLOCKED` | `PUBLISHED` | Explicit Master recovery; unchanged digest or valid higher task revision |
| `PUBLISHED` | `INTEGRATED` | Accepted handoff and `worker_commit_sha → integrated_as_sha` mapping |
| `PUBLISHED` or `BLOCKED` | `CANCELLED` or `SUPERSEDED` | Master reconciliation and preserved-state outcome |

`INTEGRATED`, `CANCELLED`, and `SUPERSEDED` are terminal for that task ID. A later status-only transition increments plan
`record_revision` and `updated_at`, but not `plan_revision` or `task_spec_revision`. An executable-content change follows the
revision and supersession rules instead of being hidden in a status transition.

Only the bound Worker updates its Worker card, except that Master may do so during an explicitly recorded takeover after a
read-only inspection. Allowed Worker transitions are:

| From | To | Required evidence |
| --- | --- | --- |
| `IDLE` | `ACTIVE` | Matching persisted plan, task spec, card, worktree, branch, baseline, and digests |
| `ACTIVE` | `AWAITING_INTEGRATION` | Atomic commit and completed Worker checks |
| `ACTIVE` or `AWAITING_INTEGRATION` | `BLOCKED` | Preserved state and exception report |
| `BLOCKED` | `ACTIVE` | Explicit Master recovery with a valid unchanged or higher task revision |
| `AWAITING_INTEGRATION` | `ACTIVE` | Explicit rework request with a higher task revision |
| `AWAITING_INTEGRATION` | `IDLE` | Accepted integration confirmation |
| `ACTIVE`, `AWAITING_INTEGRATION`, or `BLOCKED` | `IDLE` | Recorded cancellation or supersession after Master reconciliation |

Every card write increments its `record_revision` and updates `updated_at`. On return to `IDLE`, copy the completed task
identity, outcome, and commit mapping into `last_task`; clear all active identity, scope, authorization, blocker, and lock fields
to their null, empty, or default-deny values. Historical evidence remains in `last_task`, Git, the persisted task spec, and the
Dispatch Plan rather than keeping a stale lock.

Only Master updates the Master card. `IDLE → ACTIVE` requires a persisted plan; `ACTIVE → BLOCKED` records a release-level
blocker; `BLOCKED → ACTIVE` requires a recorded recovery decision; and `ACTIVE` or `BLOCKED → IDLE` requires the release task
to be completed, cancelled, or superseded with all Worker outcomes preserved. Worker state maps to Dispatch status as follows:

| Worker state | Compatible Dispatch status |
| --- | --- |
| `IDLE` | No current task, or terminal `INTEGRATED` / `CANCELLED` / `SUPERSEDED` |
| `ACTIVE` | `PUBLISHED` |
| `AWAITING_INTEGRATION` | `PUBLISHED` |
| `BLOCKED` | `BLOCKED` |

A mismatch between these records blocks further execution until Master reconciles it; no record silently wins.

### Previous/current snapshot validation

The contract validator accepts three independent historical pairs:

- `--previous-plan PREVIOUS --plan CURRENT`
- `--previous-worker-card PREVIOUS --worker-card-json CURRENT`
- `--previous-master-card PREVIOUS --master-card-json CURRENT`

A previous option without its current counterpart is a usage error. Each path is one complete UTF-8 JSON object; the Worker
option does not parse `WORKTREE_TASK.md`. Both snapshots must independently satisfy schema version 1, exact fields, digests,
and ordinary current-snapshot invariants before comparison. A previous Plan must still resolve the exact historical Task Specs
it records; a mutable current file is not a substitute.

For every record type, `record_revision` is non-decreasing. Equal revisions require byte-independent canonical object equality
and are reported as a no-op; changed records advance the revision and cannot move `updated_at` backwards. Plan semantic
changes advance `plan_revision`; status-only writes preserve semantic content and obey the Dispatch transition table. Terminal
Dispatch entries and terminal Master handoffs are append-only. Worker assignment identity, authorization, handed-off commits,
integration mappings, and candidate evidence cannot be rewritten in place; rework requires the documented successor revision.

A status-only Plan write recomputes `plan_digest` without advancing `plan_revision`; the corresponding Master Card may
synchronize `dispatch_plan_digest` in a higher card `record_revision` while preserving release task, Plan path, semantic Plan
revision, and frozen baseline. When a task ID advances through `REVISE`, its lower-revision `REWORK_REQUESTED` handoff remains
terminal history. Plan/Master consistency validates current-revision handoffs against the current entry and permits that older
handoff only when its source, role, baseline, authorization, and older Plan fence remain compatible with the revised entry.

When multiple record types are supplied, Plan/Worker, Plan/Master, and Worker/Master consistency is checked once within the
previous generation and once within the current generation—never across generations. Missing relationships report `NOT_RUN`.
Historical output distinguishes `PASS`, `FAIL`, and `NOT_RUN` and includes canonical snapshot digests. Supplying only one pair
is valid partial history; a complete release-history gate requires all three pairs and no `NOT_RUN` result. Omitting every
previous option retains current-only behavior, and `--skip-self-test` does not disable requested snapshot or transition checks.

`task_id + task_spec_revision + source_thread_id` is the message identity. `plan_revision` is its fencing token and
`task_spec_digest` proves content equality. Duplicate delivery is idempotent only when the identity and digest both match.
Reject an equal identity with a different digest, older task revisions, stale plan fences for affected entries, unknown
issuers, and messages inconsistent with a non-IDLE lock. Use a higher task revision for an in-scope correction; use a new task
with `supersedes_task_id` for a changed objective, owner, worktree, frozen baseline, or authority boundary.

## Exception and recovery

Published work is interruptible and may be revised or superseded by Master, but it must not be silently changed. A Worker that
discovers an unexpected dependency, wrong assignment, wrong scope, wrong worktree, ownership ambiguity, or baseline mismatch
must stop new implementation and external activity, preserve `HEAD`, status, changed paths, and untracked material, set the task
card to `BLOCKED`, and report the finding to Master. The report includes the task identity, plan revision, current SHA, evidence,
affected paths or tasks, and any uncommitted changes.

Master then applies the narrowest valid recovery:

- An unexpected dependency revises the plan, marks only affected tasks `GATED` or `BLOCKED`, and publishes the upstream task or
  a new task revision. Independent tasks continue when their plan entries remain valid.
- An in-scope correction increments `task_spec_revision` and changes `task_spec_digest`. A changed objective, owner, worktree,
  frozen baseline, or authority boundary creates a new task with `supersedes_task_id`; the old assignment cannot continue.
- A wrongly assigned task with no changes may be cancelled and returned to `IDLE`. A task with dirty changes remains preserved
  until Master records whether the work is retained, reassigned, or explicitly discarded. No automatic reset, cleanup, or
  deletion is allowed.
- A committed or handed-off task remains immutable. Rework or reassignment creates a successor task and commit; it does not
  amend or force-push the original.
- If a Worker or conversation disappears, Master performs read-only inspection, preserves the worktree state, and may assign a
  takeover or superseding task. Elapsed time alone does not authorize automatic takeover or cleanup.
- A stale baseline is handled by Master. Workers do not independently synchronize; if shared inputs changed or the patch no
  longer applies, Master publishes a superseding task with the new baseline. If the patch remains disjoint and applicable, Master
  may integrate it only after ownership, ancestry, and affected-gate review.

Every recovery decision records the old and new task or plan revisions, the reason, preserved material, and the resulting lock
state. Worker-to-Worker messages may carry read-only evidence but may not resolve or execute recovery decisions.

## Integration and conflict ownership

Master should:

1. Verify ancestry against the task baseline and inspect the complete patch.
2. Verify file/contract ownership and check patch equivalence for possible prior cherry-pick integration.
3. Integrate only the intended patch, not unrelated Worker history.
4. Regenerate derived outputs from integrated sources.
5. Run targeted, affected shared-contract, base-relative, and strict release-candidate gates.
6. Recheck the worktree and preserved untracked material.
7. Record every Worker mapping and the final candidate HEAD.
8. Send the result back to each Worker.

Master rejects a handoff whose task or plan revision is stale for its affected plan entry, unless Master has explicitly verified
that the entry is unchanged. A release candidate and its gates are valid only for the exact integrated-tree
`release_head_sha` and `gate_input_digest`. Any integrated-tree change invalidates all prior candidate evidence because the
candidate SHA changes. A Worker-only rework that has not been integrated leaves the candidate unchanged. A dependency-plan,
authorization, acceptance, or regenerated-projection change invalidates the gates whose inputs changed; Master clears or marks
the stale evidence and reruns the release-candidate and affected gates.

Master may resolve mechanical conflicts in generated indexes, hashes, manifests, or projections by regeneration. Semantic
conflicts in Worker-owned inputs, compilers, or business rules return to that Worker. Unknown ownership remains blocked.

An accepted Worker handoff releases its state lock even if another layer blocks the global release candidate. A failure caused
by that Worker requires an explicit rework revision.

## Rotation and recovery

A new conversation generation performs a read-only bootstrap and does not inherit implementation, runtime, publication,
destructive, synchronization, or scope-expansion authorization. A rotation handoff records the current plan revision and
task revisions and digests, dispatch waves, all worktree SHAs and states, patch-equivalent historical forks, active contracts
and inputs, latest gates, preserved material, unfinished work, blockers and recovery owners, and actions requiring renewed
authority. The new generation must not resume an affected task under an older plan or task revision or a mismatched digest.

If an old conversation disappears:

- Recover facts from Git, governance files, the persisted Dispatch Plan, complete task specifications, and the task card.
- Stop recovery if the plan, task spec, or state-card identities, revisions, paths, or digests disagree; conversation history
  cannot override a persisted mismatch.
- For `ACTIVE` plus uncommitted changes, inspect and preserve the diff; do not commit or discard without a decision.
- For `AWAITING_INTEGRATION`, verify the commit remains reachable and wait for Master.
- For `BLOCKED`, preserve the blocker kind, evidence, `blocked_since`, and recovery owner.
- Only Master may invalidate the old task, assign a takeover, or publish a superseding task.

## Adoption sequence

1. Inventory roles, contracts, worktrees, branches, release scripts, external authorities, historical evidence, and dirty state.
2. Define ownership and dependency order from actual data/control flow.
3. Establish repository routing, long-lived scope files, compact task cards, and release governance.
4. Create or validate persistent worktrees by responsibility boundary.
5. Pilot one small, testable, non-external task through the full handoff and integration loop.
6. Add guards for ownership, obsolete entrypoints, document projections, task-message identity, default-deny migration, and
   integrated-tree regeneration.
7. Enable conversation rotation only after the first stable integration.

## Effectiveness measures

Track trends in baseline mismatch rate, handoff rejection rate, semantic conflict rate, post-integration projection drift,
first-pass release-gate failure rate, rework round trips, integration wait time, and unauthorized actions. Unauthorized actions
must remain zero. Metrics improve task slicing and gates; they must not reward bypassing stop conditions or reducing necessary
verification.
