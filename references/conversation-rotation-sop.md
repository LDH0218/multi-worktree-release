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
  filesystem: the successor must reuse the retained physical worktree and see its existing files, commits, and preserved
  untracked material in place. By default, create it in the same project using `local`, then explicitly
  target the retained worktree on every command and file operation. Application cwd may remain the
  Master checkout; native application rebinding is not a prerequisite for this execution method.
- A blank successor is mandatory by default. Master may use a fork only when the predecessor history is genuinely short and
  forking is demonstrably necessary; Master records that reason in the rotation handoff or decision. A fork is the narrow
  exception to the blank-successor default and still uses the same role, retained worktree and branch, incremented generation,
  read-only bootstrap, explicit confirmation, and predecessor visibility safeguards. It does not inherit implementation,
  execution, publication, destructive, synchronization, or scope-expansion authority.
- Persisted records, not conversation memory, recover the facts. The successor receives no implementation, execution,
  publication, destructive, synchronization, or scope-expansion authority merely because it replaces a predecessor.
- One long-lived role has one current execution owner and one retained worktree/branch pair. During
  rotation, the stopped predecessor may remain visible alongside a read-only successor until confirmation
  and remain visible but inactive if archive is deferred after the successor takes over;
  this declared handover is not a competing binding. In the other SOPs/templates, a "duplicate visible
  conversation" means an undeclared competing claim, not this controlled handover interval.
  Undeclared duplicates or concurrent writers stop dispatch.
- Archiving is history management only. It is not worktree, branch, Task Spec, Card, commit, or role retirement, and it never
  implies deletion or cleanup.

### Rotation triggers

Rotation is triggered only when the context has become too long to continue reliably, the user explicitly requests it, or a
persistent risk to continuity, availability, or recovery requires it. Task completion, convenience, or an ordinary pause alone
are not rotation triggers and do not authorize archiving either conversation.

## Conversation creation and worktree binding

First distinguish a new role/worktree from a successor of an existing role. Inspect current tool capabilities
and obtain the user's requested lifecycle scope; never create a substitute simply because reuse is unavailable.

| Intended operation | Supported path and limitation |
| --- | --- |
| New conversation in the selected project's checkout | `create_thread` with that project's ID and `environment.type=local`; it uses the project's saved directory, not a path written in the prompt. |
| New independent worktree conversation under the same project | With explicit worktree-creation authority, use that project ID and `environment.type=worktree`. Select only an authorized starting branch/ref. The tool creates a new worktree; selecting an existing branch does not reuse its existing directory. |
| Blank successor in a retained worktree (default rotation) | Use the same project ID and `environment.type=local`, with a structured handoff specifying the retained absolute directory. Verify it through explicit command `workdir` and absolute file paths as described below. No new worktree, separate project, project-primary-directory change or native cwd rebinding is required. |
| Same-directory fork | `fork_thread` with `environment.type=same-directory` preserves the source directory but inherits history. It is only the documented short-history/necessary fork exception, not a blank successor. |

Different worktree conversations may belong to the same project. Project grouping, titles, attachment
lists and prompt paths do not prove the execution directory. `attach_worktree` attaches to the calling
chat under its ownership restrictions; it is not a general way to relocate another new conversation.
Handoff may move Git state and is not an arbitrary-directory binding shortcut.

### Explicit execution directory (default rotation)

Before creation, Master confirms the predecessor has stopped executing, including any background
commands that could write the target. Silence, a missing listing or an `IDLE` Card alone is not proof.
Preserve its exact path, branch or detached state, full HEAD, dirty material and current records.

Create a blank `local` conversation in the same project with this structured handoff. First report
`pwd` and Git top-level without a directory override to record the application's default. A default
cwd different from the retained worktree is expected and does not fail this method. Then fully read
the retained worktree's applicable instructions using absolute paths. In at least two independent
command calls explicitly set `workdir` to the retained absolute directory and collect:

