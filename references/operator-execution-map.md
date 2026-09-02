# Operator Execution Map

This is the single human entry map for operating Multi-Worktree Release. It fixes the order of the
existing procedures and command/evidence checks; it adds no Schema field, machine state, role registry,
authorization grant, runtime behavior, or authoritative record. The existing Plan, Task Spec, Worker or
Master Card, Git state, Schema/validator, and the eight SOPs remain authoritative. When this map and a
persisted record disagree, the record is not silently changed: stop and route the mismatch through the
[Exception and Recovery SOP](exception-recovery-sop.md).

The fixed order is:

```text
universal entry gate
  ├─ FAST (short local path)
  ├─ STRICT task delivery → integration → integrated-tree validation
  │                         → candidate approval → separate publication decision/action
  │                         → closeout → rollover
  ├─ conditional governance or Conversation Rotation route
  └─ any mismatch at any point → STOP_AND_PRESERVE
```

`PASS`, `FAIL`, and `NOT_PROVEN` in this map are human decision results, not permissions or machine
states. `PASS` permits only the next already-authorized step. `FAIL` means an invariant is contradicted
or a forbidden action occurred; stop and preserve. `NOT_PROVEN` means evidence is missing, ambiguous,
stale, partial, or unverifiable; treat the affected path as not accepted and stop.

## Universal entry gate — always first

**Owner.** The current operator performs read-only discovery. Master owns route selection for STRICT,
integration, release, governance, and persistent conversation decisions; a Worker may verify and report
only within its assignment.

**Ordered checks.**

1. Identify the requested outcome, responsibility role, current visible conversation/generation,
   absolute repository and worktree, branch, and the owner of the next decision.
2. Establish Git truth without mutation. Use the existing read-only checks:

   ```bash
   git status --short --branch
   git rev-parse HEAD
   git branch --show-current
   git worktree list --porcelain
   git diff --name-only
   ```

   Inspect preserved dirty/untracked material, the current Plan/Task Spec/Card/Master Card and handoffs,
   visible bindings, dependencies, model profile, authorization envelope, and applicable SOP.
3. Validate every available current record before changing any record, file, ref, or external target:

   ```bash
   python3 scripts/validate_contracts.py \
     --plan <CURRENT_PLAN_JSON> \
     --task-spec <TASK_SPEC_JSON> \
     --worker-card-json <WORKTREE_TASK_JSON> \
     --master-card-json <MASTER_CARD_JSON>
   ```

   For a transition with retained snapshots, add the matching `--previous-plan`,
   `--previous-worker-card`, and `--previous-master-card` options. Run the command from the repository
   whose contracts are being checked; `--repo-root` remains the existing Skill-source-root option.
4. Confirm the requested paths, dependency/ownership edges, frozen full SHA, plan/task/card identity,
   model profile, and complete authorization are exactly the persisted values. A denied capability is
   explicit `false`/`null`/`0`; it is never inferred from a test, model, message, or service tier.
5. Select exactly one route. A governance, protocol, Schema, state, authorization, persistence,
   release, security, production, irreversible, long-recovery, or uncertain request is not FAST.

**Continue condition.** Every applicable identity, ownership, baseline, status, scope, dependency,
authorization, and validation check is `PASS` or an explicitly inapplicable `NONE`; the operator can
   name the owner and next legal step.

**Stop condition.** Any mismatch, duplicate visible binding, non-IDLE FAST Card, unexpected dirty or
untracked material, missing evidence, forbidden path, unclear owner, stale digest, or authority gap
immediately becomes `STOP_AND_PRESERVE`. Do not mutate the Plan, Card, Git state, release evidence, or
external target while deciding what to do next.

**Minimum retained evidence.** Keep the operation identity, worktree/branch/full SHA and status,
preserved material, records and digests checked, route decision, owner, commands and results, and any
separate external authorization in the existing task, Plan, handoff, review, or release projection.

## Command and evidence classification

The map names operations that already exist. Classification describes the effect of the operation; it
does not grant authority.

