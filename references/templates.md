# Multi-Worktree Release Templates

Use only the templates relevant to the current operation. Replace every placeholder with repository-verified values. Omit
fields that truly do not apply; do not invent values or authority.

## Task Dependency and Dispatch Plan

Use this plan before publishing implementation work. It is a semantic coordination record and may be represented as YAML, a
table, structured text, or a diagram. In the plan, `A -> B` means that B is blocked by A.

```yaml
release_task_id: <MASTER_RELEASE_TASK_ID>
plan_revision: <positive-integer>
issued_at: <timestamp>
issued_by: <MASTER_SOURCE_THREAD_ID>
tasks:
  - task_id: <id>
    worktree: <absolute-path>
    dispatch_status: READY | GATED | PUBLISHED | BLOCKED | INTEGRATED | SUPERSEDED
    dispatch_wave: <positive-integer>
    blocked_by: [<task-id>]
    parallel_with: [<task-id>]
validation:
  unique_task_ids: <PASS/FAIL>
  known_dependency_references: <PASS/FAIL>
  acyclic_dependencies: <PASS/FAIL>
  worktree_preflight: <PASS/FAIL>
  semantic_ownership_overlap: <NONE OR LIST>
ready_wave: <positive-integer-or-null>
blocked_tasks: [<task-id>]
```

Only Master publishes executable assignments. A task with unresolved `blocked_by` remains `GATED`; a worktree preflight failure
removes only that task from the current wave. When dependencies, waves, owners, worktrees, baselines, acceptance, or authority
boundaries change, increment `plan_revision` and supersede or revise affected assignments.

## New conversation read-only bootstrap

```text
You are <PROJECT>'s <ROLE>-<GENERATION> task.
Use only the absolute worktree <ABSOLUTE_WORKTREE> on branch <BRANCH>; expected HEAD is <FULL_SHA>.

Read the repository governance, architecture index if present, WORKTREE_SCOPE.md, and WORKTREE_TASK.md completely.
Then report the absolute path, branch, HEAD, status, preserved untracked material, and task-card state. If the card is not IDLE,
verify its task ID, task revision, plan revision, dispatch wave, frozen baseline, issuer, Worker SHA, and waiting condition
against this handoff.

Do not switch branches, synchronize, merge, rebase, reset, delete historical material, run external services, create a run,
publish, or expand scope. This generation inherits no external or destructive authorization.
After the read-only check, report inconsistencies and stop; otherwise update your current facts and wait for a concrete task.
```

## Master to Worker task

```text
This is <PROJECT> task <TASK_ID>, revision <REVISION>, plan revision <PLAN_REVISION>, dispatch wave <DISPATCH_WAVE>, issued by
Master task <SOURCE_THREAD_ID> at <TIMESTAMP>.
It <does not supersede another task|supersedes TASK_ID>. Duplicate delivery is idempotent; reject older or mismatched messages.

Worktree and baseline
- Absolute worktree: <PATH>
- Branch: <BRANCH>
- Expected HEAD: <FULL_SHA>
- Preserved dirty/untracked material: <PATHS_OR_NONE>
- On worktree, baseline, assignment, or plan-revision mismatch, stop and report. Do not synchronize, merge, rebase, reset, or
  switch branches.

Objective
- <ONE CONCRETE OUTCOME>

Verified current state
- <REPOSITORY FACT>

Allowed paths
- <PATH>

Forbidden paths
- <PATH>

Inputs and dependencies
- <PATH / REVISION / DIGEST / UPSTREAM COMMIT>

Required behavior
- <REQUIREMENT>

Explicit exclusions
- <NON-GOAL>

Authorization envelope
- External call: <DENIED OR EXACT TARGET/INPUT/ROUTE/LIMIT/EXPIRY>
- Create execution/job: <DENIED OR FRESH-RUN REQUIREMENT>
- Publish: <DENIED OR EXACT TARGET>
- Destructive action: <DENIED OR EXACT TARGET/RECOVERY>
- Scope expansion and synchronization: denied unless separately listed above.

Acceptance
- <COMMAND OR OBSERVABLE CHECK>
- <COMMAND OR OBSERVABLE CHECK>
- Review the complete diff and run the repository's diff-integrity check.

Stop conditions
- Unexpected dependency, wrong assignment, wrong scope, wrong worktree, ownership ambiguity, baseline mismatch, overlapping
  dirty files, or missing authorization: stop, preserve the current state, and report to Master.

Commit and handoff
- Commit message: <MESSAGE>
- Commit only allowed paths.
- Include plan revision <PLAN_REVISION> and dispatch wave <DISPATCH_WAVE> in the task report.
- Report full baseline and result SHAs, changed paths, every check and result, unresolved cross-layer findings, and actual use of
  any external authority.
- Write the compact task card as ACTIVE after verification; after committing, record AWAITING_INTEGRATION and do not rewrite
  the handed-off commit.
```

