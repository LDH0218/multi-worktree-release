---
name: multi-worktree-release
description: Audit, design, adopt, or operate a Master/Worker collaboration model across persistent Codex tasks and Git worktrees, including task state cards, handoffs, integration gates, conversation rotation, and default-deny external authorization. Use for multi-thread or multi-worktree delivery governance, not ordinary single-branch coding.
---

# Multi-Worktree Release

Coordinate long-lived Codex tasks and Git worktrees without confusing conversation context, code identity, runtime identity,
or authorization.

## Select the operating mode

- **Audit:** inspect the current repository, worktrees, branches, responsibilities, task state, and release process. Make no
  changes unless the user also requests implementation.
- **Adopt:** establish or revise role boundaries, governance files, task cards, handoff protocol, and release gates.
- **Operate:** publish a task, perform Worker work, integrate a handoff, request rework, cancel/supersede work, or rotate a
  conversation generation.
- **Review:** evaluate an existing method for ambiguity, missing recovery paths, authorization leaks, or unverifiable claims.

Read [references/methodology.md](references/methodology.md) for every Adopt or Review request, and for an Operate request
whose current repository protocol does not already settle the decision. Read [references/templates.md](references/templates.md)
only when producing or validating task cards, dependency and dispatch plans, cross-task messages, exception reports, handoffs,
integration confirmations, or rotation prompts.

Read [references/contracts.schema.json](references/contracts.schema.json) when producing or validating persisted machine
records. After changing this Skill's contracts, or before relying on newly created plan/task/card records, run
`python3 scripts/validate_contracts.py` and resolve every failed invariant.

## Establish repository truth first

1. Read repository-owned agent instructions and the governance files they route to. If present, inspect architecture indexes,
   worktree scope files, task state cards, branch policy, CI, release scripts, and document authority maps.
2. Confirm each relevant absolute worktree path, branch, full HEAD SHA, status, preserved untracked material, and commit graph.
3. Distinguish unintegrated code from patch-equivalent cherry-picks or merges. Do not infer integration from branch-ahead counts.
4. Treat existing dirty or untracked files as user-owned. Do not clean, reset, rebase, merge, or switch branches unless the
   current request and repository rules authorize the exact action.
5. If the actual baseline or task state differs from the handoff, report the difference and stop that execution path.

## Preserve identity and authority boundaries

Keep these identities separate: responsibility role, conversation generation, worktree, branch, frozen commit baseline,
product workflow/module, runtime execution, and external authorization. A conversation label is never a Git ref, runtime ID,
contract revision, release credential, or permission.

External calls, new executions/jobs, production publication, destructive actions, cross-worktree synchronization, and scope
expansion are default-deny. Use the canonical authorization envelope in [references/methodology.md](references/methodology.md)
to bind four independent v2 grants to capability-specific structured targets, controlled input and digest, local/remote
route/provider rules, capability-local call and cost limits, execution-only fresh/resume semantics, and expiry. Keep every
required field even when denied by recording `false`, `null`, or `0`; omission never grants authority, and one grant cannot
lend target or budget fields to another. Persisted v1 flat envelopes remain valid only under their original contract. The
read-only adapter converts only canonical v1 default-deny to a newly hashed v2 default-deny envelope; allowed or ambiguous v1
authority requires a superseding task. Never store secrets in prompts, task cards, or handoff reports. Any authority-boundary
change requires Master to publish a superseding Task Spec and recompute all dependent digests.

## Name persistent conversations

Name each persistent Master or Worker conversation `<project-short-name>｜<responsibility-role>-<conversation-generation>`.
For example: `MWR｜Master-1.0` or `MWR｜授权模型-1.0`.

- Keep the project prefix and long-lived responsibility role stable. Use a specific role rather than a temporary task
  description, and omit the generic `Worker` label when the role is already clear.
- Start the first conversation for a role at `1.0`. When rotating that role to a new conversation, increment the generation
  suffix to `1.1`, `1.2`, and so on while reusing the role's worktree and branch.
- Do not encode mutable status, branch, worktree, task ID, model profile, or authorization in the title.
- Treat the title as a human-readable UI projection only. The persisted Dispatch Plan, Task Spec, and state card remain
  authoritative for identity, state, scope, and authorization.

## Coordinate through the Master

- Use a star topology for executable instructions: Master publishes to Workers; Workers hand off to Master. Worker-to-Worker
  communication may share read-only findings, but may not assign changes, synchronization, or runs.
- When task/thread coordination tools are available, use them to inspect and message existing tasks. Create, fork, move, or
  archive a task only when the user requests that lifecycle action. If no coordination tool exists, return a copyable message.
  Transporting a message never enlarges its authorization.
