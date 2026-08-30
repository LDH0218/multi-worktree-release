# Multi-Worktree Release Templates

Use only the templates relevant to the current operation. Replace every placeholder with repository-verified values. Required
identity, state, revision, and authorization fields are never omitted; record explicit `false`, `null`, `0`, or an empty list
when denied or empty. Omit only fields that the canonical contract explicitly marks optional. Never invent values or authority.
The machine field and enum authority is [contracts.schema.json](contracts.schema.json); these templates must remain equivalent.

## Task Dependency and Dispatch Plan

Use this plan before publishing implementation work. It is a semantic coordination record and may be represented as YAML, a
table, structured text, or a diagram. In the plan, `A -> B` means that B is blocked by A.

```yaml
schema_version: 1
record_revision: <positive-integer>
release_task_id: <MASTER_RELEASE_TASK_ID>
plan_revision: <positive-integer>
plan_digest: <sha256-digest>
issued_at: <timestamp>
updated_at: <timestamp>
issued_by: <MASTER_SOURCE_THREAD_ID>
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

Only Master publishes executable assignments. A task with unresolved `blocked_by` remains `GATED`; a worktree preflight failure
removes only that task from the current wave. Every semantic plan change increments `plan_revision`. Changed in-scope executable
content increments the affected `task_spec_revision` and digest. A changed objective, owner, worktree, frozen baseline, or
authority boundary requires a superseding task. Unaffected active tasks continue only through an explicit digest-verified
`GRANDFATHER` decision.

A `GRANDFATHER` entry preserves the existing task spec, digest, and its original `task_spec_plan_revision`; do not rewrite the
task to copy the new global plan fence. `NEW` and `REVISE` task specs bind to the current plan revision. Terminal entries retain
their last issued task-spec plan revision and digest.

Persist the complete task specification atomically and verify its digest before atomically updating this plan. Increment
`record_revision` on every plan write and `plan_revision` only for semantic plan changes. Unless repository governance defines
another durable path, write the plan to `<MASTER_WORKTREE>/.codex/multi-worktree-release/dispatch-plan.json` and task specs to
the sibling `tasks/` directory. Do not dispatch from a conversation-only projection or after a partial write or digest mismatch.

## New conversation read-only bootstrap

```text
You are <PROJECT>'s <ROLE>-<GENERATION> task.
Use only the absolute worktree <ABSOLUTE_WORKTREE> on branch <BRANCH>; expected HEAD is <FULL_SHA>.

Read the repository governance, architecture index if present, WORKTREE_SCOPE.md, and WORKTREE_TASK.md completely.
Read the persisted Dispatch Plan and complete task specification from the repository-defined paths or the default
`.codex/multi-worktree-release/` state directory when they exist.
Then report the absolute path, branch, HEAD, status, preserved untracked material, and task-card state. If the card is not IDLE,
verify its task ID, task revision, task-spec digest, plan revision, dispatch wave, frozen baseline, issuer, Worker SHA, and
waiting condition against this handoff. Verify card and plan `record_revision` values and the Worker/Dispatch state mapping.

Do not switch branches, synchronize, merge, rebase, reset, delete historical material, run external services, create a run,
publish, or expand scope. This generation inherits no external or destructive authorization.
After the read-only check, report inconsistencies and stop; otherwise update your current facts and wait for a concrete task.
```

## Master to Worker task

```text
This is <PROJECT> schema version <1>, task <TASK_ID>, revision <REVISION>, task-spec digest <TASK_SPEC_DIGEST>, plan revision
<PLAN_REVISION>, dispatch wave <DISPATCH_WAVE>, issued by Master task <SOURCE_THREAD_ID> at <TIMESTAMP>.
It <does not supersede another task|supersedes TASK_ID>. Duplicate delivery is idempotent; reject older or mismatched messages.

Worktree and baseline
- Persisted task specification: <ABSOLUTE_PATH>
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
- Schema version: 2
- External-call grant: <allowed, structured service target, route/provider, max_calls, max_cost, cost_unit>
- Create-execution grant: <allowed, structured execution target, route/provider, max_calls, max_cost, cost_unit,
  fresh_execution_required, exact resume_execution_id-or-null>