## Worker to Master handoff

```text
Task: <TASK_ID>, revision=<REVISION>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>,
source_thread_id=<SOURCE_THREAD_ID>
Worktree: <ABSOLUTE_PATH>
Branch: <BRANCH>
Frozen baseline: <FULL_SHA>
Worker commit: <FULL_SHA> <SUBJECT>
Task-card state: AWAITING_INTEGRATION

Completed outcome
- <BEHAVIORAL RESULT>

Changed paths
- <PATH>

Verification
- <COMMAND>: <PASS/FAIL AND KEY EVIDENCE>

Unresolved or cross-layer findings
- <ACTUAL / EXPECTED / REPRODUCTION / RESPONSIBLE ROLE>

Plan and lock status
- Plan entry: <UNCHANGED / REVISED / SUPERSEDED>
- Worktree lock: <RETAINED / RELEASED>
- Blocker: <NONE OR BLOCKER_KIND AND EVIDENCE>

Authorization statement
- <EXTERNAL CALLS USED OR NOT USED>
- <EXECUTION/JOB CREATED OR NOT CREATED>
- <PUBLICATION OR DESTRUCTIVE ACTION USED OR NOT USED>
- <PRESERVED MATERIAL STATUS>
```

## Worker exception report

Use when implementation must stop before handoff.

```text
Task: <TASK_ID>, task_revision=<REVISION>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Source thread: <SOURCE_THREAD_ID>
Worktree: <ABSOLUTE_PATH>
Branch: <BRANCH>
Current HEAD: <FULL_SHA>
Task-card state: BLOCKED
Blocker kind: DEPENDENCY | ASSIGNMENT | BASELINE | OWNERSHIP | ENVIRONMENT | AUTHORITY | WORKTREE
Blocked since: <TIMESTAMP>
Recovery owner: <ROLE_OR_THREAD>

Finding
- Actual: <ACTUAL>
- Expected: <EXPECTED>
- Evidence or reproduction: <COMMAND / OUTPUT / FACT>
- Discovered dependency or assignment error: <DETAIL>
- Affected tasks or paths: <LIST>

Preserved state
- Uncommitted changes: <PATHS_OR_NONE>
- Untracked material: <PATHS_OR_NONE>
- External calls, runs, publication, or destructive actions: <USED OR NOT USED>

Requested Master decision
- <REVISE / GATE / SUPERSEDE / CANCEL / TAKEOVER / OTHER IN-SCOPE DECISION>
```

## Master integration confirmation

```text
Task: <TASK_ID>, revision=<REVISION>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Worker commit: <WORKER_SHA>
Integration mapping: <WORKER_SHA> -> <INTEGRATED_AS_SHA>
Release-candidate HEAD: <RELEASE_HEAD_SHA>
Integration method: <MERGE / CHERRY-PICK / PATCH-EQUIVALENT EXISTING CHANGE>

Integrated-tree regeneration
- <DERIVED OUTPUT>: <RESULT>

Master gates
- <COMMAND>: <PASS/FAIL AND KEY EVIDENCE>

Candidate evidence
- Previous release-candidate HEAD: <SHA_OR_NONE>
- Previous evidence: <VALID / INVALIDATED / NOT APPLICABLE>
- Invalidation reason: <NEW INTEGRATION / REWORK / PLAN CHANGE / PROJECTION CHANGE / NONE>
- Evidence recomputed from integrated tree: <YES/NO>

Authorization status
- <EXTERNAL CALL / RUN / PUBLISH / DESTRUCTIVE ACTION ACTUALLY USED OR NOT USED>

Release candidate: <PASSED/FAILED>.
Worker handoff: <ACCEPTED/REWORK REQUIRED>; responsible findings: <NONE OR LIST>.
Record integrated_as_sha and release_head_sha. Return to IDLE when accepted. If another layer blocks release, Master retains
the release task or assigns that layer without occupying this accepted Worker's lock.
```

## Master rework request

