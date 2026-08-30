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

Before publishing a wave, Master validates that task IDs are unique, every dependency reference is known, no dependency cycle
exists, every target worktree is available and matches its task card, and semantic file or contract ownership does not overlap.
Mechanical overlap in generated outputs is allowed only when Master owns regeneration from the integrated sources. Task Spec
`dependencies.blocked_by` is the static direct graph; Plan `blocked_by` is its exact unresolved live projection. Master rejects
duplicate, self, unknown, redundant-transitive, cyclic, and dependency/parallel-conflict edges, requires symmetric
`parallel_with`, and derives `dispatch_wave` as `1` for roots or `1 + max(parent wave)` otherwise. It recomputes
`blocked_tasks` from `GATED`/`BLOCKED` status and `ready_wave` as the minimum `READY`/`PUBLISHED` wave. It also verifies every
persisted task-spec path and digest, the plan digest, and the completion of each atomic replacement before sending a task
message. Full graph rules and complexity are normative in [dispatch-graph-invariants.md](../design/dispatch-graph-invariants.md).

The validator applies full graph semantics to every current nonterminal task and every task covered by the model-policy fence.
Legacy terminal entries below that fence remain immutable digest-checked evidence and may act only as trusted topological
boundaries for newly enforced descendants. This compatibility rule prevents retroactive rewriting of completed evidence; it
does not permit a new or active task to bypass cycle, reduction, wave, blocker, frontier, or parallel-conflict validation.

Tasks with no unresolved blockers and no semantic overlap may be published in the same wave. A task with unresolved blockers
remains `GATED` and is not published. A worktree preflight failure removes only that task from the current wave; it does not
delay independent tasks.

### Model routing policy and migration fence

`model_policy` and `model_profile` are optional only for backward compatibility. A Plan without `model_policy` remains a
legacy record and may not contain per-task profiles. Once Master adds a policy, `enforced_from_plan_revision` is the migration
fence: every `NEW` or `REVISE` Task Spec bound at or after that fence, and its matching Dispatch entry, must persist the same
exact profile. Older digest-preserved `GRANDFATHER` and terminal evidence below the fence may omit it and must not be rewritten.
Adding the policy or changing a profile is executable semantic content: increment `plan_revision`; a changed task profile also
requires a higher `task_spec_revision` and a new digest. Unsupported model/reasoning/tier combinations or a Plan/Task Spec
profile mismatch stop dispatch.

Owner defaults are exact: Master uses `gpt-5.6-sol` / `high` / `default` with `owner-default:master`; an ordinary Worker uses
`gpt-5.6-luna` / `max` / `priority` with `owner-default:ordinary-worker`; a complex Worker uses `gpt-5.6-sol` / `high` /
`default` with `owner-default:complex-worker`. Master classifies each Worker task as ordinary or complex before publication.
The launcher must honor all three persisted routing fields exactly; if it cannot, dispatch stops instead of substituting a
model, effort, or tier.

The model `service_tier` is scheduler metadata only. It is never authorization `route` or `provider`, and it grants no external
call, execution creation, publication, destructive operation, synchronization, or scope expansion. Those capabilities remain
governed solely by the complete default-deny authorization envelope and its independent digest.

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
  schema_version: 2
  capabilities:
    external_call:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
    create_execution:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
      fresh_execution_required: true
      resume_execution_id: null
    publish:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
    destructive_operation:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
  controlled_input: null
  controlled_input_digest: null
  expires_at: null
  envelope_digest: <computed-sha256-digest>