- Publish grant: <allowed, structured publication target, route/provider, max_calls=0, max_cost, cost_unit>
- Destructive-operation grant: <allowed, structured resource target, route/provider, max_calls=0, max_cost, cost_unit>
- Each structured target: <kind, non-empty id, local-or-remote transport, exact paths/refs scope>
- Controlled input: <INPUT_OR_NULL; NEVER A SECRET>
- Controlled-input digest: <SHA256_DIGEST_OR_NULL>
- Expiry: <RFC3339_TIMESTAMP_OR_NULL>
- Envelope digest: <COMPUTED_SHA256_DIGEST>
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

For each denied v2 grant, spell out `allowed: false`, `target/route/provider/cost_unit: null`, and zero call/cost budgets;
the denied execution grant additionally uses `fresh_execution_required: true` and `resume_execution_id: null`. Put
fresh/resume fields nowhere else. Use non-empty route/provider only for remote targets and null values for local targets. A
schema-version-1 envelope may be quoted only as an unchanged grandfathered record. To migrate it, use the read-only adapter
only for canonical default-deny, then have Master publish a superseding task and recompute every downstream digest.

## Worker to Master handoff

```text
Task: <TASK_ID>, revision=<REVISION>, task_spec_digest=<TASK_SPEC_DIGEST>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>,
source_thread_id=<SOURCE_THREAD_ID>
Persisted task specification: <ABSOLUTE_PATH>
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
- Acceptance digest: <SHA256_DIGEST>
- <COMMAND>: <PASS/FAIL AND KEY EVIDENCE>

Unresolved or cross-layer findings
- <ACTUAL / EXPECTED / REPRODUCTION / RESPONSIBLE ROLE>

Plan and lock status
- Plan entry: <UNCHANGED / REVISED / SUPERSEDED>
- Worktree lock: <RETAINED / RELEASED>
- Blocker: <NONE OR BLOCKER_KIND AND EVIDENCE>

Authorization statement
- Envelope digest: <SHA256_DIGEST>
- <EXTERNAL CALLS USED OR NOT USED>
- <EXECUTION/JOB CREATED OR NOT CREATED>
- <PUBLICATION OR DESTRUCTIVE ACTION USED OR NOT USED>
- <PRESERVED MATERIAL STATUS>
```

## Worker exception report

Use when implementation must stop before handoff.

```text
Task: <TASK_ID>, task_revision=<REVISION>, task_spec_digest=<TASK_SPEC_DIGEST>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Source thread: <SOURCE_THREAD_ID>
Dispatch Plan: <ABSOLUTE_PATH / PLAN_REVISION / RECORD_REVISION / DIGEST>
Persisted task specification: <ABSOLUTE_PATH>
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
Task: <TASK_ID>, revision=<REVISION>, task_spec_digest=<TASK_SPEC_DIGEST>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Persisted task specification: <ABSOLUTE_PATH>
Authorization envelope digest: <SHA256_DIGEST>
Acceptance digest: <SHA256_DIGEST>
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
- Previous gate-input digest: <DIGEST_OR_NONE>
- Current gate-input digest: <DIGEST>
- Invalidation reason: <INTEGRATED-TREE CHANGE / PLAN CHANGE / AUTHORIZATION CHANGE / ACCEPTANCE CHANGE / PROJECTION CHANGE / NONE>
- Evidence recomputed from integrated tree: <YES/NO>
- Unintegrated Worker-only rework leaves existing candidate evidence unchanged.

Authorization status
- <EXTERNAL CALL / RUN / PUBLISH / DESTRUCTIVE ACTION ACTUALLY USED OR NOT USED>

Release candidate: <PASSED/FAILED>.
Worker handoff: <ACCEPTED/REWORK REQUIRED>; responsible findings: <NONE OR LIST>.
Record integrated_as_sha and release_head_sha. When accepted, copy the task identity, `COMPLETED` outcome, and commit mapping to
`last_task`, clear active lock fields to default-deny/null values, and return to IDLE. If another layer blocks release, Master
retains the release task or assigns that layer without occupying this accepted Worker's lock.
```