```text
Rework for task <TASK_ID>, task_revision=<NEXT_REVISION>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Original Worker commit: <OLD_SHA>
Status: not accepted as a release candidate contribution. Do not amend or force-push the original commit.

Evidence
- Actual: <ACTUAL>
- Expected: <EXPECTED>
- Reproduction or failed gate: <COMMAND/EVIDENCE>
- Owned paths: <PATHS>

Allowed paths: <PATHS>
Forbidden paths: <PATHS>
Baseline for successor task: <FULL_SHA>
Authorization: <EXACT ENVELOPE; DEFAULT DENY>
Acceptance: <COMMANDS>

Return the task card to ACTIVE and create a successor commit. Report both old and new SHAs. If the worktree or baseline differs,
stop and report instead of synchronizing independently.
```

## Plan revision or baseline replacement

```text
Master plan update: <OLD_PLAN_REVISION> -> <NEW_PLAN_REVISION>
Reason: <VERIFIED DEPENDENCY / ASSIGNMENT ERROR / BASELINE DRIFT / OWNERSHIP CHANGE / OTHER>
Affected tasks: <TASK_IDS>
Unaffected tasks explicitly verified to continue: <TASK_IDS_OR_NONE>

Task decisions
- Task: <TASK_ID>
  Old task revision: <REVISION>
  Action: <GRANDFATHER / GATE / REVISE / SUPERSEDE / CANCEL>
  New task ID and revision: <ID_AND_REVISION_OR_NONE>
  New baseline: <FULL_SHA_OR_NONE>
  New dependency or dispatch wave: <DETAIL_OR_NONE>

Preserved material and lock outcome
- HEAD/status/changed paths checked: <EVIDENCE>
- Preserved uncommitted or untracked material: <PATHS_OR_NONE>
- Final outcome: <BLOCKED / ACTIVE / IDLE / AWAITING_INTEGRATION>

Master authorization and next action
- <EXACT DECISION AND EXECUTABLE NEXT MESSAGE>
```

The new assignment must carry the new plan revision. Older messages for affected tasks are rejected; no Worker synchronizes
independently to satisfy the replacement baseline.

## Cancellation or supersession

```text
Task: <TASK_ID>, task_revision=<CURRENT_REVISION>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Decision: <CANCELLED / SUPERSEDED BY NEW_TASK_ID REVISION=N>
Reason: <VERIFIED FACT OR CHANGED DECISION>

Stop new implementation, external calls, and commits. Do not discard uncommitted work. First report HEAD, status, and changed
paths, blocker kind, and preserved material. After Master reconciliation, record outcome=<CANCELLED/SUPERSEDED> and return to
IDLE. Wait for a complete new task before doing further work.
```

## Conversation-generation handoff

```text
This is the read-only handoff from <ROLE>-<OLD_GENERATION> to <ROLE>-<NEW_GENERATION>.

Identity and worktree
- Role: <ROLE>; absolute worktree: <PATH>; branch: <BRANCH>.
- HEAD: <FULL_SHA>; expected status: <STATUS INCLUDING PRESERVED PATHS>.
- The generation label is context only, not Git, product workflow, runtime, or authorization identity.

Task state
- WORKTREE_TASK: <IDLE/ACTIVE/AWAITING_INTEGRATION/BLOCKED>.
- Current plan revision: <N_OR_NULL>.
- If non-IDLE: task_id=<ID>, task_revision=<N>, dispatch_wave=<N>, source_thread_id=<ID>, frozen_baseline=<SHA>.
- Worker commit=<SHA_OR_NULL>; integrated_as_sha=<SHA_OR_NULL>; release_head_sha=<SHA_OR_NULL>.
- Waiting condition or blocker: <TEXT_OR_NULL>.
- Blocker kind=<KIND_OR_NULL>; blocked_since=<TIMESTAMP_OR_NULL>; recovery_owner=<ROLE_OR_THREAD_OR_NULL>.

Cross-worktree facts
- Master: <PATH / BRANCH / SHA / STATUS>.
- Worker handoffs: <TASK / WORKER SHA / INTEGRATED SHA / STATE>.
- Patch-equivalent integrated historical forks: <MAPPING_OR_NONE>.

Contracts and gates
- Current formal inputs/revisions/routes/candidate: <EXACT VALUES>.
- Latest gates: <COMMANDS AND RESULTS>.
- Preserved material: <PATHS AND POLICY>.

Authorization
- External calls: not inherited.
- Execution/job creation: not inherited.
- Publication, deletion, scope expansion, and synchronization: not inherited.

Read all repository governance and the state card. Verify path, branch, HEAD, status, and this handoff without modification.
On mismatch, report and stop. On agreement, update current facts and wait; do not resume work or external authority yourself.
```
