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
model_policy:
  schema_version: 1
  enforced_from_plan_revision: <positive-integer>
  owner_defaults:
    master:
      model: gpt-5.6-sol
      reasoning_effort: high
      service_tier: default
      selection_reason: owner-default:master
    ordinary_worker:
      model: gpt-5.6-luna
      reasoning_effort: max
      service_tier: priority
      selection_reason: owner-default:ordinary-worker
    complex_worker:
      model: gpt-5.6-sol
      reasoning_effort: high
      service_tier: default
      selection_reason: owner-default:complex-worker
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
    model_profile:
      model: <gpt-5.6-sol-or-gpt-5.6-luna>
      reasoning_effort: <high-or-max>
      service_tier: <default-or-priority>
      selection_reason: <owner-default:master-or-owner-default:ordinary-worker-or-owner-default:complex-worker>
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

Task Spec `dependencies.blocked_by` is the canonical direct graph; the Plan entry is only its current unresolved direct
projection. Derive waves from the static graph, require exact Plan/Task Spec equality, validate transitive reduction and
parallel incomparability, and recompute `blocked_tasks` plus the `READY`/`PUBLISHED` `ready_wave` frontier on every write.

Write `allowed_paths` and `forbidden_paths` as repository-relative POSIX paths. Reject absolute paths, backslashes, empty
segments, `.`/`..` segments, and repository escapes. Normalize one trailing directory slash before component-aware parallel
ownership comparison, so `src/x` and `src/x/` conflict rather than becoming aliases.

`model_policy` and `model_profile` may be omitted only for legacy records. After `enforced_from_plan_revision`, every `NEW` or
`REVISE` task must persist the same exact profile in its Task Spec and Plan entry. Older digest-preserved records below the
fence remain untouched. The exact defaults are Master `gpt-5.6-sol`/`high`/`default`
(`owner-default:master`), ordinary Worker `gpt-5.6-luna`/`max`/`priority`
(`owner-default:ordinary-worker`), and complex Worker `gpt-5.6-sol`/`high`/`default`
(`owner-default:complex-worker`). A launcher that cannot honor the profile must stop dispatch. Model `service_tier` is not an
authorization route/provider and grants no external call, run, publication, destructive operation, synchronization, or scope.

A `GRANDFATHER` entry preserves the existing task spec, digest, and its original `task_spec_plan_revision`; do not rewrite the
task to copy the new global plan fence. `NEW` and `REVISE` task specs bind to the current plan revision. Terminal entries retain
their last issued task-spec plan revision and digest.

Treat Task Spec `supersedes_task_id` as a checked predecessor edge. At or after the plan-revision-15 migration fence, and for
every current nonterminal successor, require one distinct known older predecessor with terminal `SUPERSEDED` status. Reject
self, unknown, future, cyclic, duplicate-live-successor, source-lineage, and endpoint authorization-binding failures. A
previous/current replacement transitions exactly one predecessor via `SUPERSEDE` and adds exactly one linked `NEW` successor;
older terminal records below the fence remain immutable compatibility evidence.

Persist the complete task specification atomically and verify its digest before atomically updating this plan. Increment
`record_revision` on every plan write and `plan_revision` only for semantic plan changes. Unless repository governance defines
another durable path, write the plan to `<MASTER_WORKTREE>/.codex/multi-worktree-release/dispatch-plan.json` and task specs to
the sibling `tasks/` directory. Do not dispatch from a conversation-only projection or after a partial write or digest mismatch.
All timestamp placeholders use strict timezone-bearing RFC 3339
`YYYY-MM-DDTHH:MM:SS[.1-6 digits](Z|+HH:MM|-HH:MM)` values; never use a date-only, space separator, timezone-less value,
non-colon offset, impossible calendar date/time, or non-string substitute.

## Candidate evidence v2

Use this projection for new candidate evidence. Keep v1 aggregate records unchanged until safe migration.

