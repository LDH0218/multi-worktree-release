# Exception and Recovery SOP

This is the decision procedure for safely stopping and recovering a task or release when persisted facts
do not agree. It is a human procedure over the existing v1 Plan, Task Specs, Cards, handoffs, Git
evidence, Schema, validator, and authorization envelope. It adds no machine state or role registry.
`NOT_PROVEN` means the evidence is absent, ambiguous, stale, or unverifiable; it is never a pass. The
[Task Lifecycle SOP](task-lifecycle-sop.md) and [Release SOP](release-sop.md) define the normal path.

Conversation disappearance, duplicate visible conversations, successor confirmation, rotation, and
archive decisions are governed only by the [Conversation Rotation SOP](conversation-rotation-sop.md).
This document tells an operator to stop and route those cases; it does not create a second conversation
lifecycle.

## Universal stop procedure

When an exception is observed:

1. Stop new implementation, external calls, executions, publication, destructive action, synchronization,
   and commits for the affected path. Do not reset, rebase, merge, clean, delete, or silently switch
   context.
2. Record the task identity, Task Spec revision/digest, Plan revision/digest, source thread, role,
   worktree, branch, current full `HEAD`, status, changed/untracked paths, Card state/revision, expected
   fact, actual fact, read-only evidence, and responsible Master decision.
3. Preserve the worktree, commit graph, records, dirty/untracked material, and predecessor evidence. A
   Worker may move its Card to `BLOCKED` through the sidecar when the contract permits; it may not change
   Dispatch status or decide recovery.
4. If the evidence needed to choose a row below is not available, record `NOT_PROVEN`, leave the lock and
   release evidence conservative, and ask Master to reconcile or revise. Conversation text cannot override
   a persisted mismatch.

## Decision table

| Failure or signal | Read-only evidence | Decision and owner | Preserve/next result |
| --- | --- | --- | --- |
| Wrong `HEAD` or frozen baseline | Git full SHA differs from the Task Spec/Card/Plan expected SHA, or ancestry cannot be proved | Worker stops and reports `BASELINE`; Master decides whether to gate, revise, or supersede | Preserve current SHA, diff, commits, and material. Never synchronize independently. |
| Wrong worktree, branch, or role binding | Absolute path, branch, role/generation, or one-to-one binding differs or is unavailable | Worker stops and reports `WORKTREE` or `ASSIGNMENT`; Master reconciles the binding | No branch switch, worktree replacement, cleanup, or deletion. |
| Card missing, stale, malformed, noncanonical, conflicting, or wrong state | Fixed `WORKTREE_TASK.json` cannot be validated, its record revision regresses, or identity/digest does not match the current Plan | Stop. Master may perform only the documented bootstrap/takeover or publish a valid recovery assignment; Worker does not invent a Card | Preserve the sidecar bytes and all records. A missing prior is valid only for a valid initial `ACTIVE` activation. |
| Plan/Task/Card/handoff digest or fence mismatch | `task_spec_digest`, `plan_digest`, acceptance/auth digest, source, revision, wave, or path differs | Stop with `NOT_PROVEN`/`ASSIGNMENT`; Master rejects stale delivery and publishes a higher revision or replacement | No record silently wins; retain the mismatching snapshots as evidence. |
| Scope or ownership violation | Proposed path is forbidden, outside `allowed_paths`, semantically overlapping, or ownership is ambiguous | Worker stops with `OWNERSHIP` or `wrong-scope`; Master narrows, revises, or supersedes | Preserve the proposed diff; do not move it to another worktree or path without a new decision. |
| Unexpected dirty/untracked material | A path was not part of the verified preflight or belongs to another owner | Stop and preserve it; Master determines retained/reassigned/discarded outcome explicitly | No cleanup, reset, commit, or deletion by assumption. |
| Unexpected dependency or parallel conflict | A dependency is unknown/unresolved, a wave edge is invalid, or another task owns an overlapping contract/path | Master gates only the affected task, revises the Plan, or publishes the upstream/replacement task | Independent valid tasks may continue; the affected Worker remains stopped. |
| Missing/expired/ambiguous authorization or unsupported model | Envelope fields/digest/target/expiry are invalid, a required grant is absent, or launcher cannot honor persisted model/effort/tier | Stop with `AUTHORITY` or `ENVIRONMENT`; Master republishes only after a valid current profile/envelope | Default-deny remains in force. Model routing never supplies authorization. |
| Worker discovers a blocker during execution | Dependency, environment, ownership, baseline, or authority failure with preserved evidence | Worker records `BLOCKED` and reports; Master records/reconciles the release-level decision | Keep `HEAD`, Card lock, blocker kind, `blocked_since`, recovery owner, and material intact. |
| In-scope correction (`REVISE`) | Objective/owner/worktree/baseline/authority remain the same, but executable content, acceptance, dependency, or other assignment detail needs correction | Master publishes a higher `task_spec_revision`, new digest, current Plan fence, and explicit recovery; Worker resumes only after the new assignment | Preserve the old assignment and any handed-off commit. Return a recovered Card to `ACTIVE` only through the legal transition. |
| Objective/owner/worktree/baseline/authority change (`SUPERSEDE`) | The immutable assignment identity or authority boundary would change | Master creates a new Task Spec with `supersedes_task_id`; the predecessor becomes terminal `SUPERSEDED` | Do not mutate the old task in place. Preserve predecessor evidence and use a new baseline/owner/binding. |
| Cancellation (`CANCELLED`) | Master has a recorded cancellation decision and has reconciled current status/material | Master stops dispatch and new work; after reconciliation the Worker copies terminal outcome to `last_task` and returns to `IDLE` | Preserve uncommitted work unless separately authorized for disposal; cancellation grants no cleanup. |
| Handoff commit or integration mapping is disputed | SHA is missing, unreachable, amended, force-pushed, or mapped to an unexpected integrated SHA | Master rejects the handoff or requests a higher-revision rework; the original remains immutable | Rework creates a successor commit. Never amend, reset, force-push, or rewrite the original. |
| Master review finds a semantic conflict or `NOT_PROVEN` acceptance | Patch ownership, contract effect, test evidence, ancestry, or provenance cannot be independently proven | Master returns the affected task for rework or marks it blocked; only Master may integrate | Preserve Worker SHA, complete patch, and evidence; regenerate mechanical projections only from Master sources. |
| Duplicate visible conversation or retained binding | More than one visible conversation claims one role or worktree/branch pair | Stop dispatch and follow the Conversation Rotation SOP's duplicate-reconciliation procedure; Master owns any archive decision | Keep predecessor/history and retained worktree untouched; never archive or delete automatically. |
| Conversation disappears or predecessor is unavailable | Persisted Plan, Task Spec, Card, handoff, Git path, SHA, or digest can or cannot be reconciled | Follow the Conversation Rotation SOP. Master recovers from persisted records, preserves dirty/awaiting/blocked evidence, and decides takeover/supersession | Elapsed time does not authorize takeover, archive, cleanup, or deletion. |
| Release candidate, push, closeout, or rollover check is incomplete | Candidate head/gate evidence, publication target/auth, remote result, archive bytes, or rollover receipt is missing or ambiguous | Stop at the last proven boundary and route to the Release SOP; never promote `NOT_PROVEN` | Preserve candidate, target/archive evidence, Master lock, and exact source bytes. |

