# Project Adoption SOP

This is the human procedure for adopting the Multi-Worktree Release method in this repository or in
another project. It covers discovery, role and worktree mapping, FAST/STRICT routing, state-root use,
pilot evidence, version pinning, failure exit, and rollback. It adds no machine state, role registry,
authoritative adoption record, service, Protocol v2 enablement, or runtime authority. Existing Plan,
Task Spec, Worker/Master Card, Git, Schema, and release records remain the source of truth.

The MWR repository's own maintenance follows the existing [Task Lifecycle SOP](task-lifecycle-sop.md),
[Release SOP](release-sop.md), [Exception and Recovery SOP](exception-recovery-sop.md), and the sole
[Conversation Rotation SOP](conversation-rotation-sop.md). An adopting project keeps its own product,
security, Git, CI, and production authorities; transporting this document or a handoff does not transfer
them.

## Adoption boundaries and owners

| Scope | Owner | Safe default |
| --- | --- | --- |
| MWR self-maintenance | MWR Master and the assigned Worker role | Treat governance, contract, recovery, release, or authorization changes as STRICT; preserve v1 behavior and existing four core SOP boundaries. |
| Other project discovery | That project's owner or Master | Read-only inventory first; do not write project state, create worktrees, or alter routing until ownership and authority are explicit. |
| Other project pilot | The adopting project's Master/owner | Use one bounded, non-production task with default-deny external authority and a pinned MWR source. |
| Ongoing operation | The adopting project's existing Master/Workers | Reuse the project's accepted terms and records; do not create a second role registry or replace product permissions with MWR documents. |

Adoption itself is a governance and recovery decision, so it uses STRICT unless the project owner has
explicitly classified a purely editorial, local note as FAST. A later task may use FAST only when it
passes all FAST conditions; any parallel work, extra worktree, persistent state, contract, security,
release, production, irreversible, or uncertain scope enters STRICT.

## 1. Inventory before adoption

The adopting owner performs a read-only inventory and records the evidence in existing project-owned
planning or handoff projections, not in a new MWR record type:

- repository root, current clean/dirty state, branches, worktrees, commit graph, CI/release scripts,
  production targets, and preserved user material;
- current task system, roles, visible conversations, ownership, durable bindings, task/Plan/Card-like
  records, handoffs, gates, recovery paths, and retention policy;
- existing authorization boundaries, credentials/secret locations, external services, execution runners,
  destructive operations, and who may approve each one;
- the MWR source commit and relevant documentation/Schema compatibility, plus whether `.codex/` state is
  ignored or intentionally tracked by project policy; and
- semantic file ownership and dependencies. A role or worktree is never inferred from a title, folder
  name, equal waves, or a convenient available directory.

Stop if the inventory cannot prove the current baseline, one-to-one role/worktree binding, ownership,
state root, or authority boundary. Preserve dirty/untracked material and use the
[Compliance Audit SOP](sop-compliance-audit-sop.md) with `NOT_PROVEN` evidence.

## 2. Map roles and worktrees

Map one long-lived responsibility role to one current visible conversation and one retained worktree/
branch pair. Master owns creation, binding, rotation, and archive decisions. Workers receive only their
allowed implementation paths and may not bind roles, replace worktrees, synchronize, or archive. Use the
Conversation Rotation SOP for successor creation and confirmation; do not introduce a role registry.

For MWR self-maintenance, the existing `protocol-infrastructure` role and retained project worktrees
remain governed by the current Plan and Cards. For another project, translate Master/Worker into its
existing domain names while preserving identity separation: role, conversation generation, worktree,
branch, frozen baseline, product workflow, runtime execution, and external authorization are distinct.

Before a pilot, prove for every selected role:

- absolute worktree and branch are available and their full `HEAD`, status, and preserved material are
  known;
- no active Card, task, or visible conversation is being silently reused by another role;
- ownership and dependency edges are explicit and non-overlapping; and
- the owner, current Plan/Task/Card identity, model profile, and complete default-deny authorization are
  recoverable after a conversation restart.

## 3. Choose FAST or STRICT

