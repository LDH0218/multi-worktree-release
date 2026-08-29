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

The plan is versioned and contains at least:

```yaml
plan_revision: <positive-integer>
tasks:
  - task_id: <id>
    worktree: <absolute-path>
    dispatch_status: READY | GATED | PUBLISHED | BLOCKED | INTEGRATED | SUPERSEDED
    dispatch_wave: <positive-integer>
    blocked_by: [<task-id>]
    parallel_with: [<task-id>]
```

Before publishing a wave, Master validates that task IDs are unique, every dependency reference is known, no dependency cycle
exists, every target worktree is available and matches its task card, and semantic file or contract ownership does not overlap.
Mechanical overlap in generated outputs is allowed only when Master owns regeneration from the integrated sources. Master
normalizes `parallel_with` symmetrically and computes waves from unresolved `blocked_by` edges.

Tasks with no unresolved blockers and no semantic overlap may be published in the same wave. A task with unresolved blockers
remains `GATED` and is not published. A worktree preflight failure removes only that task from the current wave; it does not
delay independent tasks.

Any change to dependencies, parallel groups, dispatch waves, owner, worktree, frozen baseline, acceptance, or authority
boundary increments `plan_revision`. New or revised assignments carry the new revision. Older revisions for an affected task
are rejected; an unaffected active task may continue only when Master records that its plan entry is unchanged.

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
- Candidate invalidation: clear or mark stale the affected candidate evidence after integration, rework, plan, or projection
  changes, then rerun the required gates from the integrated tree.

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
an RFC 3339 `expires_at` must be concrete. `max_cost` is non-negative and `cost_unit` identifies an ISO 4217 currency or an
explicit provider billing unit. `resume_execution_id: null` prohibits resumption. A non-null resume ID authorizes only that
exact execution and only when the task explicitly permits resumption; `fresh_execution_required: true` and a non-null resume
ID are mutually exclusive. Secrets are never valid controlled inputs or state-card values.

Digests use `sha256:<64-lowercase-hex>`. For structured data, hash UTF-8 JSON with object keys recursively sorted, arrays kept
in order, and no insignificant whitespace. For files or byte streams, hash the exact bytes. Compute `envelope_digest` over the
authorization object with `envelope_digest` itself set to `null`. The digest is an integrity check, not a grant of authority.
Any change to the authorization envelope is an authority-boundary change and requires a superseding task rather than an
in-place revision.

## Task publication contract

An executable task should contain:

```yaml
task_id: <stable-id>
task_spec_revision: <positive-integer>
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
state: IDLE | ACTIVE | AWAITING_INTEGRATION | BLOCKED
task_id: <id-or-null>
task_spec_revision: <integer-or-null>
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
outcome: completed | cancelled | superseded | null
```

Master card uses a list; never concatenate multiple SHAs into one field:

```yaml
state: IDLE | ACTIVE | BLOCKED
release_task_id: <id-or-null>
plan_revision: <integer-or-null>
frozen_baseline_sha: <full-sha-or-null>
worker_handoffs:
  - task_id: <worker-task-id>
    task_spec_revision: <positive-integer>
    source_thread_id: <thread-id>
    role: <role>
    worker_commit_sha: <full-sha>
    integrated_as_sha: <full-sha-or-null>
    state: RECEIVED | INTEGRATED | REWORK_REQUESTED
release_head_sha: <full-sha-or-null>
blocker: <text-or-null>
```

`task_id + task_spec_revision + source_thread_id` is the message identity. Duplicate delivery is idempotent. Reject older
revisions, unknown issuers, and messages inconsistent with a non-IDLE lock. Use a higher revision for an in-scope correction;
use `supersedes_task_id` when replacing the task.

## Exception and recovery

Published work is interruptible and may be revised or superseded by Master, but it must not be silently changed. A Worker that
discovers an unexpected dependency, wrong assignment, wrong scope, wrong worktree, ownership ambiguity, or baseline mismatch
must stop new implementation and external activity, preserve `HEAD`, status, changed paths, and untracked material, set the task
card to `BLOCKED`, and report the finding to Master. The report includes the task identity, plan revision, current SHA, evidence,
affected paths or tasks, and any uncommitted changes.

Master then applies the narrowest valid recovery:

- An unexpected dependency revises the plan, marks only affected tasks `GATED` or `BLOCKED`, and publishes the upstream task or
  a new task revision. Independent tasks continue when their plan entries remain valid.
- An in-scope correction increments `task_spec_revision`. A changed objective, owner, worktree, or authority boundary creates a
  new task with `supersedes_task_id`; the old assignment cannot continue.
- A wrongly assigned task with no changes may be cancelled and returned to `IDLE`. A task with dirty changes remains preserved
  until Master records whether the work is retained, reassigned, or explicitly discarded. No automatic reset, cleanup, or
  deletion is allowed.
- A committed or handed-off task remains immutable. Rework or reassignment creates a successor task and commit; it does not
  amend or force-push the original.
- If a Worker or conversation disappears, Master performs read-only inspection, preserves the worktree state, and may assign a
  takeover or superseding task. Elapsed time alone does not authorize automatic takeover or cleanup.
- A stale baseline is handled by Master. Workers do not independently synchronize; if shared inputs changed or the patch no
  longer applies, Master publishes a replacement with the new baseline. If the patch remains disjoint and applicable, Master
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
`release_head_sha`. Any new integration or rework invalidates all prior candidate evidence because the candidate SHA changes. A
dependency-plan or regenerated-projection change invalidates the gates whose inputs changed; Master clears or marks the stale
evidence and reruns the release-candidate and affected gates.

Master may resolve mechanical conflicts in generated indexes, hashes, manifests, or projections by regeneration. Semantic
conflicts in Worker-owned inputs, compilers, or business rules return to that Worker. Unknown ownership remains blocked.

An accepted Worker handoff releases its state lock even if another layer blocks the global release candidate. A failure caused
by that Worker requires an explicit rework revision.

## Rotation and recovery

A new conversation generation performs a read-only bootstrap and does not inherit implementation, runtime, publication,
destructive, synchronization, or scope-expansion authorization. A rotation handoff records the current plan revision and
dispatch waves, all worktree SHAs and states, patch-equivalent historical forks, active contracts and inputs, latest gates,
preserved material, unfinished work, blockers and recovery owners, and actions requiring renewed authority. The new generation
must not resume an affected task under an older plan or task revision.

If an old conversation disappears:

- Recover facts from Git, governance files, and the task card.
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