| Class | Existing command or evidence | Use and owner boundary |
| --- | --- | --- |
| Read-only | `git status --short --branch`, `git rev-parse HEAD`, `git branch --show-current`, `git worktree list --porcelain`, `git diff --name-only`, `git log`, and reading Plan/Task Spec/Card/handoff files | Establish identity, ancestry, status, preserved material, and ownership before mutation. Any operator may inspect; never infer authority from the output alone. |
| Validation-only | `python3 scripts/validate_contracts.py` with the applicable current/previous record options; `PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py'`; `git diff --check`; available Skill Creator `quick_validate.py` | Prove contract shape, cross-record history, tests, and diff integrity. Validation must precede each state-changing step; a passing test does not grant external authority. |
| Local state-changing | `git add <owned-paths>` and `git commit -m '<message>'`; ordinary Master-owned `git merge`/`git cherry-pick` integration; `git worktree add` when a separately approved STRICT topology requires it | Changes local Git or coordination state. Workers commit only their allowed paths and never integrate or create extra worktrees; Master owns integration and topology decisions. A handed-off commit is immutable. |
| Local state-changing | `python3 scripts/worker_card_sidecar.py --repo-root <MASTER_WORKTREE> --plan <PLAN_JSON> --master-card-json <MASTER_CARD_JSON> --task-id <TASK_ID> --transition --card-json <COMPLETE_CARD_JSON>` | The official atomic Worker Card transition. Use only for the bound Worker's legal transition or an explicitly recorded Master bootstrap/takeover; it changes no Plan, Master Card, Markdown, Git, or external state. |
| Local state-changing | `python3 scripts/close_release.py --repo-root <MASTER_WORKTREE> --plan <PLAN_JSON> --master-card-json <MASTER_CARD_JSON> --worker-card-json <WORKER_CARD_JSON> --release-task-id <RELEASE_TASK_ID>` | Master-only local closeout after all closeout gates and the publication decision. It writes the exact existing three-file archive; it is not publication, cleanup, or deletion authority. |
| Local state-changing | `python3 scripts/rollover_release.py --repo-root <MASTER_WORKTREE> --plan <PLAN_JSON> --master-card-json <MASTER_CARD_JSON> --next-plan-json <NEXT_PLAN_JSON> --next-master-card-json <NEXT_MASTER_CARD_JSON>` | Master-only next-release transition after verified closeout. It writes the existing immutable rollover receipt and forward compare-and-swap records; it is not a rollback or Worker dispatch grant. |
| Local state-changing (separate destructive authorization) | Deletion, cleanup, or branch/ref removal | These are not implied by closeout, `IDLE`, rollover, or any other route. Prove the exact target and independent destructive scope immediately before any such local mutation; never batch or wrap it here. |
| Separately authorized external mutation | `git push <remote> <ref>`, production publication/deployment, or external service calls | Never hide these behind a new wrapper or infer them from Candidate approval, tests, closeout, model profile, or Card state. Each exact target, scope, and capability needs its own current authorization immediately before use. |

The `close_release.py` and `rollover_release.py` entries are existing local state transitions, not new
records or new authority. No command in this map combines validation with publication, push, deletion,
cleanup, or another external mutation.

## FAST route — short path only

**Enter when.** The universal gate proves one current task and worktree, no independent parallel
responsibility or extra worktree, a relevant Card absent or `IDLE`, no active Dispatch assignment or
competing durable role binding, clear current-role ownership, bounded local verification, and no
governance/protocol/Schema/state/authorization/persistence/release/security/production/irreversible or
long-recovery impact. Any uncertainty enters STRICT or stops.

**Owner.** The current task/role owns the local change. No Master/Worker coordination records are
created for the FAST operation.

**Ordered steps.**

1. Complete the universal gate and record the FAST decision as human evidence.
2. Modify only the current-role-owned paths in the current worktree. Do not create or change a Plan,
   Task Spec, Worker Card, Master Card, extra worktree, cycle fence, adoption record, Operation Receipt,
   or v2 behavior.