```

Authorization v2 has exactly four independent grants. Each grant has `allowed`, `target`, `route`, `provider`, `max_calls`,
`max_cost`, and `cost_unit`; only `create_execution` also has `fresh_execution_required` and `resume_execution_id`. A denied
grant uses exactly the values above. It cannot retain a target, route, provider, call or cost budget. Grants cannot borrow any
field or budget from another capability.

An allowed target is an exact object `{kind, id, transport, scope}`. `id` is non-empty; `transport` is `local` or `remote`;
`scope` is exactly `{paths, refs}` with unique non-empty strings in canonical UTF-8 byte order and no wildcard. External calls
use `kind: service` and `transport: remote`; executions use `kind: execution`; publication uses `kind: publication`; destructive
operations use `kind: resource`. Publication and destructive targets require at least one path or ref. Remote targets require
non-empty route and provider; local targets require both to be null. External-call and execution grants require
`max_calls >= 1`; publication and destructive grants require `max_calls: 0`. `max_cost` is a non-negative integer count. Zero
cost requires a null unit; positive cost requires the exact non-empty atomic unit, such as `USD-cent` or a provider credit.

Fresh/resume semantics exist only in `create_execution`. `fresh_execution_required: true` requires
`resume_execution_id: null`; `false` requires one exact non-empty ID and authorizes only that execution. Any allowed grant
requires non-null canonical `controlled_input`, its matching digest, and a future RFC 3339 `expires_at`. An all-denied envelope
requires those three fields to be null. Secrets are never valid controlled inputs or state-card values.

Historical validation still parses an expired envelope and verifies its shape and digests as immutable evidence, but never
treats it as executable authority. Current nonterminal Task Specs and Worker locks compare expiry with the current time;
terminal and previous snapshots use structural/digest validation so retained history remains verifiable after time passes.

Digests use `sha256:<64-lowercase-hex>`. Structured digest inputs use only null, booleans, integers, strings, arrays, and objects
with string keys; floating-point values are invalid and decimals use strings or integer units. Hash UTF-8 JSON with object keys
recursively sorted, arrays kept in order, strings preserved exactly as stored, and no insignificant whitespace. For files or
byte streams, hash the exact bytes. Compute `envelope_digest` over the authorization object with `envelope_digest` itself set
to `null`. The digest is an integrity check, not a grant of authority. Any change to the authorization envelope is an
authority-boundary change and requires a superseding task rather than an in-place revision.

Persisted schema-version-1 envelopes remain valid under their original flat contract; this is grandfather validation, not a
reinterpretation as v2. The read-only v1 adapter first validates the complete source and never mutates it. It converts only the
canonical all-denied v1 envelope to canonical all-denied v2 and computes a new v2 digest. It rejects multiple allowed v1
capabilities, any allowed string target whose structured kind, transport, and scope cannot be proven, and noncanonical denied
state. The old digest never becomes a v2 digest. Migrating an assignment is an authority-boundary change: Master publishes a
superseding Task Spec and recomputes the Task Spec, Plan authorization, acceptance, and evidence digests before dispatch.

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
model_profile:
  model: <gpt-5.6-sol-or-gpt-5.6-luna>
  reasoning_effort: <high-or-max>
  service_tier: <default-or-priority>
  selection_reason: <owner-default:master-or-owner-default:ordinary-worker-or-owner-default:complex-worker>
authorization:
  schema_version: 2
  capabilities:
    external_call:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
    create_execution:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
      fresh_execution_required: true
      resume_execution_id: null
    publish:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
    destructive_operation:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
  controlled_input: null
  controlled_input_digest: null
  expires_at: null
  envelope_digest: <computed-sha256-digest>
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
  schema_version: 2
  capabilities:
    external_call:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
    create_execution:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
      fresh_execution_required: true
      resume_execution_id: null
    publish:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
    destructive_operation:
      allowed: false
      target: null
      route: null
      provider: null
      max_calls: 0
      max_cost: 0
      cost_unit: null
  controlled_input: null
  controlled_input_digest: null
  expires_at: null
  envelope_digest: <computed-sha256-digest>
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
  schema_version: 2
  release_task_id: <master-release-task-id-or-null>
  release_head_sha: <full-sha-or-null>
  plan_revision: <positive-integer-or-null>
  plan_digest: <sha256-digest-or-null>
  gate_registry_digest: <sha256-digest-or-null>
  gate_registry:
    - gate_id: <stable-id>
      gate_revision: <positive-integer>
      required: <true-or-false>
      gate_definition: <bounded-canonical-value>
      gate_definition_digest: <sha256-digest>
      runner_policy: <bounded-canonical-value>
      runner_policy_digest: <sha256-digest>
      checks:
        - check_id: <stable-id>
          check_revision: <positive-integer>
          command_spec: <bounded-canonical-value>
          command_spec_digest: <sha256-digest>
          runner_policy: <bounded-canonical-value>
          runner_policy_digest: <sha256-digest>
          input_source_ids: [<stable-source-id>]
  gate_input_digest: <sha256-digest-or-null>
  status: NONE | STALE | PASSED | FAILED
  legacy: <null-or-preserved-v1-audit>
  gates:
    - gate_id: <stable-id>
      gate_revision: <positive-integer>
      required: <true-or-false>
      status: NONE | STALE | PASSED | FAILED
      input_digest: <sha256-digest-or-null>
      evidence_digest: <sha256-digest-or-null>
      input_sources: [<bounded-source-manifest>]
      checks: [<current-check-evidence>]
      invalidation_reason: <reason-or-null>
blocker: <text-or-null>
```

### Per-Gate candidate evidence

