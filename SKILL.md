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
to bind the task, exact target, controlled input and digest, route/provider, call and cost limits, fresh-run requirement,
prohibited resumptions, and expiry. Keep every required field even when denied by recording `false`, `null`, or `0`; omission
never grants authority. Never store secrets in prompts, task cards, or handoff reports. An authority-boundary change cannot
widen an existing task in place; publish a superseding task with a new authorization envelope.

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
- Every plan entry records `task_spec_revision` and `task_spec_digest`. An affected changed assignment increments its task
  revision; an unchanged active assignment may continue only through an explicit grandfather record in the new plan revision.
- Keep semantic `plan_revision` separate from `record_revision`, which increments on every persisted state update. Preserve the
  state directory as user-owned material whether repository policy tracks it or keeps it local.
- Validate unique task IDs, known dependency references, acyclic dependencies, available worktrees, and no semantic file or
  contract overlap before publishing a batch.
- If tasks have no unresolved dependency and no semantic file or contract overlap, publish them in the same parallel batch.
- `parallel_with` records tasks that may run concurrently.
- `blocked_by` records unresolved dependencies and determines publication order.
- A non-IDLE task card locks only its own worktree; it does not block unrelated worktrees.
- If a target worktree is `ACTIVE`, `AWAITING_INTEGRATION`, or `BLOCKED`, do not reuse it until Master resolves, cancels,
  supersedes, or explicitly takes over the prior task.
- Follow the authoritative Dispatch, Worker, and Master transition tables in [references/methodology.md](references/methodology.md).
  Status-only updates increment persisted `record_revision`, not semantic task or plan revisions. On return to `IDLE`, clear
  active lock fields and preserve the completed identity and outcome under `last_task`.
- If an upstream contract is not frozen, downstream Workers may perform discovery only; implementation remains gated.
- Worktree numbering never determines task order. Dependency edges determine task order.
- A pre-dispatch mismatch removes that task from the current batch; it does not delay independent tasks.

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
- Any integration or rework invalidates all prior release-candidate evidence because `release_head_sha` changes. A
  dependency-plan or derived-output change invalidates the gates whose inputs changed. Master recomputes evidence from the
  integrated tree and reruns the release-candidate and affected gates.
- An accepted Worker handoff may return to `IDLE` even if the global candidate is blocked by another responsibility layer.

## Deliver evidence, not ceremony

For an audit or design, report the verified topology, responsibility map, current risks, proposed state model, adoption order,
and decisions needing user authority. For an operated task, report exact paths, branches, SHAs, changed files, checks and
results, integration mapping, remaining blockers, and which external authorities were or were not used.

Do not impose Master/Platform/Workflow names when a project has better domain terms. Preserve the method's identity,
ownership, handoff, integration, and authorization properties while mapping names to the repository's architecture. Match the
user's language; reference templates preserve semantics and may be translated.