## State and revision rules

Only Master changes Dispatch status. The legal recovery shape is:

- `PUBLISHED → BLOCKED` on a Worker exception or Master-verified blocker;
- `BLOCKED → PUBLISHED` only after explicit Master recovery with a valid unchanged or higher revision;
- `PUBLISHED → INTEGRATED` only after accepted handoff and the exact `worker_commit_sha → integrated_as_sha`
  mapping; and
- `GATED` or `READY → CANCELLED/SUPERSEDED`, or `PUBLISHED` or `BLOCKED → CANCELLED/SUPERSEDED`, only
  after Master reconciliation and preserved-state outcome. Terminal records remain immutable history.

The bound Worker uses only legal Card transitions: `ACTIVE` or `AWAITING_INTEGRATION → BLOCKED`,
`BLOCKED → ACTIVE` after Master recovery, `AWAITING_INTEGRATION → ACTIVE` only for an explicit higher
revision rework, accepted `AWAITING_INTEGRATION → IDLE`, and recorded cancellation/supersession to
`IDLE`. Every write advances `record_revision`; an `IDLE` Card clears active lock fields and preserves
the completed identity/mapping under `last_task`.

## Recovery completion gate

Recovery is complete only when Master has recorded the decision and the operator can re-run the applicable
standalone Schema/validator checks, current Plan/Worker/Master consistency, ancestry/scope review, and
affected tests from the correct tree. A missing result stays `NOT_PROVEN`. After accepted integration,
recompute derived evidence and candidate Gates from the integrated Master tree; after cancellation or
supersession, preserve the terminal lineage; after a conversation failure, leave lifecycle decisions to
the Conversation Rotation SOP. No recovery row authorizes push, publication, deletion, synchronization,
or scope expansion by itself.