- Bind each long-lived role to one explicit worktree and branch. A conversation rotation reuses that worktree and branch.
- Freeze every task to a full SHA. Workers do not independently merge, rebase, reset, or synchronize from Master.
- Treat a non-IDLE task card as a lock on that worktree only, not as a global release lock. Identify messages with
  `task_id + task_spec_revision + source_thread_id`; require the same `task_spec_digest` for duplicate delivery. Treat
  `plan_revision` as a fencing token, not part of message identity. Changed executable content for an affected task requires a
  higher task revision. A changed objective, owner, worktree, frozen baseline, or authority boundary requires a superseding
  task rather than an in-place revision.
- Keep `WORKTREE_TASK.md` compact and local when repository policy allows: it is a durable state card, not a copy of the full
  cross-task message. Follow repository policy if the file is tracked or uses another name.

## Dispatch policy

Before publishing implementation work, Master creates a versioned Task Dependency and Dispatch Plan. The plan is a semantic
model, not a required visual diagram; it may be represented as structured text, YAML, a table, or a diagram. Read the detailed
plan validation and state-transition rules in [references/methodology.md](references/methodology.md).

Persist the normative machine record before dispatch. Unless repository governance names another location, use
`<MASTER_WORKTREE>/.codex/multi-worktree-release/dispatch-plan.json` and store complete task specifications under the sibling
`tasks/` directory. Each plan entry carries its absolute `task_spec_path`. Conversation text, tables, and diagrams are
projections, not the recovery source. Write task specs and the plan atomically, verify their digests, and only then publish an
executable message.

- The plan records task IDs, absolute worktrees, `dispatch_status`, `dispatch_wave`, `blocked_by`, and `parallel_with`.
- Treat Task Spec `dependencies.blocked_by` as the canonical static direct graph and Plan `blocked_by` as the exact unresolved
  direct projection. Reject duplicate, self, unknown, cyclic, redundant-transitive, stale, or omitted edges. Derive every wave
  as `1` for a root or `1 + max(parent wave)`, and recompute `blocked_tasks` plus the minimum active `READY`/`PUBLISHED`
  `ready_wave` frontier on every Plan write.
- Require `parallel_with` to be canonical, symmetric, same-wave, transitively incomparable, and free of active-worktree or
  semantic ownership overlap. Never infer parallel eligibility merely from equal waves.
- Every plan entry records `task_spec_revision` and `task_spec_digest`. An affected changed assignment increments its task
  revision; an unchanged active assignment may continue only through an explicit grandfather record in the new plan revision.
- A grandfathered entry preserves its persisted task spec and records that spec's original `task_spec_plan_revision`; it does
  not rewrite the task merely to copy the newer global fence.
- Persist `model_policy` with an `enforced_from_plan_revision` migration fence before requiring profiles. At or after the fence,
  every `NEW` or `REVISE` Task Spec and matching Plan entry uses one identical exact `model_profile`; older digest-preserved
  records below the fence may omit it. Changing a profile requires a higher Task Spec revision/digest. Stop dispatch if the
  launcher cannot honor the persisted profile.
- Use only these owner defaults: Master `gpt-5.6-sol`/`high`/`default` with `owner-default:master`; ordinary Worker
  `gpt-5.6-luna`/`max`/`priority` with `owner-default:ordinary-worker`; complex Worker
  `gpt-5.6-sol`/`high`/`default` with `owner-default:complex-worker`. Model `service_tier` is scheduler metadata, never
  authorization `route`/`provider`, and grants no external call, execution, publication, destructive action, synchronization,
  or scope expansion.
- Keep semantic `plan_revision` separate from `record_revision`, which increments on every persisted state update. Preserve the
  state directory as user-owned material whether repository policy tracks it or keeps it local.
- Validate unique task IDs, known dependency references, acyclic dependencies, available worktrees, and no semantic file or
  contract overlap before publishing a batch.
- If tasks have no unresolved dependency and no semantic file or contract overlap, publish them in the same parallel batch.
- `parallel_with` records validated same-wave concurrency claims.
- Task Spec `blocked_by` determines dependency order; Plan `blocked_by` records only currently unresolved direct dependencies.
- A non-IDLE task card locks only its own worktree; it does not block unrelated worktrees.
- If a target worktree is `ACTIVE`, `AWAITING_INTEGRATION`, or `BLOCKED`, do not reuse it until Master resolves, cancels,
  supersedes, or explicitly takes over the prior task.
- Follow the authoritative Dispatch, Worker, and Master transition tables in [references/methodology.md](references/methodology.md).
  Status-only updates increment persisted `record_revision`, not semantic task or plan revisions. On return to `IDLE`, clear
  active lock fields and preserve the completed identity and outcome under `last_task`.
- If an upstream contract is not frozen, downstream Workers may perform discovery only; implementation remains gated.
- Worktree numbering never determines task order. Dependency edges determine task order.
- A pre-dispatch mismatch removes that task from the current batch; it does not delay independent tasks.

### Validate persisted history

