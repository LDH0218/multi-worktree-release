---
name: multi-worktree-release
description: Govern persistent Master/Worker tasks across Git worktrees, including handoffs, recovery, and release gates. Use for collaboration governance, not unrelated coding; classify eligible delivery as FAST first.
---

# Multi-Worktree Release

Coordinate persistent roles without confusing conversation context, Git identity, runtime execution,
or authorization. Map roles to actual ownership boundaries, not a desired agent count. Audit and review
requests are read-only unless implementation is requested.

## Choose the smallest applicable path

Classify **FAST** before creating a Dispatch Plan or starting Master/Worker setup. All conditions must hold:

- One current task and work directory can complete the change, without an independent parallel
  responsibility or extra worktree.
- The relevant Card is absent or `IDLE`; there is no active Dispatch assignment or competing durable
  role binding for the current worktree/role. Any non-IDLE Card makes FAST ineligible.
- Every modified path is clearly owned by the current role. Master must not edit Worker-owned business
  paths from its worktree. Unknown or ambiguous ownership requires STRICT.
- No governance, protocol, Schema, state-machine, authorization, security, persistence, release,
  irreversible migration, production or long-recovery impact.
- Verification is clear and bounded locally; every external write has separate explicit authorization.

FAST stays in the current task/worktree: preserve user material, inspect the baseline, make the scoped
change, run proportional local checks, review the diff, commit when repository policy calls for it,
and report. Create no Plan, Task Spec, Worker/Master Card, extra task/worktree, cycle fence, adoption
record or Operation Receipt. These instructions suffice for eligible FAST work; do not load STRICT or
release material merely to perform it.

Enter existing **ISOLATED / STRICT** before risky action for parallel work, any excluded impact,
material scope expansion, more than one local correction after failed acceptance, or uncertainty.
Do not create records as a workaround for failed FAST eligibility; follow STRICT or stop.

## Read only the applicable procedure

Select the relevant references below, then read each selected instruction completely before acting.
Follow references required by that procedure when applicable; do not load every linked document.
Progressive loading changes reading cost, not prerequisites, validation or stop conditions.

| Current operation | Required procedure |
| --- | --- |
| STRICT publication, execution, handoff, integration or Worker return to IDLE | [Task Lifecycle](references/task-lifecycle-sop.md) |
| Candidate/Gate certification, publication, closeout or rollover | [Release](references/release-sop.md) |
| Assignment mismatch, blocker, rework, cancellation or supersession | [Exception and Recovery](references/exception-recovery-sop.md) |
| Create, rotate, recover or archive a persistent conversation | [Conversation Rotation](references/conversation-rotation-sop.md), sole conversation lifecycle authority |
| Audit actual execution evidence | [SOP Compliance Audit](references/sop-compliance-audit-sop.md), plus the procedure being audited |
| Adopt MWR or revise project ownership topology | [Project Adoption](references/project-adoption-sop.md) |
| Classify, review or change SOP meaning and batch compatibility | [SOP Change Governance](references/sop-change-governance-sop.md) |
| Retain, retire or consider deleting worktrees, conversations or records | [Retention and Retirement](references/retention-retirement-sop.md) |

- Read [methodology](references/methodology.md) for protocol design/review, adoption, or an operation
  not settled by repository protocol and its applicable SOP. It retains detailed identity, dispatch,
  authorization, model-policy, state-transition, candidate and recovery rules.
- Read [templates](references/templates.md) when producing or validating assignment messages, Plans,
  Cards, handoffs, exceptions, integration confirmations or rotation prompts.
- Read [contracts.schema.json](references/contracts.schema.json) when producing or validating persisted
  machine records. Schema and persisted records remain machine authority; prose cannot replace evidence.
- Use [Operator Execution Map](references/operator-execution-map.md) to resolve commands or operation
  order. It is a lookup, not an additional requirement to read all eight SOPs.

## Keep the safety boundaries

- Establish relevant absolute worktree, branch, full HEAD, status, preserved material, ownership and
  record identities before mutation. Investigate ancestry and patch-equivalent integrations; branch-ahead
  counts and chat claims alone do not prove integration. Preserve dirty/untracked user material.
- External calls, executions/jobs, publication/push, destructive actions, synchronization and scope
  expansion are default-deny. Verify the exact current grant immediately before use; local tests grant
  no external execution authority. Never store secrets in messages or records. Model profiles are not grants.
- Master owns planning, assignment publication, independent handoff review, integration and release
  decisions. Workers change only assigned paths and their Card; no independent merge, rebase, reset,
  synchronization, push, publication or widened scope. Worker-to-Worker messages share evidence, not execution.
- Persist complete Task Specs and the Plan atomically, verify digests, then dispatch. The default Plan
  is `<MASTER_WORKTREE>/.codex/multi-worktree-release/dispatch-plan.json`, with sibling `tasks/` specs.
  Preserve repository tracking/ignore policy. Canonical `WORKTREE_TASK.json` is Worker machine evidence;
  `WORKTREE_TASK.md` is only a human projection.
- Freeze assignments to full SHAs. Message identity is `task_id + task_spec_revision + source_thread_id`;
  duplicates must also match `task_spec_digest`. In-scope executable changes require a higher task
  revision; objective, owner, worktree, baseline or authority changes require a superseding task.
- One persistent role has one current conversation and one retained worktree/branch pair. Master alone
  owns binding and lifecycle decisions. Use available task tools to inspect/message existing tasks;
  create, fork, move or archive only when the user requests that lifecycle action. Without coordination
  tools provide a copyable message; transport never grants authority.
- Name conversations `<responsibility-role>-<conversation-generation>` (for example `Master-1.0`),
  without a project prefix by default. Rotation preserves task and Git identity; require successor
  verification and explicit confirmation before predecessor archive. Task completion does not retire
  conversations/worktrees. Deletion always needs separate explicit authority.
- Handed-off commits are immutable; rework uses successor commits. Master reviews the full patch and
  records Worker-to-integrated SHA mappings. Regenerate final evidence from the integrated tree;
  semantic conflicts return to their owner. Only Master declares a release candidate.
- Preserve `integration → fresh Candidate/Gates → separate publication decision → closeout → rollover`.
  Changed integrated HEAD invalidates Gate evidence; tests or closeout never grant publication.
  Use existing writers and the state-root lock for cooperative writes, including Master Plan/Card
  updates. Never bypass checks or replace receipt-backed forward recovery with rollback.
- Mismatches stop the affected path and preserve evidence. Missing proof is `NOT_PROVEN`, not success.
  A non-IDLE Worker locks its own worktree, not unrelated work; accepted integration may return that
  Worker to IDLE while another responsibility blocks the release.

v1 remains authoritative. Authorization envelope v2 and Candidate evidence schema v2 are formal parts
of current STRICT behavior; protocol v2 adoption/binding prototypes remain experimental and unrouted.
This entrypoint changes neither protocol nor model configuration.

## Validation and delivery

Run `python3 scripts/validate_contracts.py` after contract changes and before relying on newly created
Plan/Task/Card records. Its `--repo-root` means Skill source root, not audited project root.
Writer `--repo-root` means business Master root; optional `--skill-root` defaults to the installed
scripts directory's parent. Commands and historical pairs remain in applicable references.

Honor Task Spec acceptance and release gates; run proportional checks for ordinary delivery. Repository
unit tests use `PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py'`.
Report paths, SHAs, verification, preserved material, unresolved blockers and actual authority used.
For audits report evidence and decisions needed, not invented completion or permission.
