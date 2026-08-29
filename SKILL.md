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
only when producing or validating task cards, cross-task messages, handoffs, integration confirmations, or rotation prompts.

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
expansion are default-deny. Require a current explicit authorization envelope binding the task, exact target, controlled input
and digest, route/provider, limits, fresh-run requirement, prohibited resumptions, and expiry. Never store secrets in prompts,
task cards, or handoff reports.

## Coordinate through the Master

- Use a star topology for executable instructions: Master publishes to Workers; Workers hand off to Master. Worker-to-Worker
  communication may share read-only findings, but may not assign changes, synchronization, or runs.
- When task/thread coordination tools are available, use them to inspect and message existing tasks. Create, fork, move, or
  archive a task only when the user requests that lifecycle action. If no coordination tool exists, return a copyable message.
  Transporting a message never enlarges its authorization.
- Bind each long-lived role to one explicit worktree and branch. A conversation rotation reuses that worktree and branch.
- Freeze every task to a full SHA. Workers do not independently merge, rebase, reset, or synchronize from Master.
- Treat a non-IDLE task card as a worktree lock. Identify messages with `task_id + task_spec_revision + source_thread_id`;
  duplicate messages are idempotent, older revisions are rejected, and changed scope requires a new revision or supersession.
- Keep `WORKTREE_TASK.md` compact and local when repository policy allows: it is a durable state card, not a copy of the full
  cross-task message. Follow repository policy if the file is tracked or uses another name.

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
- An accepted Worker handoff may return to `IDLE` even if the global candidate is blocked by another responsibility layer.

## Deliver evidence, not ceremony

For an audit or design, report the verified topology, responsibility map, current risks, proposed state model, adoption order,
and decisions needing user authority. For an operated task, report exact paths, branches, SHAs, changed files, checks and
results, integration mapping, remaining blockers, and which external authorities were or were not used.

Do not impose Master/Platform/Workflow names when a project has better domain terms. Preserve the method's identity,
ownership, handoff, integration, and authorization properties while mapping names to the repository's architecture. Match the
user's language; reference templates preserve semantics and may be translated.
