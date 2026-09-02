# Retention and Retirement SOP

This is the human procedure for retaining, archiving, retiring, or considering deletion of MWR
conversations, worktrees, branches, Task Specs, Worker Cards, Dispatch Plans, closeout archives, and
candidate or handoff evidence. Archive, completion, conversation hiding, and deletion are different
outcomes. This SOP adds no retention registry, machine state, contract field, role binding, or cleanup
authority; the existing records, Git history, and repository policy remain authoritative.

The [Conversation Rotation SOP](conversation-rotation-sop.md) is the sole authority for conversation
creation, successor confirmation, rotation, and archive decisions. The [Task Lifecycle SOP](task-lifecycle-sop.md)
governs Worker/Card completion, the [Release SOP](release-sop.md) governs closeout and rollover, and the
[Exception and Recovery SOP](exception-recovery-sop.md) governs unsafe or incomplete retirement. A
Worker may report retention facts but may not archive a conversation, retire a binding, or delete data.

## Trigger, owner, inputs, evidence, and outcomes

**Triggers.** Use this SOP before archiving or retiring a conversation, role binding, worktree, branch,
Task Spec, Card, Plan, closeout, candidate, handoff, or other evidence; before considering deletion or
cleanup; after a release or task reaches a terminal result; and after an interrupted or disputed
retention decision.

**Owner.** Master owns MWR retention, release closeout, rollover, and binding decisions, subject to the
Conversation Rotation SOP for conversation creation/successor/archive decisions. The existing project
owner owns project-specific retention, legal, and security obligations. Workers may report facts but may
not archive conversations, retire bindings, or delete or clean up data.

**Required inputs.** Identify the exact item and locator, task/release and role/conversation identity,
owner, branch/worktree and full `SHA`/status, dirty or untracked material, reachable commits and
references, active or historical Plan/Card/handoff/candidate/recovery evidence, legal/security holds,
retention policy, archive bytes/digests where relevant, and the separate exact authority and scope for
any destructive operation.

**Retained evidence.** Keep the source bytes and complete record lineage, item path/locator, identity,
owner and references, baseline/current SHA and status, preserved material, archive bytes or digest,
retention reason, dependency and hold checks, decision owner, authorization scope, and recovery or
rollback decision in the existing task, Plan, handoff, closeout, or rotation projections. This SOP and
its compact projection are not a retention registry or deletion queue.

**Results.** `PASS` means the exact retention/archive/retirement decision is current, all references and
obligations are reconciled, required bytes are preserved, and any destructive scope has its independent
valid authorization; it permits only the next existing owner-authorized step. `FAIL` means a requirement
is contradicted, retained evidence is damaged, or an unauthorized destructive action occurred; stop and
preserve. `NOT_PROVEN` means identity, ownership, references, policy, archive bytes, authority, or
recovery evidence is missing, ambiguous, stale, partial, or unverifiable; retain the material and do
not infer permission. These labels are human results, not machine states or deletion authority.

**Stop conditions.** Stop under the Exception and Recovery SOP for a wrong or ambiguous target,
identity, owner, branch/worktree, SHA, status, binding, dependency, hold, archive, or record; dirty or
unpreserved user material; missing or incomplete provenance/backup; unclear retention period; absent,
expired, cross-capability, or overbroad destructive authorization; archive/deletion confusion; or any
request to reset, overwrite, discard, synchronize, force-push, batch-clean, delete, or automatically
retire material without already-proven exact independent authority. This task authorizes no deletion or
cleanup.

## Default retention policy

Retain each item until the relevant task, release, recovery, legal, security, and user obligations are
reconciled. A terminal status or a successful archive does not by itself authorize deletion.

| Item | Retain and archive rule | Retirement/deletion boundary |
| --- | --- | --- |
| Conversation | Keep the predecessor visible until the blank successor completes read-only bootstrap and explicit confirmation; Master may then archive only the predecessor. Keep the current role conversation available after task completion. | Conversation archive is history management, not deletion. Deletion needs separate explicit authority and the Rotation SOP's reconciliation. |
| Worktree and branch | Retain the role's worktree/branch through `IDLE`; preserve dirty/untracked material and commit history. | Retiring a binding does not delete its worktree or branch. Deletion or ref removal requires a fresh, exact destructive authorization. |
| Task Spec and Plan | Preserve exact task identity, revisions, digests, baselines, terminal lineage, and the live Plan until the release is closed. | Do not rewrite or remove immutable task history. A new task or release supersedes by existing contract rules. |
| Worker Card | Return an accepted Worker Card to `IDLE`, clearing its active lock while preserving the completed mapping under `last_task`; retain the canonical sidecar. | Closeout does not delete a Card, and an `IDLE` Card is not permission to remove the worktree or history. |
| Master Card and handoffs | Preserve the complete ordered `worker_handoffs` list, integration mappings, blockers, and candidate evidence. | Master closeout archives the exact ACTIVE snapshot; it does not erase handoffs or grant deletion. |
| Candidate/Gate evidence | Retain current and legacy evidence needed to explain the exact integrated HEAD, Gate results, provenance, invalidation, and migration history. | Stale or legacy evidence remains audit material; it is not disposable merely because a newer candidate exists. |
| Release closeout | Preserve exactly `dispatch-plan.json`, `master-card.active.json`, and `closeout.json` under the validated release archive. | The three-file archive is not a cleanup manifest, deletion list, or fourth-record license. Rollover never rewrites it. |

