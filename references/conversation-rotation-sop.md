# Persistent Conversation Rotation SOP

This document is the single normative human procedure for the lifecycle of persistent Master and Worker conversations.
It defines role binding, rotation, structured handoff, successor bootstrap, predecessor archiving, duplicate reconciliation,
and safe failure stops. It is a documentation procedure, not a Schema, role registry, Dispatch Plan, Worker Card, Master Card,
new machine state, or authorization grant. Existing v1 records, state transitions, and default-deny authority remain the source
of truth.

## Ownership and invariants

Master is the sole lifecycle owner for every persistent role binding and every conversation create, rotate, or archive
decision. A Worker may report that rotation is needed and provide read-only evidence, but may not create, bind, or archive a
conversation. A Worker also may not retire the retained worktree or branch.

Within a project context, use `<responsibility-role>-<conversation-generation>` for the persistent conversation title, such as
`Master-1.0` or `协议基础设施-1.1`. Project and Skill names belong in project context and persisted Plan/Task/Card records;
do not invent an `MWR` or other project prefix in a global or unscoped view unless the user explicitly requests a special
naming convention. Titles remain human-readable projections and do not carry mutable status, branch, worktree, task ID, model
profile, or authorization.

The default rotation approach is **blank successor plus structured handoff**:

- “Blank successor” means a new conversation with no copied transcript or inherited chat context. It does not mean an empty
  filesystem: the successor reuses the retained physical worktree and sees its existing files, commits, and preserved
  untracked material in place.
- A blank successor is mandatory by default. Master may use a fork only when the predecessor history is genuinely short and
  forking is demonstrably necessary; Master records that reason in the rotation handoff or decision. A fork is the narrow
  exception to the blank-successor default and still uses the same role, retained worktree and branch, incremented generation,
  read-only bootstrap, explicit confirmation, and predecessor visibility safeguards. It does not inherit implementation,
  execution, publication, destructive, synchronization, or scope-expansion authority.
- Persisted records, not conversation memory, recover the facts. The successor receives no implementation, execution,
  publication, destructive, synchronization, or scope-expansion authority merely because it replaces a predecessor.
- One long-lived role has one current visible conversation and one retained worktree/branch pair. A duplicate visible binding
  stops dispatch until Master reconciles it.
- Archiving is history management only. It is not worktree, branch, Task Spec, Card, commit, or role retirement, and it never
  implies deletion or cleanup.

### Rotation triggers

Rotation is triggered only when the context has become too long to continue reliably, the user explicitly requests it, or a
persistent risk to continuity, availability, or recovery requires it. Task completion, convenience, or an ordinary pause alone
are not rotation triggers and do not authorize archiving either conversation.

## Default rotation sequence

Master follows this sequence in order. A mismatch at any step is a failure stop; do not skip ahead to archive.

1. **Verify current durable state.** Read the repository governance, current role binding, visible conversations, Dispatch Plan,
   relevant Task Specs and Cards, current handoffs, and read-only Git/worktree inventory. Record the predecessor's role and
   generation, absolute worktree, branch, full HEAD, status, preserved dirty or untracked material, Plan and Task identities,
   Card states and revisions, blockers, unfinished work, and latest gates. Prove that exactly one visible conversation claims the
   role and retained worktree/branch pair. A wrong HEAD, wrong worktree, digest mismatch, dirty-state surprise, or duplicate
   binding stops the procedure while leaving the predecessor visible and the worktree untouched.
2. **Create the default blank successor.** Master creates a blank successor conversation with the same long-lived responsibility
   role, the same retained worktree and branch, and the next conversation generation. Only when the predecessor history is
   genuinely short and forking is demonstrably necessary may Master create a fork instead, and Master records that reason. In
   either case, the successor does not create a Task Spec, change a Plan, rewrite a Card, copy files, or synchronize the
   worktree. The predecessor remains visible.
3. **Complete the predecessor's final structured handoff.** Master records or sends the full rotation handoff before asking the
   successor to confirm. It includes the role and generations, exact paths and Git facts, Plan/Task/Card identities and digests,
   every active or terminal task and Worker/Master handoff, preserved material, blockers, unfinished work, latest gates, and
   actions requiring renewed authority. The handoff is evidence and does not grant authority by transport.
4. **Run the successor's read-only bootstrap.** The successor reads the governance and state-card instructions, then recovers
   facts from the persisted Plan, complete Task Specs, Cards, handoffs, and Git/worktree inventory. It verifies the same role,
   incremented generation, exact worktree and branch, HEAD/status and preserved material, one-to-one binding, Plan/Task/Card
   identities and revisions, and all relevant digests. It must report any mismatch and stop; it must not resume implementation
   or perform lifecycle actions while verification is incomplete.