Use previous/current validation when retained snapshots must prove a state change. Pair `--previous-plan` with `--plan`,
`--previous-worker-card` with `--worker-card-json`, and `--previous-master-card` with `--master-card-json`. Previous Worker
input is a complete JSON Worker Card, never an implicit parse of `WORKTREE_TASK.md`. Each supplied snapshot is validated
independently before its transition, and historical Plan validation requires the exact Task Specs referenced by that Plan.

Run cross-record checks separately for the previous set and current set. Current Plan/Worker/Master consistency runs whenever
at least two current records are supplied, even without a previous option. A relationship missing either record is `NOT_RUN`,
not `PASS`; complete history requires all three pairs. Reports distinguish `PASS`, `FAIL`, and `NOT_RUN` and include canonical
snapshot digests. Omitting every previous option preserves single-record output behavior, while `--skip-self-test` never skips
requested snapshot, transition, or cross-record checks. See [references/methodology.md](references/methodology.md) for
monotonic revisions, terminal states, immutable identity/evidence, and diagnostic rules.

## Exceptions and recovery

- If a Worker discovers an unexpected dependency, wrong assignment, wrong scope, wrong worktree, ownership ambiguity, or baseline
  mismatch, it stops implementation, preserves the current state, records `BLOCKED`, and reports to Master.
- Master revises the plan and gates only affected tasks. An in-scope correction uses a higher `task_spec_revision`; a changed
  objective, owner, worktree, frozen baseline, or authority boundary creates a superseding task.
- Do not silently reset, discard, amend, force-push, or reuse an affected worktree. Cancellation and takeover require Master to
  record the evidence and outcome. Read [references/methodology.md](references/methodology.md) for the recovery procedure.

## Execute and integrate

- A Worker changes only owned/allowed paths, runs layer tests plus affected shared-contract tests when available, reviews the
  diff, creates an atomic commit, records `AWAITING_INTEGRATION`, and does not rewrite the handed-off commit.
- Rework creates a successor commit. Do not amend or force-push an immutable handoff.
- Master reviews ownership and the complete patch, records `worker_commit_sha → integrated_as_sha`, and resolves only
  mechanical shared-projection conflicts. Semantic conflicts return to the owning Worker.
- Recompute generated projections, hashes, baselines, indexes, lock files, and cross-layer evidence from the integrated Master
  tree. Never promote a Worker-local derived value as final evidence without that recomputation.
- Run targeted, affected shared, base-relative, and release gates in proportion to the change. Only Master may declare a
  release candidate. Production release remains a separate authorized action.
- Execution order and integration order are independent. Independent Workers may execute in parallel. Master may integrate
  accepted handoffs in any suitable order, but must recheck conflicts and recompute derived outputs after integration.
- Candidate evidence v2 binds effective identity exactly to `release_task_id + release_head_sha`, uses stable explicit Gate and
  check revisions, and recomputes bounded source, input, result, provenance, artifact, and aggregate digests from the integrated
  tree. Plan and registry digests remain audit context, not authority or candidate-key members.
- Any change to the integrated Master tree changes `release_head_sha` and makes every Gate stale; patch or tree equivalence does
  not permit reuse. A Worker-only rework that has not been integrated does not change the candidate. For the same head, a
  dependency-plan, authorization, acceptance, toolchain, Gate-registry, or derived-output change invalidates only Gates whose
  declared semantic inputs changed when the registry and source map are complete. Status-only Plan writes do not invalidate
  unrelated Gates. Missing membership, ambiguous mapping, unverifiable digests/provenance, mixed fences, or partial writes use
  the whole-candidate `STALE` fallback. `STALE` precedes `FAILED`; only all current required Gates passing yields `PASSED`.
- Preserve aggregate-only v1 evidence under the v2 `legacy` audit field with its original digest. Evidence-bearing legacy
  records migrate to `STALE`, empty legacy `NONE` remains `NONE`, and migration never invents Gate identity or promotes an old
  aggregate result. Standalone and historical readers may validate the old syntax, but a current Master Card rejects v1
  `PASSED` or `FAILED`; even byte-identical evidence-bearing v1 comparison returns whole-candidate `ALL`. A current legacy v1
  `STALE` remains readable for deliberate recovery. Comparison returns `NONE` only when both operands are empty v1 `NONE`;
  every mixed v1/v2 comparison returns whole-candidate `ALL`. Master reruns required Gates and
  recomputes final evidence from the integrated tree.
- An accepted Worker handoff may return to `IDLE` even if the global candidate is blocked by another responsibility layer.

## Deliver evidence, not ceremony

For an audit or design, report the verified topology, responsibility map, current risks, proposed state model, adoption order,
and decisions needing user authority. For an operated task, report exact paths, branches, SHAs, changed files, checks and
results, integration mapping, remaining blockers, and which external authorities were or were not used.

Do not impose Master/Platform/Workflow names when a project has better domain terms. Preserve the method's identity,
ownership, handoff, integration, and authorization properties while mapping names to the repository's architecture. Match the
user's language; reference templates preserve semantics and may be translated.
