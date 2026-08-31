# E2E Authority Boundaries Audit

Status: strict, read-only authority audit. This document records contract and temporary-fixture evidence; it does not
perform or claim a release closeout, external call, execution, integration, push, publication, or destructive operation.

## 1. Audit identity and conclusion

The audit was run for `mwr-audit-e2e-authority-boundaries`, Task Spec revision `1`, under Dispatch Plan revision `38` and
dispatch wave `1`.

| Fact | Verified value |
| --- | --- |
| Worktree | `/Users/lidaohang/.codex/worktrees/af6f/multi-worktree-release` |
| Branch | `codex/authorization-model-e2e-1` |
| Frozen baseline / observed HEAD | `73265ee5121523f798d9fc5e909ba2eb4467bd37` |
| Task Spec | `/Users/lidaohang/Projects/multi-worktree-release/.codex/multi-worktree-release/tasks/mwr-audit-e2e-authority-boundaries.json` |
| Task Spec digest | `sha256:b49116e056106a2c70744795a3a2b11fde8ef764530b0b08e42863588b21f38a` |
| Dispatch Plan | `/Users/lidaohang/Projects/multi-worktree-release/.codex/multi-worktree-release/dispatch-plan.json` |
| Dispatch Plan record / semantic revision | `59 / 38` |
| Dispatch Plan digest | `sha256:9ce280c57030833d243fba81c7f983f2cfea749bb75cb60429dc9b8a4c2b9305` |
| Current Dispatch status | `PUBLISHED` |
| Worker Card | `ACTIVE`, record revision `11` |
| Model profile | `gpt-5.6-luna`, reasoning `max`, service tier `priority`, `owner-default:complex-worker` |
| Authorization envelope | v2 canonical default-deny, `sha256:0173395a7243a00d172211fc489e18f2195189792a89e4e77da3b34537376106` |

The central result is a three-stage boundary: validate the immutable assignment and its message projection, validate the
candidate Worker lock against the Plan and Task Spec, and only then write `ACTIVE`. A mismatch stops at the first failed
stage. A closeout or integration action cannot repair a mismatch by changing a Worker Card, Task Spec, Plan, branch, or
baseline in place.

## 2. Capability and authority matrix

The v2 envelope is complete default-deny for this audit. All four grants are independent and are not inferred from a role,
model profile, branch name, handoff, closeout status, or message.

| Capability | `allowed` | `target` / route / provider | `max_calls` / `max_cost` / unit | Fresh/resume |
| --- | --- | --- | --- | --- |
| `external_call` | `false` | `null` / `null` / `null` | `0` / `0` / `null` | not present in this grant |
| `create_execution` | `false` | `null` / `null` / `null` | `0` / `0` / `null` | `fresh_execution_required=true`, `resume_execution_id=null` |
| `publish` | `false` | `null` / `null` / `null` | `0` / `0` / `null` | not present in this grant |
| `destructive_operation` | `false` | `null` / `null` / `null` | `0` / `0` / `null` | not present in this grant |

`controlled_input`, `controlled_input_digest`, and `expires_at` are all `null`. The envelope digest above covers the whole
canonical object. A later action would need a newly published, capability-specific, action-time authorization; no field in
this audit can be promoted into that authority.

The following matrix separates the owner of each authority from the records and projections that merely reference it.

| Actor or boundary | Reads | May write or act, when separately authorized | Explicitly cannot do | Required fence/evidence |
| --- | --- | --- | --- | --- |
| Worker | Its exact Task Spec, Plan entry, Worker Card, own worktree, Git status/HEAD, and local acceptance inputs | Only the allowed paths in its own worktree, its own local checks, and its own Card transition required by the current assignment | Change the assignment, repair a baseline, modify the Plan or Task Spec, merge, rebase, reset, synchronize, push, call an external service, create an execution, publish, or perform destructive cleanup | Exact task identity, Plan/task digest, worktree, branch, baseline, allowed paths, and v2 authorization; handoff is `RECEIVED` evidence, not release authority |
| Master orchestration | All persisted Plan/Task Specs/Cards, Git evidence, handoffs, and release records | Publish or revise assignments, accept/reject handoffs, update Master-owned state, integrate an immutable Worker commit, and perform closeout steps inside the exact local state root | Treat a message, model profile, Worker handoff, candidate status, or closeout as production publication; silently rewrite terminal records; grant a capability absent from an action-time envelope | Current Plan and record revisions, immutable task digests, append-only handoff identity, explicit recovery/revision decision, and separate action-time authorization |
| Closeout utility | The exact local `state_root`, current Master Card, Plan, accepted handoffs, and closeout inputs | If a future Master-authorized utility exists, atomically write only validated closeout state beneath `/Users/lidaohang/Projects/multi-worktree-release/.codex/multi-worktree-release` and the live Master Card selected by Master | Write a Worker Card, Task Spec, Dispatch Plan, branch, worktree, or tracked design; push; make an external call; create an execution; delete or clean material; create a Tag or Release; or claim production publication | Exact `state_root`, current Master/Card identity, complete pre/post digest evidence, and a separate closeout authorization. This repository has no tracked closeout utility, so this audit only defines the boundary |
| Git integration | Immutable Worker commit, Plan entry, Task Spec, Worker Card, and Master handoff | Master may map one accepted `worker_commit_sha` to one `integrated_as_sha` and validate the resulting tree | Worker-side integration, history rewriting, synchronization, force-push, tag, release, deployment, or publication | Accepted `RECEIVED` handoff, unchanged Worker SHA, explicit Master mapping, and a new candidate identity for the integrated head |
| Normal `origin/main` push | Local Git state and the exact remote/ref specification | Master only, and only after separate action-time user authorization for that exact non-force ref; it is a Git publication outcome, not a production release | Worker push, force-push, tag or release creation, deployment, protected publication, or production claim; closeout authorization does not imply a push | Exact ref, commit, authorization use, checks, and receipt. No push was authorized or attempted in this audit |