## Master rework request

```text
Rework for task <TASK_ID>, task_revision=<NEXT_REVISION>, task_spec_digest=<NEW_TASK_SPEC_DIGEST>,
plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Persisted task specification: <ABSOLUTE_PATH>
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
Authorization: <COMPLETE CANONICAL ENVELOPE; KEEP EVERY REQUIRED FIELD; DEFAULT DENY>
Acceptance: <COMMANDS>

Return the task card to ACTIVE and create a successor commit. Report both old and new SHAs. If the worktree or baseline differs,
stop and report instead of synchronizing independently.
```

## Plan revision or baseline replacement

```text
Master plan update: <OLD_PLAN_REVISION> -> <NEW_PLAN_REVISION>
Dispatch Plan: <ABSOLUTE_PATH / NEW_RECORD_REVISION / NEW_PLAN_DIGEST>
Reason: <VERIFIED DEPENDENCY / ASSIGNMENT ERROR / BASELINE DRIFT / OWNERSHIP CHANGE / OTHER>
Affected tasks: <TASK_IDS>
Unaffected tasks explicitly verified to continue: <TASK_IDS_OR_NONE>

Task decisions
- Task: <TASK_ID>
  Old task revision: <REVISION>
  Old task-spec digest: <DIGEST>
  Revision decision: <GRANDFATHER / REVISE / SUPERSEDE / CANCELLED>
  Dispatch action: <GATE / READY / PUBLISH / NONE>
  New task ID and revision: <ID_AND_REVISION_OR_NONE>
  New task-spec digest: <DIGEST_OR_NONE>
  New baseline: <FULL_SHA_OR_NONE>
  New dependency or dispatch wave: <DETAIL_OR_NONE>

Preserved material and lock outcome
- HEAD/status/changed paths checked: <EVIDENCE>
- Preserved uncommitted or untracked material: <PATHS_OR_NONE>
- Final outcome: <BLOCKED / ACTIVE / IDLE / AWAITING_INTEGRATION>

Master authorization and next action
- <EXACT DECISION AND EXECUTABLE NEXT MESSAGE>
```

The new assignment must carry the new plan revision. `REVISE` requires a higher task revision and new digest. `GRANDFATHER`
requires an unchanged persisted digest. Objective, owner, worktree, frozen-baseline, or authority changes require `SUPERSEDE`.
`CANCELLED` is terminal. Dispatch gating is recorded separately from the revision decision. Older messages for affected tasks
are rejected; no Worker synchronizes independently to satisfy the replacement baseline.

## Cancellation or supersession

```text
Task: <TASK_ID>, task_revision=<CURRENT_REVISION>, task_spec_digest=<TASK_SPEC_DIGEST>, plan_revision=<PLAN_REVISION>, dispatch_wave=<DISPATCH_WAVE>
Persisted task specification: <ABSOLUTE_PATH>
Decision: <CANCELLED / SUPERSEDED BY NEW_TASK_ID REVISION=N>
Reason: <VERIFIED FACT OR CHANGED DECISION>

Stop new implementation, external calls, and commits. Do not discard uncommitted work. First report HEAD, status, and changed
paths, blocker kind, and preserved material. After Master reconciliation, copy the identity and
outcome=<CANCELLED/SUPERSEDED> to `last_task`, clear active lock fields to default-deny/null values, and return to IDLE. Wait for
a complete new task before doing further work.
```

## Historical validation invocation

Use complete retained JSON snapshots and keep previous/current generations coherent:

```text
python3 scripts/validate_contracts.py \
  --previous-plan <PREVIOUS_PLAN_JSON> --plan <CURRENT_PLAN_JSON> \
  --previous-worker-card <PREVIOUS_WORKER_CARD_JSON> --worker-card-json <CURRENT_WORKER_CARD_JSON> \
  --previous-master-card <PREVIOUS_MASTER_CARD_JSON> --master-card-json <CURRENT_MASTER_CARD_JSON>
```