Candidate evidence v2 is self-contained: its embedded `gate_registry` is the exact bounded registry used to validate Gate and
check membership, revisions, requiredness, command specifications, runner policies, and source dependencies. The effective
candidate identity is exactly `(release_task_id, release_head_sha)`. `plan_revision`, `plan_digest`, and
`gate_registry_digest` are audit/fencing context, not extra candidate-key members; a status-only Plan write does not invalidate
evidence merely because those audit values changed.

Normalize Gate, check, source, source-ID, and artifact arrays by their stable IDs or locators before hashing. Stable IDs use
lowercase kebab case and are never inferred from list position, command text, timestamps, branches, or content digests. Rehash
every persisted `gate_definition`, `command_spec`, and `runner_policy`, then recompute each check `input_digest`, Gate
`input_digest`, compatibility `gate_input_digest`, check `evidence_digest`, and Gate `evidence_digest` from the canonical
envelopes defined by the schema and validator. Current `PASS` or `FAIL` evidence requires exact input binding, bounded command
description, execution reference, exit-code predicate, output digests, artifact digests, runner digest, and observation time.
Infrastructure errors and unverifiable provenance are `STALE`, never `FAIL` or `PASS`.

A changed `release_head_sha` invalidates every Gate without tree- or patch-equivalence reuse. For the same head, compare only
the semantic source manifests each Gate declares. A changed acceptance, authorization, Task Spec, registry, toolchain, or
projection source stales its dependent Gates when the embedded registry and mapping are complete. Do not invalidate unrelated
Gates solely for `record_revision`, `updated_at`, dispatch status, `plan_revision`, or the whole `plan_digest`. If Gate
membership, requiredness, source mapping, digest recomputation, provenance, revision fencing, or atomic persistence cannot be
proved, clear asserted current evidence and persist all known Gate rows as `STALE` with a whole-candidate reason and no asserted
registry or compatibility digest.

Aggregate required Gates in this order: missing/`NONE`/`STALE` first, then valid `FAILED`, then all valid `PASSED`. Thus
`STALE` precedes `FAILED`. An explicitly `required: false` Gate is reported but does not change the required-Gate result;
missing or unknown requiredness is stale. An empty required set cannot pass.

Aggregate v1 evidence remains valid as immutable legacy syntax. Migrate it with
`--candidate-evidence-json <PATH> --migrate-candidate-evidence`; preserve the exact original object plus its canonical digest
under `legacy`, synthesize no Gate/check identity, and produce `STALE` whenever the old record contains evidence. An empty v1
`NONE` record remains `NONE`. This read compatibility is not current release authority: a current Master Card rejects v1
`PASSED` and `FAILED`, while a previous historical Master snapshot may retain them for exact migration audit and a current v1
`STALE` remains readable for deliberate recovery. Comparing any evidence-bearing v1 record returns whole-candidate `ALL`,
even when both objects are byte-identical; only an empty v1 `NONE` may return `NONE`. Applying migration to an already migrated
v2 record is idempotent. Validate standalone fixtures with `--candidate-evidence-json <PATH>`, compare old/current manifests with
`--previous-candidate-evidence-json <OLD> --candidate-evidence-json <CURRENT>` to obtain `NONE`, `AFFECTED`, or `ALL`, and run
the targeted matrix with `--candidate-evidence-self-test`.

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
terminal history, including when the revised task is carried unchanged into later Plans through `GRANDFATHER`. Plan/Master
consistency validates current-revision handoffs against the current entry and permits that older handoff only when its source,
role, baseline, authorization, digest relationship, and older Plan fence prove the original revision boundary.

Plan/Worker, Plan/Master, and Worker/Master consistency is always checked for every supplied pair of current records, including
current-only invocations. Historical mode additionally checks the previous generation separately and never mixes generations.
Missing relationships report `NOT_RUN` internally. Historical output distinguishes `PASS`, `FAIL`, and `NOT_RUN` and includes
canonical snapshot digests. Supplying only one previous/current pair is valid partial history; a complete release-history gate
requires all three pairs and no `NOT_RUN` result. Omitting every previous option retains single-record validation and output
behavior, but does not skip available current cross-record checks. `--skip-self-test` does not disable requested snapshot,
transition, or cross-record checks.

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
`release_head_sha` and their recomputed per-Gate input/evidence digests. Any integrated-tree change invalidates every Gate
because the candidate SHA changes. A Worker-only rework that has not been integrated leaves the candidate unchanged. For the
same head, a dependency-plan, authorization, acceptance, toolchain, registry, or regenerated-projection change invalidates
only Gates whose declared semantic sources changed when the registry and dependency map are complete; bookkeeping-only Plan
writes do not invalidate Gates. Any ambiguity uses the whole-candidate `STALE` fallback. Master reruns stale required Gates and
recomputes the compatibility `gate_input_digest` from the integrated tree before candidate approval.

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