Apply the existing FAST gate to each concrete task, not to adoption as a whole:

| Route | Conditions | Adoption consequence |
| --- | --- | --- |
| FAST | One task/worktree, Card absent or `IDLE`, no active competing binding, clear ownership, bounded local verification, and no governance/protocol/state/auth/persistence/release/security/production/irreversible impact. | Work in the current project task/worktree; create no Plan, Task Spec, Card, adoption record, extra worktree, or Operation Receipt. External and destructive authority remains separate. |
| STRICT | Any FAST condition is false or uncertain, or adoption/pilot touches roles, persistent state, recovery, contracts, release, security, or parallel work. | Master publishes a versioned Task Spec and Plan, freezes a full baseline, activates the canonical Card, and uses the full handoff/integration gates. |

Adoption documentation, routing, state-root setup, version changes, and rollback are STRICT governance
work. Do not make them look FAST merely because no application code changes.

## 4. Establish the existing state root

Use the existing protocol location unless project policy explicitly names another compatible location:

```text
<MASTER_WORKTREE>/.codex/multi-worktree-release/
├── dispatch-plan.json
└── tasks/<task-id>.json
```

The Master state root is local coordination state, not a product database, role registry, adoption
ledger, or permission store. Decide and document only the existing project's track/ignore policy; never
commit secrets or silently create a second state root. Worker Cards stay at the canonical ignored
`<WORKTREE>/WORKTREE_TASK.json` path when that protocol is adopted, with `WORKTREE_TASK.md` as a human
projection only. A missing or conflicting state root is a stop, not permission to initialize over user
material.

## 5. Pin, pilot, and decide

1. Pin the exact MWR source commit (or an existing project-approved immutable release reference) and
   record it in the adopting project's existing governance/task evidence. Pinning is compatibility
   evidence, not a new authoritative record or an authorization grant.
2. Verify the pinned source's `SKILL.md`, methodology, templates, Schema, validator, and applicable SOPs
   are mutually consistent. Run the available contract/unit checks from the source repository; missing
   tooling or evidence is `NOT_PROVEN`.
3. Run one bounded pilot with no production publish, destructive action, external side effect, or
   unbounded execution. Test the complete relevant path: discovery, classification, assignment,
   Worker evidence, Master review, and recovery/closeout where applicable.
4. Audit the pilot using the [SOP Compliance Audit SOP](sop-compliance-audit-sop.md). Proceed only when
   ownership, evidence, authorization, recovery, and the user's expected outcome are all proven.
5. Roll out by responsibility boundary, not by copying every template or creating every possible
   worktree. Keep v2 adoption/binding prototypes unrouted and retain the current v1 authoritative flow.

Minimum pilot evidence is the pinned source SHA, project/worktree/role map, baseline and status, route
decision, Plan/Task/Card identities if STRICT, checks and results, authorization actually used, preserved
material, observed failure/recovery behavior, and an owner decision. Do not report a pilot as `PASS` if
any required item is `NOT_PROVEN`.

## 6. Failure exit and rollback

Stop and preserve the project, current HEAD, records, dirty/untracked material, and evidence when an
adoption check finds wrong identity, ownership, dependency, state root, source pin, model, authorization,
scope, or recovery behavior. Route the mismatch through the [Exception and Recovery SOP](exception-recovery-sop.md):
the affected task may be gated, revised, superseded, cancelled, or left `BLOCKED` only by its existing
owner and legal transition.

If the pilot is not accepted, exit adoption by stopping new dispatch and documenting the reason in the
project's existing owner-facing planning evidence. A rollback means returning only adoption-owned
documentation or routing changes to a previously proven compatible source through a new, reviewed commit
or the project's existing reversible mechanism. It never means resetting a worktree, deleting records,
discarding user changes, force-pushing, or silently changing a baseline. Re-validate the project after
rollback; if the previous state cannot be proven, leave the result `NOT_PROVEN` and keep the owner lock
or blocker visible.

No adoption step authorizes push, publication, execution, deletion, cleanup, synchronization, or
production use. Those actions require their existing independent authority every time.
