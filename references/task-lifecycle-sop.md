# Task Lifecycle SOP

This is the operator runbook for one task from FAST/STRICT classification through delivery and, for a
strict task, accepted Worker return to `IDLE`. It is a human procedure over the existing Dispatch Plan,
Task Spec, Worker/Master Cards, Git evidence, Schema, validator, and authorization envelope. It adds no
machine state, role registry, contract field, or authority. For release work, continue with the
[Release SOP](release-sop.md). For failures, use the [Exception and Recovery SOP](exception-recovery-sop.md).
Persistent conversation lifecycle remains solely governed by the
[Conversation Rotation SOP](conversation-rotation-sop.md).

## Operating principles

- Master owns STRICT classification decisions, Plan and Task Spec publication, Dispatch status, review,
  integration, and release readiness. The bound Worker owns only its allowed implementation and Worker
  Card transitions.
- Keep responsibility role, conversation generation, worktree, branch, frozen baseline, product
  workflow, runtime execution, and external authorization distinct. A title, model choice, or message
  never substitutes for a persisted identity or grant.
- `NOT_PROVEN` is a human evidence result: if a required fact, digest, provenance item, or check is
  missing, ambiguous, stale, or unverifiable, stop the affected decision and report `NOT_PROVEN`; do
  not infer success from silence, branch-ahead counts, a chat statement, or a partial record.
- Preserve dirty and untracked material. No Worker independently synchronizes, merges, rebases, resets,
  pushes, publishes, deletes, or expands scope.

## 1. Classify the work

Classify FAST before creating a Dispatch Plan or entering heavy coordination.

| Path | Use when | Required result |
| --- | --- | --- |
| FAST | One current task and work directory are sufficient; the relevant Worker Card is absent or `IDLE`; there is no active Dispatch assignment or competing durable role binding; ownership is clear; the change is bounded, low-risk, locally verifiable, and has no irreversible migration, permission-boundary change, production operation, formal release certification or complex recovery. File category alone does not force STRICT. | Work in the current directory, preserve user material, run bounded checks, review the diff, and commit when repository workflow calls for it. Create no Plan, Task Spec, Card, extra worktree, cycle fence, adoption record, or Operation Receipt. |
| STRICT | Any FAST condition is false, or the work has parallel responsibility, an extra worktree, permission-boundary change, formal release certification, production operation, irreversible migration or complex recovery. Repeated bounded corrections alone do not require STRICT. | Master performs the read-only discovery gate, publishes a versioned Task Spec/Plan, and uses the lifecycle below. |

FAST never grants external-call, execution, publication, destructive, synchronization, or scope-expansion
authority. A separate explicit authorization is required immediately before any such external mutation;
local tests do not grant `create_execution`. A non-`IDLE` Worker Card, active assignment, or competing writer
requires reconciliation before FAST even if the requested change appears small.

Master takeover: stop the prior Worker, inspect HEAD/status, preserve dirty material and immutable handoffs,
and transfer ownership explicitly. Reconcile active strict assignments through cancellation or supersession;
never run two writers against the same paths. Multiple local debugging corrections are allowed while risk
and scope remain bounded.

## 2. STRICT preflight and publication

Master completes these checks before publishing implementation work:

1. Read repository instructions and the routed methodology, templates, Schema, validator, and SOPs that
   apply. Inventory roles, visible conversations, worktrees, branches, Cards, current Plan/Task Specs,
   handoffs, dependencies, dirty/untracked material, and release gates.