Each previous option requires its current counterpart. The Worker inputs are JSON contract records, not
`WORKTREE_TASK.md`. A partial invocation is allowed, but omitted cross-record relationships must remain `NOT_RUN`; reviewers
must require all three pairs when claiming complete history. Record the canonical previous/current snapshot digests and retain
the validator's `PASS`, `FAIL`, and `NOT_RUN` distinctions.

With no previous option, supply multiple current records to enforce their cross-record consistency without transition output:

```text
python3 scripts/validate_contracts.py \
  --plan <CURRENT_PLAN_JSON> \
  --worker-card-json <CURRENT_WORKER_CARD_JSON> \
  --master-card-json <CURRENT_MASTER_CARD_JSON>
```

Every relationship whose two current records are present is checked. Omitted relationships remain internal `NOT_RUN` results;
a single current record retains the existing current-only output. A lower-revision `REWORK_REQUESTED` handoff may remain beside
a later `GRANDFATHER` entry only when the entry preserves the original revised Task Spec Plan fence and all compatible identity,
digest, baseline, and authorization evidence.

## Conversation-generation handoff

```text
This is the read-only handoff from <ROLE>-<OLD_GENERATION> to <ROLE>-<NEW_GENERATION>.

Identity and worktree
- Role: <ROLE>; absolute worktree: <PATH>; branch: <BRANCH>.
- HEAD: <FULL_SHA>; expected status: <STATUS INCLUDING PRESERVED PATHS>.
- Dispatch Plan: <ABSOLUTE_PATH / PLAN_REVISION / RECORD_REVISION / DIGEST>.
- Persisted task specification: <ABSOLUTE_PATH_OR_NULL / TASK_SPEC_DIGEST_OR_NULL>.
- The generation label is context only, not Git, product workflow, runtime, or authorization identity.

Task state
- WORKTREE_TASK: <IDLE/ACTIVE/AWAITING_INTEGRATION/BLOCKED>.
- Worker-card record revision and updated time: <N / RFC3339_TIMESTAMP>.
- Current plan revision: <N_OR_NULL>.
- If non-IDLE: task_id=<ID>, task_revision=<N>, task_spec_digest=<DIGEST>, dispatch_wave=<N>, source_thread_id=<ID>,
  frozen_baseline=<SHA>.
- Worker commit=<SHA_OR_NULL>; integrated_as_sha=<SHA_OR_NULL>; release_head_sha=<SHA_OR_NULL>.
- Waiting condition or blocker: <TEXT_OR_NULL>.
- Blocker kind=<KIND_OR_NULL>; blocked_since=<TIMESTAMP_OR_NULL>; recovery_owner=<ROLE_OR_THREAD_OR_NULL>.
- If IDLE: last_task=<TASK_ID / TASK_SPEC_REVISION / TASK_SPEC_DIGEST / OUTCOME / WORKER_SHA / INTEGRATED_SHA OR NULL>.

Cross-worktree facts
- Master: <PATH / BRANCH / SHA / STATUS>.
- Worker handoffs: <TASK / WORKER SHA / INTEGRATED SHA / STATE>.
- Patch-equivalent integrated historical forks: <MAPPING_OR_NONE>.

Contracts and gates
- Current formal inputs/revisions/routes/candidate: <EXACT VALUES>.
- Candidate evidence: <RELEASE_HEAD_SHA / GATE_INPUT_DIGEST / NONE|STALE|PASSED|FAILED>.
- Latest gates: <COMMANDS / RESULTS / EVIDENCE_DIGESTS>.
- Preserved material: <PATHS AND POLICY>.

Authorization
- External calls: not inherited.
- Execution/job creation: not inherited.
- Publication, deletion, scope expansion, and synchronization: not inherited.

Read all repository governance and the state card. Verify path, branch, HEAD, status, and this handoff without modification.
On mismatch, report and stop. On agreement, update current facts and wait; do not resume work or external authority yourself.
```
