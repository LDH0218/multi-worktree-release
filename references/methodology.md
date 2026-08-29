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
13. A non-IDLE task card is a worktree lock.
14. Messages and state never contain secrets.

## Lifecycle

```text
Read-only bootstrap
→ Master discovery and ownership decision
→ Explicit cross-task publication
→ Worker verifies identity and baseline
→ Worker task card = ACTIVE
→ implementation, checks, atomic commit
→ structured handoff
→ Worker task card = AWAITING_INTEGRATION
→ Master patch and contract review
→ integration
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

## Task publication contract

An executable task should contain:

```yaml
task_id: <stable-id>
task_spec_revision: <positive-integer>
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
  blocked_by: [<condition>]
authorization:
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: null
  controlled_input: null
  route: null
  max_calls: 0
  max_cost: 0
  fresh_execution_required: true
  resume_execution_id: null
  expires_at: null
  envelope_digest: null
acceptance: [<targeted-test>, <layer-audit>, <base-relative-audit>, <diff-check>]
commit_message: <message>
stop_conditions: [<baseline-mismatch>, <overlapping-dirty-files>, <ambiguity>, <missing-authorization>]
```

The task must say both what to do and what not to do. The recipient should not need to invent scope, authority, inputs, or
acceptance criteria.

## Durable state cards

Worker card:

```yaml
state: IDLE | ACTIVE | AWAITING_INTEGRATION | BLOCKED
task_id: <id-or-null>
task_spec_revision: <integer-or-null>
source_thread_id: <thread-id-or-null>
issued_at: <timestamp-or-null>
supersedes_task_id: <id-or-null>
worker_generation: <generation-or-null>
frozen_baseline_sha: <full-sha-or-null>
allowed_paths: [<path>]
forbidden_paths: [<path>]
authorization:
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: null
  controlled_input_digest: null
  route: null
  max_calls: 0
  envelope_digest: null
  expires_at: null
acceptance_commands: [<command>]
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

Master may resolve mechanical conflicts in generated indexes, hashes, manifests, or projections by regeneration. Semantic
conflicts in Worker-owned inputs, compilers, or business rules return to that Worker. Unknown ownership remains blocked.

An accepted Worker handoff releases its state lock even if another layer blocks the global release candidate. A failure caused
by that Worker requires an explicit rework revision.

## Rotation and recovery

A new conversation generation performs a read-only bootstrap and does not inherit implementation, runtime, publication,
destructive, synchronization, or scope-expansion authorization. A rotation handoff records all worktree SHAs and states,
patch-equivalent historical forks, active contracts and inputs, latest gates, preserved material, unfinished work, and actions
requiring renewed authority.

If an old conversation disappears:

- Recover facts from Git, governance files, and the task card.
- For `ACTIVE` plus uncommitted changes, inspect and preserve the diff; do not commit or discard without a decision.
- For `AWAITING_INTEGRATION`, verify the commit remains reachable and wait for Master.
- For `BLOCKED`, preserve the blocker evidence.
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