3. Run bounded local validation and tests, then `git diff --check` and a complete diff review.
4. If all checks pass, use the existing local `git add` and `git commit`; record the resulting SHA and
   status. If a check fails, make at most the permitted local correction; further uncertainty or scope
   growth exits FAST.
5. Report the result and retained evidence. A requested push or other external action is a separate
   decision and authorization after the local result; FAST never grants it.

**Continue condition.** The bounded change, local checks, complete diff, and commit all remain within
the original owned scope, with no new record or authority required.

**Stop or upgrade condition.** Stop immediately for a failed/ambiguous gate, a second unresolved local
correction, ownership or scope drift, a non-IDLE Card/active assignment/competing binding, or any
request for coordination, persistence, release, production, external, destructive, synchronization,
or v2 behavior. Route the affected work to STRICT or exception recovery; do not create STRICT records
from the FAST path as a workaround.

**Minimum evidence.** Pre/post Git truth, owned changed paths, commit SHA/subject, local check results,
preserved material, and the separate decision for any external action. Use the [Task Lifecycle SOP](task-lifecycle-sop.md)
for the detailed FAST/STRICT boundary.

## STRICT task route — complete delivery path

**Enter when.** FAST is ineligible, or the work is governed by a Plan, Task Spec, Card, persistent
recovery, parallel responsibility, contract, security, release, or other strict boundary.

**Owner.** Master owns discovery, Plan/Task publication, Dispatch, handoff review, integration, and
release readiness. The Worker owns only its assigned paths and evidence.

**Ordered steps.**

1. Master performs read-only discovery of role/conversation/worktree bindings, dependencies, current
   Git truth, preserved material, and authority. Master persists the complete Task Spec and Plan with
   exact digests and fences before publishing the assignment.
2. Validate the persisted Task Spec/Plan/Master Card and the target worktree before mutation. Activate
   the canonical Worker Card through `worker_card_sidecar.py` only after identity, baseline, scope,
   model, authorization, and acceptance match.
3. Worker repeats the identity/baseline/status/scope preflight, changes only allowed paths, runs
   affected checks, reviews the complete diff, and creates one atomic local commit. Worker then records
   `AWAITING_INTEGRATION` through the official sidecar; it does not alter Plan/Master state or integrate.
4. Master validates the complete handoff against the frozen baseline, Task Spec/Plan/Card identities,
   authorization, commit ancestry, scope, checks, and preserved material. A rejected or unproven
   handoff is not integrated; use the exception/rework route.
5. Master integrates the accepted commit with the repository's ordinary approved Git action, then
   recomputes derived projections and reruns validation from the integrated tree. Integration is a
   local state change owned by Master; it is not a publication action.
6. Master records the Worker-to-integrated SHA mapping and, after acceptance evidence is complete,
   the Worker returns its Card to `IDLE` through the legal sidecar transition. A Worker-only rework
   does not change the existing candidate evidence.

**Continue condition.** Every assignment, handoff, integration, projection, and validation check is
current and independently evidenced; the integrated Master tree is the only source for release gates.

**Stop condition.** Any stale digest/revision, wrong baseline or worktree, dirty/overlapping material,
missing handoff evidence, forbidden path, failed check, or integration conflict with unknown ownership
stops the affected path. Preserve the state and use the [Exception and Recovery SOP](exception-recovery-sop.md);
never make a Worker resolve it by reset, rebase, merge, synchronization, or scope expansion.

**Minimum evidence.** Persisted Task Spec/Plan/Card/Master identities and digests, full baseline and
result SHAs, dependency/ownership checks, complete changed paths, test and diff results, handoff,
integration mapping, Card state, and any unresolved finding. Use the [Task Lifecycle SOP](task-lifecycle-sop.md)
for the authoritative state transitions.

## Conditional release route — integrated tree first

**Enter when.** Master has an accepted STRICT handoff and the release task is ready for release-candidate
gates. This route is never entered from an unintegrated Worker branch.

**Owner.** Master owns candidate evidence, candidate approval, closeout, and rollover. An authorized
release role owns any production publication or external push under a separate grant.