2. Verify the exact absolute worktree, branch, full `HEAD`, status, preserved material, role/generation
   binding, and ownership. A wrong path, branch, baseline, role, duplicate binding, or unexpected dirty
   path stops that assignment.
   For a newly created conversation, first complete the
   [conversation/worktree binding check](conversation-rotation-sop.md#conversation-creation-and-worktree-binding).
   A read-only bootstrap may establish its actual directory before assignment; publish no executable
   Task Spec or message based only on a title, prompt path, pending client ID or assumed worktree location.
3. Build the dependency and ownership view. Reject unknown, cyclic, redundant, stale, or asymmetric
   edges; semantic file/contract overlap; unavailable worktrees; and assignments whose current Card or
   baseline does not match. Independent, non-overlapping ready tasks may share a wave.
4. Persist each complete Task Spec and then the complete Dispatch Plan atomically. Verify every
   `task_spec_digest`, authorization digest, acceptance digest, Plan digest, path, wave, and fence before
   sending the executable message. A changed objective, owner, worktree, frozen baseline, or authority
   boundary requires a new task with `supersedes_task_id`; an in-scope correction uses a higher task
   revision and new digest.
5. Publish only through Master. A message identifies `task_id + task_spec_revision + source_thread_id`;
   `task_spec_digest` proves content equality and `plan_revision` is the fencing token. A stale or
   mismatched message is rejected.

The minimum strict assignment evidence is:

- task identity, revision, digest, absolute Task Spec path, Plan revision, dispatch wave, issuer, issued
  time, role/generation, worktree, branch, and full frozen baseline;
- objective, allowed and forbidden repository-relative paths, inputs, outputs, dependencies, acceptance
  checks, stop conditions, and any required Master regeneration;
- the exact persisted model profile and complete authorization envelope; and
- verified current-state facts, including preserved dirty/untracked material and any relevant handoff or
  blocker.

### Model profile

Projects choose model, effort and service tier; use the persisted profile exactly when a policy exists.
The Skill imposes no model whitelist. Plan/Task profiles must equal project `model_policy.owner_defaults`,
and the launcher must support the requested values. `service_tier` grants no external authority.
Existing assignments retain their recorded profiles until legally revised.

For new tasks/conversations without an explicit user/project model choice, all roles default to
`gpt-6.1-sol`. A default is not a whitelist and does not rewrite historical profiles. If an existing
Plan policy differs from a newly approved project default, Master must publish the normal versioned
policy/task update before new executable dispatch; never change old digests in place.

Before creating or resuming a conversation for executable work:

1. Resolve model, effort and service tier from the applicable project policy. Pass the model and effort
   explicitly through supported launcher parameters (for Codex task tools, `model` and `thinking`), not
   just in the prompt. Do not rely on application defaults or silently substitute unsupported values.
2. Before dispatch, verify model/effort from launcher acknowledgement or observable conversation settings.
   A Task Spec, requested argument, title or Worker self-report alone is not proof of runtime settings.
3. Set/verify the requested tier through a supported control or observable runtime setting. If the tool
   has no tier parameter, do not invent one or claim `priority` was applied. Unverified required settings
   are `NOT_PROVEN`: stop executable dispatch for that binding and report the missing control/evidence.
   This checks requested settings, not an unobservable backend effective scheduling tier.

Reuse existing conversations only after the same configuration check. Do not create replacements,
archive conversations or alter worktree bindings merely to correct model settings without lifecycle authority.

### Authorization gate

Every executable Task Spec and non-`IDLE` Worker Card carries the complete schema-version-2 envelope
with four independent grants: `external_call`, `create_execution`, `publish`, and
`destructive_operation`. A denied grant explicitly uses `allowed: false`, `target/route/provider: null`,
zero call and cost budgets, and null `cost_unit`; the denied execution grant additionally uses
`fresh_execution_required: true` and `resume_execution_id: null`. No grant borrows fields or budget from
another, and no authority is inherited from a predecessor, model, commit, or message. Missing fields,
secrets, an invalid digest, an expired current grant, or an ambiguous target is `NOT_PROVEN` and stops
the operation.

Older persisted schema-version-1 envelopes remain valid only under their original contract; do not
reinterpret or migrate them without Master publishing a superseding task.

## 3. Worker bootstrap and execution

The bound Worker performs a read-only bootstrap before changing files:

1. Confirm the absolute worktree, branch, full `HEAD`, status, preserved material, role/generation,
   Plan path/revision/digest, Task Spec path/revision/digest, dispatch wave, baseline, allowed paths,
   model profile, and authorization envelope.
2. Confirm that the current Card is the expected record and that its state/record revision maps to the
   current Dispatch entry. A mismatch is a stop, not a request to synchronize from Master.
3. For a valid initial assignment, use `worker_card_sidecar.py --advance ACTIVE` with the Plan,
   Master Card and task ID. The tool derives the complete Card from Task Spec and prior history,
   checks the actual branch/HEAD/clean state, and uses the existing atomic sidecar transition.
   No manually assembled Card is required for normal activation. The JSON sidecar is the machine record.
4. Change only allowed paths. Run the owned-layer checks and affected shared-contract checks named by
   the Task Spec. Preserve unrelated user changes and untracked material.
5. Review the complete diff and create one scoped commit. The commit must use the Task Spec's non-empty
   message for an implementation task; a handed-off commit is immutable. Rework creates a successor
   commit and never amends or force-pushes the original.
6. Use `--advance AWAITING_INTEGRATION --worker-commit <FULL_SHA>` after checks and commit.
   The tool verifies the current committed HEAD, derives assignment fields and preserves history.
   Include those identities with actual check results in the structured handoff; the tool does not
   invent acceptance results or grant integration authority.

The minimum Worker evidence is:

- task/Plan identity, worktree, branch, full baseline and result SHA;
- exact changed paths and a statement that forbidden paths were untouched;
- commit SHA and subject, test/check commands with results and output evidence, and any preserved
  material or unresolved cross-layer finding; and
- actual use of external, execution, publication, or destructive authority, including an explicit
  `none` when no grant was used.

## 4. Master review, integration, and Worker closeout

Master independently reviews every handoff:

1. Validate the complete current Plan, Task Spec, Card, handoff identity, digests, model, authorization,
   baseline, ownership, ancestry, and full patch. A patch-equivalent prior change is evidence to
   investigate, not permission to ignore the Worker SHA.
2. Reject or return for rework when any acceptance result is `NOT_PROVEN`, the commit is unreachable or
   rewritten, scope/ownership is wrong, the baseline is stale, or a required check/provenance item is
   missing. Preserve the original handoff and issue a higher Task Spec revision for in-scope rework.
3. Integrate only the intended Worker change into the Master tree. Master may regenerate mechanical
   projections from their sources, but semantic conflicts return to the owning Worker or a verified Master takeover. Record the
   mapping `worker_commit_sha → integrated_as_sha` and recompute affected derived evidence from the
   integrated tree.
4. After accepted integration, Master records the handoff as `INTEGRATED` and sends the exact mapping
   and release-head context to the Worker. The Worker uses `--advance IDLE` to derive the accepted
   terminal Card from Master evidence, preserving `task_id`, Task Spec revision/digest, outcome, Worker SHA,
   and integrated SHA under `last_task`, while clearing active identity, scope, authorization, blocker,
   and lock fields. If another layer blocks the release candidate, an accepted Worker may still return
   to `IDLE`.

The relevant state ownership is fixed: only Master changes Dispatch status; only the bound Worker changes
its Card except a recorded Master takeover; `ACTIVE` and `AWAITING_INTEGRATION` map to Dispatch
`PUBLISHED`; `BLOCKED` maps to `BLOCKED`; and `IDLE` maps to no current task or a terminal Dispatch
entry. Any mismatch blocks further execution until Master reconciles it.

Generated normal transitions use the same state-root lock, identity/digest validation and atomic
write as explicit `--transition --card-json`. Repeated identical transitions are idempotent.
Blocker details and exceptional recovery still use the complete explicit Card; Plan/Task publication
and Master review remain separate. An automatic Card command does not stop a running conversation.

## Stop-and-preserve checklist

Stop the affected path, preserve `HEAD`, status, diffs, untracked material, records, and commits, and
report to Master for any of the following:

- wrong assignment, worktree, branch, baseline, role binding, or Plan/task fence;
- dirty or untracked material that is unexpected, overlapping, or not clearly owned;
- duplicate visible conversation or competing role/worktree binding;
- missing, conflicting, stale, malformed, or noncanonical Card, Plan, Task Spec, handoff, digest, model,
  or authorization evidence;
- unexpected dependency, ownership ambiguity, semantic overlap, or scope expansion;
- unsupported model profile or any attempted external, execution, publication, destructive, synchronization,
  or push action without a current explicit grant; or
- a change in risk, scope, dependencies or authorization that the current assignment does not cover,
  need to modify a forbidden path, or missing required evidence. Rework count alone is not a stop condition;
  an explicitly agreed task budget or stopping condition still applies.

The [Exception and Recovery SOP](exception-recovery-sop.md) defines the decision after the stop. Never
turn a failed check into a new machine state or silently resolve it from conversation memory.