```yaml
schema_version: 2
release_task_id: <MASTER_RELEASE_TASK_ID>
release_head_sha: <EXACT_INTEGRATED_HEAD_SHA>
plan_revision: <POSITIVE_INTEGER_AUDIT_FENCE>
plan_digest: <SHA256_OR_NULL_AUDIT_CONTEXT>
gate_registry_digest: <RECOMPUTED_SHA256>
gate_registry:
  - gate_id: <STABLE_KEBAB_ID>
    gate_revision: <POSITIVE_INTEGER>
    required: true | false
    gate_definition: <BOUNDED_CANONICAL_VALUE>
    gate_definition_digest: <RECOMPUTED_SHA256>
    runner_policy: <BOUNDED_CANONICAL_VALUE>
    runner_policy_digest: <RECOMPUTED_SHA256>
    checks:
      - check_id: <STABLE_KEBAB_ID>
        check_revision: <POSITIVE_INTEGER>
        command_spec: <BOUNDED_CANONICAL_VALUE_WITH_SUCCESS_EXIT_CODES>
        command_spec_digest: <RECOMPUTED_SHA256>
        runner_policy: <BOUNDED_CANONICAL_VALUE>
        runner_policy_digest: <RECOMPUTED_SHA256>
        input_source_ids: [<CANONICALLY_SORTED_STABLE_SOURCE_ID>]
gate_input_digest: <RECOMPUTED_COMPATIBILITY_SHA256_OR_NULL>
status: NONE | STALE | PASSED | FAILED
legacy: null
gates:
  - gate_id: <REGISTERED_GATE_ID>
    gate_revision: <REGISTERED_REVISION>
    required: true | false
    status: NONE | STALE | PASSED | FAILED
    input_digest: <RECOMPUTED_SHA256_OR_NULL>
    evidence_digest: <RECOMPUTED_SHA256_OR_NULL>
    input_sources:
      - source_id: integrated-tree
        kind: git-commit
        locator: master-integrated-tree
        revision: <EXACT_INTEGRATED_HEAD_SHA>
        value_digest: <SHA256_OF_EXACT_CONSUMED_VALUE>
    checks:
      - check_id: <REGISTERED_CHECK_ID>
        check_revision: <REGISTERED_REVISION>
        command: <BOUNDED_NON_SECRET_DESCRIPTION>
        input_source_ids: [<CANONICALLY_SORTED_STABLE_SOURCE_ID>]
        result: PASS | FAIL
        input_digest: <RECOMPUTED_SHA256>
        evidence_digest: <RECOMPUTED_SHA256>
        execution_ref: <NON_SECRET_REFERENCE_OR_NULL; NON_NULL_IF_EXECUTION_REF_REQUIRED>
        exit_code: <INTEGER>
        stdout_digest: <SHA256>
        stderr_digest: <SHA256>
        observed_artifacts:
          - locator: <NON_SECRET_LOCATOR>
            value_digest: <SHA256>
        runner_digest: <SHA256>
        observed_at: <RFC3339_TIMESTAMP>
    invalidation_reason: <NULL_OR_ENUM_REASON>
```

The candidate identity is only `release_task_id + release_head_sha`. The plan and registry summaries are audit context. A
status-only Plan write does not stale Gates whose selected semantic source manifests are unchanged. A changed head makes every
Gate stale. Same-head selective reuse is allowed only with complete registered membership, revisions, requiredness, and source
mapping; otherwise clear asserted Gate/check evidence and use the all-Gate `STALE` fallback. Aggregate required Gates with
`STALE` before `FAILED`; explicitly optional Gates are reported but do not change the required-Gate result.

A mapped `STALE` or `NONE` row uses only a Schema-enumerated `invalidation_reason`. A null `execution_ref` is valid only when
the registered runner policy does not declare `execution_ref_required: true`; every other provenance field remains mandatory.
Two canonical empty v2 `NONE` records compare as `NONE`.