```bash
pwd
git rev-parse --show-toplevel
git rev-parse --git-common-dir
git rev-parse HEAD
git symbolic-ref -q --short HEAD
git status --short
```

Compare the actual target path/branch/HEAD and shared Git directory with the handoff and worktree
inventory. A detached target can pass a read-only check when expected, but cannot satisfy a Task Spec
requiring a named branch. New-worktree creation still records its generated path before publication.
Record requested and verified model settings separately using the
[model-profile check](task-lifecycle-sop.md#model-profile).

Continue using these directory rules after bootstrap and on every later turn:

- Set `workdir` explicitly on every target command; one prior `cd` does not carry into another shell.
  When a command tool lacks a directory option, put an explicit guarded `cd "<absolute-target>" && ...`
  in that invocation. If a tool cannot unambiguously select its target, stop that operation.
- Read, edit and patch files using absolute target paths. Resolve scripts, test inputs and output paths
  from the intended worktree; for cross-worktree Plan/Card tools pass the verified Master/state paths
  explicitly (including `--repo-root` where applicable), rather than inheriting the chat's default cwd.
- Before mutation on a new turn or after interruption, recheck target Git identity, current authorized
  HEAD/state and ownership. Update expected HEAD only from authorized task progress, not from a mismatch.
- Application Git, review, commit and worktree buttons may still target the Master checkout. Use
  explicitly targeted Git commands for authorized operations; use UI actions only if their target is
  independently verified. Prompt text and command overrides do not change native application binding.

This verifies execution in the retained directory, not application rebinding, filesystem isolation,
or a sandbox boundary. Both cwd values remain explicit in the handoff. No native-directory parameter
is needed to complete this method; unverified access or target identity still yields `NOT_PROVEN`.

### Pending creation or missing conversation listing

- Save the creation result and correlate it to the intended role/project/baseline. A returned
  `clientThreadId` means pending setup, not a usable `threadId`; never pass it to read/wait/message tools.
- Use documented status/listing capabilities with bounded, spaced checks. If a real ID is absent from
  the list, use an already-known real ID, or narrowly scoped read-only creation diagnostics that link
  the request to a real ID, then verify its initial prompt and `cwd` with `read_thread` before trusting it.
- Once the real ID is verified, use `wait_threads` for completion. Missing list entries, an empty
  attachment list or silence do not prove deletion, failed creation or failed directory binding.
- If identity or binding remains unverifiable, stop with `NOT_PROVEN`, retain the pending result and
  any generated worktree, and report. Do not retry creation, invent IDs, edit application storage,
  dispatch implementation or archive a predecessor to resolve the uncertainty.

## Default rotation sequence

Master follows this sequence in order. Failed identity, ownership, authorization or required checks
stop handover. Archive is separate after confirmed handover and may be deferred without blocking work.

1. **Verify current durable state.** Read the repository governance, current role binding, visible conversations, Dispatch Plan,
   relevant Task Specs and Cards, current handoffs, and read-only Git/worktree inventory. Record the predecessor's role and
   generation, absolute worktree, branch, full HEAD, status, preserved dirty or untracked material, Plan and Task identities,
   Card states and revisions, blockers, unfinished work, and latest gates. Verify the predecessor has
   stopped and no competing writer claims the role/worktree. A wrong HEAD, wrong worktree, digest mismatch, dirty-state surprise, or duplicate
   binding stops the procedure while leaving the predecessor visible and the worktree untouched.
2. **Create the default blank successor.** Use the same project and `local` mode, with the retained
   directory in the structured bootstrap prompt. Master creates a blank successor with the same
   long-lived responsibility role, retained worktree and branch, and the next conversation generation.
   Follow the explicit execution-directory procedure above; do not create a replacement worktree.
   Only when the predecessor history is genuinely short and forking is demonstrably necessary may
   Master create a fork instead, and Master records that reason. In
   either case, the successor does not create a Task Spec, change a Plan, rewrite a Card, copy files, or synchronize the
   worktree. Resolve the current project model profile and explicitly pass model/effort to the creation
   tool, following the [Task Lifecycle model-profile check](task-lifecycle-sop.md#model-profile).
   All roles default to `gpt-6.1-sol` only when no explicit user/project choice exists; an active assignment
   retains its recorded profile. Do not silently inherit application settings. Record requested settings
   separately from observed model/effort/tier. Unobserved preferences remain `NOT_PROVEN` but do not
   block directory confirmation or dispatch; unmet/unverified explicit hard requirements block execution.
   Preserve prior assignment requirements; never invent a tier parameter or claim acceleration.
   The predecessor remains visible.
3. **Complete the predecessor's final structured handoff.** Master records or sends the full rotation handoff before asking the
   successor to confirm. It includes the role and generations, exact paths and Git facts, Plan/Task/Card identities and digests,
   every active or terminal task and Worker/Master handoff, preserved material, blockers, unfinished work, latest gates, and
   actions requiring renewed authority. The handoff is evidence and does not grant authority by transport.
4. **Run the successor's read-only bootstrap.** The successor reads the governance and state-card instructions, then recovers
   facts from the persisted Plan, complete Task Specs, Cards, handoffs, and Git/worktree inventory. It verifies the same role,
   incremented generation, exact target worktree and branch through explicit directory calls,
   HEAD/status and preserved material, sole execution ownership, Plan/Task/Card
   identities and revisions, all relevant digests, and launcher/settings evidence for the selected
   model/effort/tier. Report unobserved preferences separately. Identity/ownership/authorization
   mismatches or missing required verification stop handover; implementation waits for confirmation.
5. **Require explicit successor confirmation.** Master waits for a structured, read-only confirmation that every required bootstrap
   check passed, with unobserved preferences reported separately. Silence, partial reading, a missing confirmation, or a required-check mismatch is not confirmation. Keep the predecessor
   visible and do not archive it until this explicit confirmation is received and reconciled by Master.
   Master records in the existing handoff/decision that the successor is the sole current execution
   owner and the predecessor must remain inactive. This completes handover; no new machine record is needed.
6. **Continue under the successor binding.** With applicable task authority and required checks satisfied,
   the successor may continue before predecessor archive. It explicitly targets the retained worktree
   on every command/file operation and continues from persisted facts. Rotation alone does not change
   Task ID, Task Spec revision or digest, Plan identity, Worker/Master Card state, or Git
   identity. Task completion alone never triggers conversation archiving; a later archive is a separate Master-owned decision.
7. **Archive the predecessor when safe.** Master may archive it only when the selected operation is
   verified not to retire or auto-clean the retained worktree. Otherwise defer only archive, retain
   the inactive predecessor and record the unresolved archive condition in the handoff. Successful
   handover remains valid; the inactive predecessor is not a competing writer. Do not change cleanup
   settings implicitly. If it resumes writing, stop affected execution and reconcile ownership.
   Archive no successor, worktree, branch, Task Spec, Card, commit or other history as part of rotation.

## Identity and retention rules

Rotation changes conversation context and generation only. It preserves, and the successor must verify:

- the long-lived responsibility role and its sole current execution owner (an inactive predecessor may remain visible);
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

These checks are documentation-level simulations: compare the recorded fact with the observed fact and take no mutation.
Apply each row's scoped outcome; identity/authority failures stop handover, while archive and preference
limitations remain separate. Preserve the predecessor and retained worktree and leave recovery to Master.

| Check | Read-only condition | Required safe result |
| --- | --- | --- |
| Wrong HEAD | Explicitly targeted worktree or inventory HEAD differs from the handoff's verified full SHA | Stop; keep predecessor visible; do not archive, reset, checkout, rebase, synchronize, or copy files |
| Wrong worktree | Explicitly targeted Git top-level, branch or directory identity differs from the handoff | Stop; preserve predecessor and both path/branch facts; application default cwd alone is not this failure |
| Main checkout remains the default | Blank Local conversation starts in Master; independent explicit-directory calls prove the retained target | Allow execution-directory confirmation; retain explicit targeting for all later commands and files, without claiming native rebinding |
| Targeting unavailable or omitted | Target cannot be verified, or a planned write would implicitly use the default directory | Stop before that operation; re-establish the explicit target or report `NOT_PROVEN`; do not create a substitute worktree |
| Pending or missing listing | Only a client ID is available, or the known conversation is omitted from listing | Resolve and verify the real ID read-only; otherwise stop without duplicate creation |
| Duplicate visible conversation | Undeclared competing binding or predecessor still executing; excludes declared handover and an inactive predecessor awaiting archive | Stop dispatch; reconcile ownership through Master; archive only a proven unassigned duplicate, never automatically |
| Archive safety unavailable | Successor confirmed and sole writer established, but archive may clean the retained directory | Defer archive only; retain inactive predecessor, record the condition, allow already authorized successor work |
| Runtime preference unobserved | Model/effort/tier preference lacks observation, but no explicit hard requirement is unmet | Record setting as `NOT_PROVEN`; do not claim it applied; other required checks still govern continuation |
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
Creation mode: same-project Local; blank successor; explicit execution directory
Application default cwd: <OBSERVED_PATH>
Retained execution directory and independent call evidence: <ABSOLUTE_PATH / EVIDENCE>
Predecessor stopped and no competing writer: <EVIDENCE / NOT_PROVEN>
Every target command uses explicit workdir; every file path is absolute: true
Branch: <BRANCH>
HEAD and status: <FULL_SHA / CLEAN_OR_PRESERVED_DETAILS>
Requested model / effort / tier: <PROJECT_PROFILE>
Observed launcher/settings evidence: <VALUES / EVIDENCE / NOT_PROVEN>
Explicit hard runtime requirements: <REQUIREMENTS_OR_NONE>
Unobserved preferences (nonblocking): <VALUES_OR_NONE>

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
- Archive disposition: <SAFE_TO_ARCHIVE / DEFERRED_WITH_INACTIVE_PREDECESSOR_AND_REASON>
- Confirmed successor may continue authorized work while archive is deferred: true
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
Application default cwd: <OBSERVED_PATH; MAY_DIFFER_FROM_TARGET>
Explicit target cwd, Git top-level and shared Git directory: <VALUES / INDEPENDENT_CALL_EVIDENCE>
Predecessor stopped; only declared read-only overlap remains: <PASS/FAIL / EVIDENCE>
Every later target command/file operation will explicitly select the retained directory: true
Native application binding changed: <NOT_CLAIMED / SEPARATELY_VERIFIED_EVIDENCE>
HEAD and status: <FULL_SHA / CLEAN_OR_PRESERVED_DETAILS>
One-to-one role/worktree binding: <PASS/FAIL>
Dispatch Plan and Task Spec identities/digests: <PASS/FAIL / DETAILS>
Worker/Master Card states and revisions: <PASS/FAIL / DETAILS>
Model/effort/tier settings verified against applicable profile: <PASS/FAIL/NOT_PROVEN / EVIDENCE>
Explicit hard requirements satisfied: <PASS/FAIL/NOT_PROVEN / NONE>
Unobserved preferences do not block this handover: <VALUES_OR_NONE>
Preserved dirty or untracked material: <PATHS_OR_NONE>
No copied files, synchronization, reset, archive, or scope expansion performed: <PASS/FAIL>

Confirmation: <EXPLICIT PASS — MASTER MAY CONFIRM HANDOVER / STOP_AND_PRESERVE>
Archive: <SEPARATE_SAFETY_CHECK / DEFERRED; DOES_NOT_BLOCK_CONFIRMED_HANDOVER>
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

After a successful confirmation and Master reconciliation, the successor becomes the sole current
execution owner. Only Master archives the predecessor when safe; deferred archive leaves the
predecessor visible but inactive and does not block authorized successor work. The role's
worktree and branch remain retained, and existing task lifecycle transitions continue unchanged. A completed Worker task returns
its Card to `IDLE`; it does not archive either conversation or retire the role binding.