**Ordered steps.**

1. Confirm integration is complete for the intended scope and identify the exact integrated Master
   `release_head_sha`. Recheck Plan, handoffs, Cards, dependencies, and dirty/untracked material.
2. Run contract validation, affected/shared/base-relative checks, and the release-candidate gates from
   the integrated tree. Recompute all required input, provenance, and evidence digests; a changed
   integrated HEAD makes prior candidate evidence stale.
3. Master approves or rejects the candidate only after the current per-Gate evidence proves the exact
   integrated identity. Candidate approval is a local Master record decision and grants no publication,
   push, deployment, deletion, or other external authority.
4. Make the publication decision separately. If publication is approved, obtain and verify the fresh
   exact external authorization, then perform only the explicitly bounded external action (for example
   `git push <remote> <ref>`) and retain its result. If publication is not approved, do not perform it.
5. After the publication decision and any required publication verification, confirm all closeout
   prerequisites: terminal Plan and handoffs, all bound Worker Cards `IDLE`, exact final Git HEAD,
   fresh schema-v2 `PASSED` Candidate evidence, and complete archive inputs.
6. Master runs the existing `close_release.py` command only after validation-before-mutation succeeds.
   Verify the exact three-file closeout archive and live Master readback; closeout is local archival
   state, not publication or deletion.
7. Only after verified closeout, Master stages the next independent Plan and Master Card and runs the
   existing `rollover_release.py` command. Verify the immutable receipt and forward live-record
   readback before any new dispatch. Do not rediscover old Worker directories or reuse old evidence as
   the new release.

**Continue condition.** The ordered chain is proven as `integration → integrated-tree validation →
candidate approval → separate publication decision/action → closeout → verified closeout → rollover`.
If publication is not authorized, the external action is omitted; no earlier or later step inherits
that authority.

**Stop condition.** Stop and preserve on any non-integrated candidate input, stale/missing Gate evidence,
head or provenance mismatch, incomplete terminal history, non-IDLE bound Card, archive conflict,
publication authorization gap, dirty/unreachable Git state, or rollover interruption outside the
documented forward-recovery bytes. Candidate invalidation is not a failed publication; it is a reason to
rerun the affected release gates.

**Minimum evidence.** Exact integrated HEAD/tree, current Plan/Master/Card/handoff identities and
digests, per-Gate input/result/provenance evidence, candidate approval decision, separate publication
authorization and result (or explicit no-publication decision), closeout archive bytes/digests, and
rollover receipt/readback. Use the [Release SOP](release-sop.md) for the full release boundaries.

## Interrupting exception route — STOP_AND_PRESERVE

**Triggers.** Wrong identity, source, role, generation, worktree, branch, baseline, Plan/Task/Card
revision or digest; unexpected dependency; dirty or overlapping user material; duplicate visible
conversation; missing/expired/ambiguous authorization; failed validation; forbidden path; candidate or
archive conflict; or any request to reset, rebase, merge, synchronize, publish, delete, clean up, or
expand scope without its exact authority.

**Owner.** The discovering Worker or operator immediately preserves and reports facts. Master owns the
legal decision to gate, revise, supersede, cancel, take over, integrate, or resume.

**Ordered steps.**

1. Immediately stop implementation and all external activity. Do not make a “repair” commit, reset,
   rebase, merge, synchronize, delete, clean up, or overwrite evidence.
2. Capture read-only Git truth and the complete current record identity: current SHA/status/changed and
   untracked paths, task/Plan/Card revisions and digests, owner, expected fact, observed fact, and the
   command or record that proves the mismatch.
3. Preserve the current material. For an active Worker task, use the official sidecar to record
   `BLOCKED` only after the complete blocker evidence is ready; this local state change grants no
   recovery or external authority. If activation has not occurred, leave the records untouched and
   report to Master.
4. Master selects the narrowest legal recovery under the Exception and Recovery SOP. An in-scope
   correction uses a higher Task Spec revision; changed objective/owner/worktree/baseline/authority
   uses a superseding task. A committed or handed-off commit remains immutable.