5. **Require explicit successor confirmation.** Master waits for a structured, read-only confirmation that every bootstrap
   check passed. Silence, partial reading, a missing confirmation, or any mismatch is not confirmation. Keep the predecessor
   visible and do not archive it until this explicit confirmation is received and reconciled by Master.
6. **Archive only the predecessor conversation.** After confirmation, and only after Master independently reconciles the
   evidence, Master may archive the predecessor. The successor becomes the current visible conversation for the same role.
   Archive no successor, worktree, branch, Task Spec, Card, commit, or other history as part of this rotation.
7. **Continue under the successor binding.** The successor reuses the retained worktree and branch and continues from persisted
   facts. Rotation alone does not change Task ID, Task Spec revision or digest, Plan identity, Worker/Master Card state, or Git
   identity. Task completion alone never triggers conversation archiving; a later archive is a separate Master-owned decision.

## Identity and retention rules

Rotation changes conversation context and generation only. It preserves, and the successor must verify:

- the long-lived responsibility role and its one-to-one visible-conversation binding;
- each affected Task ID, Task Spec revision and digest, and the relevant Plan identity, including release task, plan path,
  semantic plan revision, and plan digest;
- the retained absolute Git worktree/branch/HEAD identity, including the frozen baseline, status, and preserved dirty or untracked
  material;
- existing Worker/Master Card states, record revisions, handoff identities, integration mappings, blockers, and gate evidence.

Record revisions may advance only through their existing persisted-record operations; conversation rotation is not a reason to
rewrite semantic revisions or digests. If a new task, revised assignment, or new Plan is needed, Master follows the ordinary
Dispatch and supersession rules separately; rotation does not silently create one.

Never copy uncommitted files into a successor, reset or synchronize a worktree, switch or recreate a branch, delete a worktree,
branch, Task Spec, Card, commit, handoff, or other history, or change a Worker/Master state merely to rotate a conversation.
Any such action requires its own existing authority and owner. A Worker cannot archive the predecessor, even if the Worker
believes the successor is ready.

## Read-only failure checks

These checks are documentation-level simulations: compare the recorded fact with the observed fact and take no mutation. Each
failure must stop safely, preserve the predecessor and retained worktree, and leave later recovery to Master.

| Check | Read-only condition | Required safe result |
| --- | --- | --- |
| Wrong HEAD | Successor or inventory HEAD differs from the handoff's verified full SHA | Stop; keep predecessor visible; do not archive, reset, checkout, rebase, synchronize, or copy files |
| Wrong worktree | Successor path differs from the retained absolute path, or the path/branch binding is unavailable | Stop; preserve the predecessor and both path/branch facts; do not create a replacement binding or delete anything |
| Duplicate visible conversation | More than one visible conversation claims the role or retained worktree/branch pair | Stop dispatch for that binding; reconcile ownership through Master; archive only a proven unassigned duplicate, never automatically |
| Successor not confirmed | Successor has not supplied the complete read-only confirmation, or any check is missing/mismatched | Stop before archive; keep predecessor visible and retain the worktree, records, and evidence unchanged |
| Worker self-archive | A Worker attempts or requests the archive operation as its own lifecycle decision | Reject the operation; Worker may report evidence only; Master retains predecessor visibility and lifecycle ownership |

The same stop applies to a Task/Plan/Card identity or digest mismatch, an unexpected dirty or untracked path, an unavailable
successor, or a request to expand scope. Do not convert a failed check into a new machine state or silently resolve it from
conversation memory.

## Master rotation handoff

Master uses the structured projection below for the predecessor's final handoff. It is not a fourth persisted record and does
not replace the Dispatch Plan, Task Specs, Cards, or Git evidence.