For a legacy v1 record, preserve the exact original object and canonical digest under `legacy` with reason
`LEGACY_AGGREGATE_ONLY`, leave `gate_registry`, `gates`, and per-Gate digests empty, and set evidence-bearing records to
`STALE`. Standalone or previous-snapshot parsing may retain v1 for audit, but never place v1 `PASSED` or `FAILED` in the current
Master Card; migrate it first. A current v1 `STALE` remains valid recovery input. Treat every evidence-bearing v1 comparison as
`ALL` even when identical. Permit `NONE` only when both operands are empty v1 `NONE`; every mixed v1/v2 comparison is `ALL`.
Never derive IDs from commands or positions.
Validate with `--candidate-evidence-json`; use
`--previous-candidate-evidence-json <OLD> --candidate-evidence-json <CURRENT>` for read-only invalidation scope,
`--migrate-candidate-evidence` for the read-only legacy projection, and `--candidate-evidence-self-test` for the focused matrix.

A migrated legacy-only v2 audit record may later advance to a fresh per-Gate rerun. The new record must use the same non-null
release task and exact head, a non-regressing Master plan fence, `legacy: null`, and a complete independently valid registry,
source/check provenance, and recomputed input/evidence digests; its aggregate is freshly `PASSED` or `FAILED`. Never copy an
opaque legacy digest. Identity, head, plan-authority, registry, provenance, digest, or monotonic-record failures remain H25.

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

Model routing profile
- Model: <gpt-5.6-sol-or-gpt-5.6-luna>
- Reasoning effort: <high-or-max>
- Service tier: <default-or-priority>
- Selection reason: <owner-default:master-or-owner-default:ordinary-worker-or-owner-default:complex-worker>
- If the launcher cannot honor this exact profile, stop and report; do not substitute it.
- This profile grants no authority and is separate from authorization route/provider.

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
- Commit message: <NON_EMPTY_MESSAGE; NULL_ONLY_FOR_AN_INDEPENDENT_READ_ONLY_REPORT_REVISION>
- Commit only allowed paths.
- Include plan revision <PLAN_REVISION> and dispatch wave <DISPATCH_WAVE> in the task report.
- Report full baseline and result SHAs, changed paths, every check and result, unresolved cross-layer findings, and actual use of
  any external authority.
- Write the compact task card as ACTIVE after verification; after committing, record AWAITING_INTEGRATION and do not rewrite
  the handed-off commit.
```

An `independent-read-only` Task Spec with `commit_message: null` may report `BLOCKED` or be `CANCELLED`; it cannot produce a
successful integrated handoff. For a successful re-review, Master publishes a higher Task Spec revision with a non-empty
attestation commit message and explicitly permits a metadata-only empty commit. The handoff records that Worker SHA and Master
records an attestation commit or an existing tree-equivalence mapping. Do not apply this exception to implementation tasks.

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
- Model profile honored: <MODEL / REASONING_EFFORT / SERVICE_TIER / SELECTION_REASON>
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
- Candidate identity: <RELEASE_TASK_ID + EXACT_RELEASE_HEAD_SHA>
- Previous release-candidate HEAD: <SHA_OR_NONE>
- Previous evidence: <VALID / INVALIDATED / NOT APPLICABLE>
- Previous gate-input digest: <DIGEST_OR_NONE>
- Current gate-input digest: <DIGEST>
- Gate registry digest and membership verified: <DIGEST / YES_OR_NO>
- Per-Gate status/input/evidence digest: <GATE_ID / REVISION / REQUIRED / STATUS / INPUT_DIGEST / EVIDENCE_DIGEST>
- Invalidation reason: <HEAD_CHANGED / INPUT_SOURCE_CHANGED / REGISTRY_AMBIGUOUS / MAPPING_AMBIGUOUS / OTHER_ENUM / NONE>
- Selective mapping: <COMPLETE_AND_VALID / WHOLE_CANDIDATE_STALE_FALLBACK>
- Evidence recomputed from integrated tree: <YES/NO>
- Legacy aggregate audit: <NONE / PRESERVED_DIGEST_AND_STALE>
- Unintegrated Worker-only rework leaves existing candidate evidence unchanged.

Authorization status
- <EXTERNAL CALL / RUN / PUBLISH / DESTRUCTIVE ACTION ACTUALLY USED OR NOT USED>

Release candidate: <NONE/STALE/PASSED/FAILED>.
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