The closeout boundary is intentionally narrower than an ordinary workflow description: a state write under the exact local
`state_root` does not grant Git, network, execution, destructive, Tag, Release, or production-publication authority. If a
closeout record cannot be written atomically or its digest does not verify, the prior valid state and preserved material stay
in place and Master marks the affected action blocked.

## 3. Pre-ACTIVE gate

An executable assignment message is a transport projection. Its normative content remains the persisted Task Spec and Plan;
the message identity is `task_id + task_spec_revision + source_thread_id`, while `task_spec_digest` proves content equality and
`plan_revision` is a fencing token. The pre-ACTIVE sequence is:

1. Verify the exact worktree, branch, frozen baseline, Task Spec digest, Plan digest, dispatch status, model profile, and
   authorization digest.
2. Validate the complete Task Spec and Plan, including the persisted Task Spec path and the Plan-to-Task-Spec digest binding.
3. Validate the candidate Worker Card shape and compare its assignment lock to the Plan and Task Spec.
4. Validate the message publisher binding (`source_thread_id` to the Plan's `issued_by`) and all acceptance/authorization
   projections.
5. Only after all checks pass may the Worker Card transition from `IDLE` to `ACTIVE`. No negative path writes that state.

The following are hard stops before activation:

- A Worker `frozen_baseline_sha` different from the Plan entry's `expected_head` or the Task Spec's `expected_head`.
- A changed executable Task Spec payload, including `commit_message`, whose newly computed digest is not the digest published
  in the Plan and message projection.
- A message whose source thread is not the Plan issuer for a `NEW` or `REVISE` assignment.
- A changed objective, owner role, worktree, expected starting commit, or authorization boundary presented as an in-place
  revision. These require a successor Task Spec and `supersedes_task_id` lineage.

The model profile is checked independently. `gpt-5.6-luna / max / priority` identifies routing policy; it is not a grant for
external calls or execution. If the launcher cannot honor the persisted profile, work stops rather than substituting a
different profile.

## 4. Supersession and revision boundary

`classify_task_change` makes the authority boundary explicit:

| Change from the published assignment | Required classification | Consequence |
| --- | --- | --- |
| `objective`, `owner_role`, `worktree`, `expected_head`, or `authorization` | `SUPERSEDE` | Publish a new assignment with a new identity and, where applicable, `supersedes_task_id`; preserve the predecessor as terminal history |
| Acceptance or other in-scope executable content | `REVISE` | Increase `task_spec_revision`, compute a new `task_spec_digest`, bind the revision to the current Plan revision, and republish |
| Only a later Plan fence with unchanged assignment content | `GRANDFATHER` | Preserve the original Task Spec, digest, publisher, and original Task Spec Plan fence |

Neither a successor nor a later Plan inherits a predecessor's authorization by implication. A successor carries its own
complete envelope and its own digest. A changed baseline cannot be repaired by synchronizing the worktree to a newer commit;
that is a supersession decision owned by Master.

## 5. Isolated temporary-fixture evidence

The negative tests used only a system-created temporary directory. They wrote candidate JSON files under that directory,
loaded them through the repository's Schema-first Python validator, and removed the directory on exit. The live Plan, Task
Spec, Worker Card, branch, HEAD, and existing commits were read only.

| Fixture | Mutation in the temporary copy | Observed result |
| --- | --- | --- |
| Baseline mismatch | Structurally valid candidate Worker Card with `frozen_baseline_sha="f" * 40` | `REJECTED before ACTIVE: [H20] Plan/Worker identity mismatch: ['frozen_baseline_sha']` |
| Executable message mismatch | Temporary Task Spec changed its `commit_message`, recomputed its own digest, while the published Plan retained the old `task_spec_digest` | `REJECTED before ACTIVE: plan/task-spec mismatch ... ['task_spec_digest']` |
| Publisher/message identity mismatch | Temporary internally valid Task Spec used `source_thread_id="untrusted-message-source"` | `REJECTED before ACTIVE: Task Spec publisher mismatch ...` |
| Immutable objective change | Changed only `objective` in the comparison fixture | `SUPERSEDE` |
| Immutable baseline change | Changed only `expected_head` in the comparison fixture | `SUPERSEDE` |
| Ordinary executable-content control | Added one acceptance item with higher revision and a new digest | `REVISE` |

The temporary fixture root was absent after cleanup (`temporary_fixture_cleanup=True`). The live-state manifest was computed
from branch, HEAD, raw Dispatch Plan bytes, raw Task Spec bytes, and raw `WORKTREE_TASK.md` bytes before and after the
fixtures:

```text
branch: codex/authorization-model-e2e-1
head: 73265ee5121523f798d9fc5e909ba2eb4467bd37
dispatch-plan.json bytes: 985df7e9d3e879c675163b07b4c3303966c8b45bd13d8b1022f2ed5ab96868ae
Task Spec bytes:         b44e33a80cf8425f7fe8d2240de3ff517d6411e1456b65dc291755bfa557d4a0
WORKTREE_TASK.md bytes:  229e90ac065ecc83905b234bc81143d60e5ab08f346e86ddc82ad7d3b749827c
manifest before:         sha256:844df13993cf674f67f98c649a650378e881340c07a0ef2188adcd5eeb91f276
manifest after:          sha256:844df13993cf674f67f98c649a650378e881340c07a0ef2188adcd5eeb91f276
live_state_unchanged:    True
```

This proves non-corruption of the live state for the tested rejection paths. It does not claim that the repository contains a
production activation or closeout dispatcher; the current proof is a contract-level gate exercised with isolated inputs.

## 6. Closeout lifecycle and non-inheritance

Closeout is a Master-owned state transition after delivery evidence has been accepted. It is not a Worker completion message
and not a capability escalation:

```text
immutable assignment
  -> pre-ACTIVE identity/binding gate
  -> Worker ACTIVE and owned local checks
  -> RECEIVED handoff
  -> Master integration mapping
  -> closeout state under exact local state_root / live Master Card
  -> separate release candidate and Gate evidence
  -> separate action-time publication authorization
```

The closeout step may record the accepted handoff, integration mapping, preserved material, checks, and current record
digests. It may not:

- rewrite a Task Spec, Plan entry, Worker assignment, branch, or frozen baseline to make the closeout pass;
- treat an integrated commit as a release candidate without the release-plan and Gate evidence required by the STRICT mode;
- infer `publish`, `external_call`, `create_execution`, or `destructive_operation` from a successful handoff or candidate;
- create a Tag, Release, deployment, production publication, or remote reference;
- delete temporary or preserved user material as an unbounded cleanup operation; or
- synthesize a publication receipt when no publication was attempted.

An ordinary, explicitly authorized non-force `origin/main` push is a separate Git action and receipt. It does not become
available because closeout succeeded, and it is not a production-release claim. This audit performed no such action.

## 7. Checks, limitations, and findings

The identity preflight and isolated fixtures passed. The required repository checks for this audit are recorded below after
the document was written:

| Check | Result |
| --- | --- |
| Exact Task Spec digest and persisted-object digest | PASS |
| Exact Plan digest and persisted-object digest | PASS |
| Worktree, branch, frozen baseline, dispatch status | PASS |
| v2 default-deny authorization and envelope digest | PASS |
| Task Spec/Plan/Worker model profile parity | PASS |
| Temporary-fixture cleanup and live-state hash equality | PASS |
| `python3 scripts/validate_contracts.py` | PASS |
| `git diff --check` | PASS |
| External call / execution / publication / destructive operation / push | NOT USED |

No unresolved authority violation was found within the audited scope. One implementation gap remains intentionally explicit:
there is no tracked production closeout utility in this baseline. A future Master-owned implementation must bind any closeout
writer to the exact local `state_root` and live Master Card, use atomic validated persistence, and keep all capability grants
and Git/publication actions separate. This audit neither implements nor authorizes that utility.

No candidate evidence, release evidence, publication receipt, remote reference, or production release is created or claimed by
this document.