```text
Master rotation handoff
Action: ROTATE
Role: <ROLE>
Predecessor conversation: <TASK/TITLE/OLD_GENERATION>
Successor conversation: <TASK/TITLE/NEW_GENERATION_OR_TARGET>
Retained worktree: <ABSOLUTE_PATH>
Branch: <BRANCH>
HEAD and status: <FULL_SHA / CLEAN_OR_PRESERVED_DETAILS>

Persisted coordination
- Dispatch Plan: <PATH / RELEASE_TASK_ID / PLAN_REVISION / RECORD_REVISION / PLAN_DIGEST>
- Task Specs: <TASK_ID / TASK_SPEC_REVISION / TASK_SPEC_DIGEST / PATH>
- Worker Cards: <TASK_ID / STATE / RECORD_REVISION / WORKER_SHA / INTEGRATED_SHA>
- Master handoffs: <TASK_ID / STATE / WORKER_SHA / INTEGRATED_SHA>
- Current blockers, unfinished work, and latest gates: <DETAILS_OR_NONE>
- Preserved dirty or untracked material: <PATHS_OR_NONE>

Rotation rules
- Successor mode: <BLANK_DEFAULT / FORK_EXCEPTION>
- Blank successor with no copied chat context: <true / documented fork exception>
- Fork exception reason (required only for short history + genuine necessity): <DETAILS_OR_NOT_APPLICABLE>
- Rotation trigger: <CONTEXT_TOO_LONG / EXPLICIT_USER_REQUEST / PERSISTENT_RISK>
- Same role, retained worktree, and branch; generation increments by one: <PASS/FAIL>
- Successor must perform read-only bootstrap and explicit confirmation: true
- Predecessor remains visible until that confirmation: true
- Archive target after confirmation: predecessor conversation only
- Worktree, branch, Task Specs, Cards, commits, and other history are retained: true

Master decision: <PROCEED_TO_SUCCESSOR_BOOTSTRAP / STOP_AND_PRESERVE>
Recovery owner: <MASTER_ROLE_OR_THREAD>
```

## Successor read-only confirmation

The successor sends this confirmation to Master. It confirms facts only; it does not archive the predecessor or grant new
authority.

```text
Successor read-only confirmation
Role and generation: <ROLE / NEW_GENERATION>
Predecessor remains visible: <PASS/FAIL>
Successor mode and documented fork exception if any: <PASS/FAIL / DETAILS>
Blank successor with no inherited chat context (required for BLANK_DEFAULT): <PASS/FAIL / NOT_APPLICABLE>
Absolute worktree and branch: <PATH / BRANCH>
HEAD and status: <FULL_SHA / CLEAN_OR_PRESERVED_DETAILS>
One-to-one role/worktree binding: <PASS/FAIL>
Dispatch Plan and Task Spec identities/digests: <PASS/FAIL / DETAILS>
Worker/Master Card states and revisions: <PASS/FAIL / DETAILS>
Preserved dirty or untracked material: <PATHS_OR_NONE>
No copied files, synchronization, reset, archive, or scope expansion performed: <PASS/FAIL>

Confirmation: <EXPLICIT PASS — MASTER MAY ARCHIVE PREDECESSOR / STOP_AND_PRESERVE>
Unresolved mismatch or blocker: <NONE_OR_DETAILS>
```

## Failure-stop report

Use this human-readable report for a failed read-only check. `STOP_AND_PRESERVE` is a decision in the procedure, not a new
persisted machine state.

```text
Conversation rotation failure-stop report
Check: <WRONG_HEAD / WRONG_WORKTREE / DUPLICATE_VISIBLE_CONVERSATION / SUCCESSOR_NOT_CONFIRMED / WORKER_SELF_ARCHIVE / OTHER>
Role and generations: <ROLE / PREDECESSOR / SUCCESSOR_OR_NONE>
Master handoff: <PATH_OR_THREAD>
Actual: <OBSERVED_FACT>
Expected: <RECORDED_FACT>
Evidence: <READ_ONLY_COMMAND_OR_RECORD>

Required result: STOP_AND_PRESERVE
- Predecessor remains visible: true
- Retained worktree and branch remain untouched: true
- Task/Plan/Card records remain unchanged: true
- Archive, deletion, reset, synchronization, and scope expansion performed: none
Recovery owner and next decision: <MASTER / RECONCILE / REVISE / SUPERSEDE / CANCEL / TAKEOVER>
```

## Recovery and completion

If a predecessor disappears before confirmation, Master recovers facts from Git, governance files, the persisted Plan, complete
Task Specs, Cards, handoffs, and the retained worktree. Master does not assume confirmation, archive history, or clean up the
binding from elapsed time. A duplicate, mismatch, unavailable successor, or preserved dirty state remains a stop until Master
records the narrowest valid recovery decision.

After a successful confirmation, only Master archives the predecessor. The successor remains the current conversation, the role's
worktree and branch remain retained, and existing task lifecycle transitions continue unchanged. A completed Worker task returns
its Card to `IDLE`; it does not archive either conversation or retire the role binding.