5. Resume only after the new or recovered identity, baseline, scope, authorization, and evidence pass
   the universal gate and all required validation is rerun.

**Continue condition.** Master has recorded the recovery decision and legal transition, preserved
material is accounted for, and a fresh validated assignment or unchanged valid path exists.

**Stop condition.** Any unresolved identity, ownership, baseline, scope, authorization, recovery owner,
or preserved-material gap remains `NOT_PROVEN`; keep the affected lock/evidence visible and wait for
Master. The exception route never authorizes external mutation, deletion, cleanup, or synchronization.

**Minimum evidence.** Exception report with actual/expected facts, full SHA/status/paths, task and Plan
identity, blocker kind and recovery owner, preserved material, authorization actually used (normally
none), and Master decision. Use the [Exception and Recovery SOP](exception-recovery-sop.md).

## Conditional governance and conversation-rotation routes

**Enter when.** The operation audits execution, adopts MWR, changes an SOP, retains/retires evidence, or
creates/rotates/archives a persistent conversation. Governance routes are human routing only and do not
override contracts or create a registry. A governance document change normally follows the STRICT task
route for its commit and integration.

**Owner.** Master or the existing project owner makes governance and persistent conversation decisions.
Workers and auditors collect/report evidence only. Conversation lifecycle remains solely governed by the
[Conversation Rotation SOP](conversation-rotation-sop.md).

**Ordered route selection.** After the universal gate and validation, use exactly the applicable existing
runbook:

| Condition | Existing route | Continue evidence | Stop condition |
| --- | --- | --- | --- |
| Audit of an actual FAST, STRICT, release, recovery, adoption, change, retention, or rotation operation | [SOP Compliance Audit](sop-compliance-audit-sop.md) | Current owner, identity, evidence, authorization, and applicable SOP checks are independently proven | Missing, stale, ambiguous, or contradictory evidence is `NOT_PROVEN`; stop the affected decision. |
| MWR self-maintenance or another project adoption | [Project Adoption](project-adoption-sop.md) | Inventory, ownership/binding map, state-root policy, source pin, bounded pilot, and exit path are proven | Do not enable v2, replace runtime authority, create an adoption registry, or proceed with unproven pilot evidence. |
| Editorial/normative SOP proposal, freeze, deprecation, or rollback | [SOP Change Governance](sop-change-governance-sop.md) | Class, owner/reviewer, complete diff, compatibility, release-batch impact, and rollback are proven | Semantic ambiguity, silent in-flight change, contract/runtime scope, or missing review routes to exception recovery. |
| Retention, archive, retirement, or deletion-boundary review | [Retention and Retirement](retention-retirement-sop.md) | Exact target, references, preserved bytes, obligations, owner, and any independent destructive scope are proven | Archive is not deletion; missing exact destructive authority stops and preserves, with no automatic cleanup. |
| Conversation creation, successor confirmation, rotation, or predecessor archive | [Conversation Rotation](conversation-rotation-sop.md) | Master verifies the same role/worktree/branch, blank successor by default, read-only bootstrap, explicit confirmation, and predecessor visibility | Wrong HEAD/worktree, duplicate visible conversation, missing confirmation, or Worker self-archive is immediate `STOP_AND_PRESERVE`. |

For a governance or rotation change, continue through the STRICT integration and release routes when the
operation changes tracked documentation or release inputs. Do not modify an existing SOP body from this
map when the current Task Spec forbids it. Adoption, FAST binding, v2, deletion, publication, and
conversation archive decisions never inherit one another's authority.

## Final operator rule

Validation comes before every mutation. Integration comes before candidate generation or approval.
Candidate approval and publication authorization are separate. Closeout follows the publication decision
and its required verification. Rollover follows verified closeout. Any missing or ambiguous evidence is
`NOT_PROVEN`; any contradiction or unsafe interruption is `STOP_AND_PRESERVE` until Master or the
existing owner records the next legal decision.