When project policy or law requires a longer period, use the longer requirement. When the required
retention period or owner is unclear, report `NOT_PROVEN` and retain the material.

## 1. Inventory before any retirement decision

Master performs a read-only inventory and records the decision in the existing task, Plan, handoff,
closeout, or conversation-rotation projection where applicable:

- exact item path/locator, task/release identity, owner, source conversation, branch/worktree, full SHA,
  status, and current Card/Plan/Master revisions;
- dirty/untracked/user-owned material, reachable commits, dependencies, references from active tasks,
  current or historical Gate evidence, and any recovery or legal/security hold;
- whether the item is live, terminal, archived, superseded, or merely a human projection; and
- the explicit decision owner, retention reason, archive bytes/digests if relevant, and separate authority
  needed for any destructive operation.

Do not infer that a directory is disposable from age, a completed task, an empty Card, a merged branch,
an absent conversation, or a clean status. A missing or ambiguous fact is `NOT_PROVEN`.

## 2. Safe completion and archival

1. Complete the applicable Task, Release, Exception, or Conversation Rotation checks. Accepted Worker
   work returns the Card to `IDLE`; it does not archive the conversation or retire the role.
2. For conversation rotation, keep the predecessor visible until explicit successor confirmation, then
   archive only the predecessor through the Master-owned Rotation procedure.
3. For release closeout, require a terminal Plan and handoffs, all Worker Cards `IDLE`, fresh v2
   `PASSED` evidence for the exact final HEAD, and the Release SOP's exact three-file no-overwrite
   archive. A partial archive is not completion.
4. For rollover, use only the existing Master-owned rollover procedure after verified closeout. Retain
   the old archive and receipt; do not rediscover or delete old Worker directories.
5. Preserve source bytes, complete handoff arrays, commit mappings, and evidence digests. Record actual
   external authority as `NONE` when none was used.

Archiving is a reversible history/retention action only when the existing owner says it is; it does not
authorize push, publication, deployment, execution, synchronization, cleanup, or deletion.

## 3. Independent deletion gate

Deletion, cleanup, branch/ref removal, worktree removal, or destruction of retained evidence requires a
separate explicit authorization from the applicable user/owner or authorized release role. That
authorization is not inherited from task completion, `IDLE`, integration, closeout, rollover, publication,
model profile, or a normal external-call grant. It must identify the exact target and bounded path/ref
scope, be current and digest-valid, and be checked immediately before the operation.

Before an authorized destructive action, Master or the authorized owner must prove:

- no live role, visible conversation, active/blocked task, handoff, Plan, Card, candidate, recovery, or
  retention/legal/security obligation still references the target;
- current path/ref, owner, branch/worktree, full SHA, dirty/untracked material, and intended effect are
  exactly the authorized target;
- the retained archive/source bytes and any required recovery evidence are readable and complete; missing
  backup or provenance is `NOT_PROVEN`;
- the destructive grant is independent from publication and all other capabilities, unexpired, within
  its call/cost limits, and owned by the responsible role; and
- the deletion is explicitly in scope, reviewed, bounded, and reversible where the governing policy
  requires reversibility.

If any check fails, stop and preserve. Never turn an archive into a deletion queue, infer a wildcard
target, batch unrelated cleanup, or retry an ambiguous destructive operation. This task performs no
deletion or cleanup.

## 4. Retirement, failure, and rollback

Retiring a role binding or source means stopping new use and preserving its evidence; it does not mean
deleting the conversation, worktree, branch, Task Spec, Card, Plan, commit, or archive. Master reconciles
active work, terminal lineage, successor bindings, and preserved material before recording retirement.

If a retirement or archive check is incomplete, wrong, dirty, conflicting, or interrupted, use the
[Exception and Recovery SOP](exception-recovery-sop.md): stop, keep the current lock/evidence and exact
bytes, and report `FAIL` or `NOT_PROVEN`. Recovery may resume only after revalidating the original inputs;
it may not overwrite, reset, clean, rollback history, or create an alternate archive. A rollback of an
adoption or document-retirement decision is a new reviewed owner decision or existing reversible change,
not an implicit delete or restore-all operation.

Compact human evidence may use this projection; it is not a new persisted record:

```text
Retention/retirement review
Item and exact locator: <CONVERSATION | WORKTREE | BRANCH | TASK | CARD | PLAN | EVIDENCE | CLOSEOUT>
Owner and references: <ROLE / TASK/RELEASE / LIVE_OR_TERMINAL_DEPENDENCIES>
Current SHA/status/material: <FULL_SHA / STATE / DIRTY_OR_UNTRACKED_DETAILS>
Retention/archive evidence: <EXACT SOURCE BYTES / ARCHIVE DIGEST / NONE>
Decision: <RETAIN | ARCHIVE | RETIRE_BINDING | DELETE_REQUESTED>
Deletion authority: <NONE | EXACT_SEPARATE_AUTHORITY_AND_SCOPE>
Result: <PASS | FAIL | NOT_PROVEN>
Recovery owner and next decision: <MASTER_OR_EXISTING_OWNER / DETAILS>
```

No item is automatically cleaned, deleted, or archived merely because this SOP is consulted.
