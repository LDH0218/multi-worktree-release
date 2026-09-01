# Release SOP

This is the Master-owned operator procedure from an accepted Worker handoff through integrated-tree
candidate evidence, explicit publication, push verification, local closeout, and the next-release
rollover. It uses the existing v1-authoritative Plan, Cards, handoffs, Candidate evidence v2, Schema,
validator, and release scripts. It adds no release state, contract field, role registry, or authority.
The [Task Lifecycle SOP](task-lifecycle-sop.md) governs task delivery; the
[Exception and Recovery SOP](exception-recovery-sop.md) governs failed checks. Conversation creation,
rotation, successor confirmation, and archive decisions remain solely in the
[Conversation Rotation SOP](conversation-rotation-sop.md).

## The release boundary

Keep these outcomes separate:

| Outcome | Minimum evidence | Owner/authority |
| --- | --- | --- |
| Integration complete | `worker_commit_sha → integrated_as_sha` for the accepted handoff, with the Master tree reviewed | Master |
| Release candidate passed | Current schema-v2 per-Gate evidence bound to the exact `release_head_sha`, all required Gates `PASSED` | Master |
| Publication/push complete | A current explicit publication authorization covers the exact target/ref, plus verified remote or release-system evidence | Authorized release role |
| Local closeout complete | Validated terminal Plan, terminal handoffs, all Worker Cards `IDLE`, fresh candidate `PASSED` for the final HEAD, and the exact three-file archive | Master |

Candidate approval never authorizes publication, push, deployment, execution, destructive action, or
external calls. Closeout never grants any of those authorities. Production release is complete only
when the release system supplies evidence under a current authorization; a local archive is not a
production release.

## 1. Finish integration in the Master tree

For each Worker handoff, Master:

1. Checks task/Plan revision, digest, source, baseline, allowed paths, model, authorization, Card state,
   commit reachability, ancestry, and the complete patch.
2. Integrates only the intended change. A Worker-only rework that has not been integrated does not change
   the current candidate. Mechanical generated-output conflicts are resolved by regenerating from
   integrated sources; semantic conflicts return to the owning Worker.
3. Records the exact `worker_commit_sha → integrated_as_sha` mapping, changes the matching handoff to
   `INTEGRATED`, and recomputes generated projections, hashes, indexes, lock files, and other derived
   outputs from the integrated Master tree.
4. Confirms the Master tree and preserved material are the expected state before candidate work. A new
   integrated HEAD changes the candidate identity and invalidates all prior Gate evidence.

Do not infer integration from branch-ahead counts, a matching patch, a chat acknowledgement, or a Worker
Card alone.

## 2. Generate and re-authenticate the candidate

The effective candidate identity is exactly:

```text
(release_task_id, release_head_sha)
```

Use the exact final integrated `release_head_sha`, its tree, the current Plan/Task/authorization inputs,
and the embedded current Gate registry. Recompute, from the integrated tree, every applicable Gate and
check input digest, command/provenance/result/artifact evidence digest, compatibility gate-input digest,
and aggregate status. The registry, stable IDs, revisions, requiredness, runner policy, source mapping,
and evidence must be independently verifiable.

Gate freshness rules:

- Any changed integrated `release_head_sha` makes every Gate stale; do not reuse evidence by patch or
  tree equivalence.
- For the same head, a changed acceptance, authorization, Task Spec, registry, toolchain, or projection
  source stales each dependent Gate when the registered source map is complete. A status-only Plan write
  does not stale an unrelated Gate by itself.
- Missing/unknown membership, requiredness, source mapping, provenance, digest recomputation, revision
  fence, or atomic persistence clears asserted evidence and uses the whole-candidate `STALE` fallback.
- Infrastructure errors and unverifiable provenance are `STALE`, never `FAILED` or `PASSED`. A mapped
  `STALE` or `NONE` row uses only a Schema-enumerated invalidation reason.
- Aggregate missing, `NONE`, or `STALE` before valid `FAILED`, and valid `FAILED` before all `PASSED`.
  An optional (`required: false`) Gate is reported but does not decide the required result; an empty
  required set cannot pass.

Current release authority requires Candidate evidence v2 with current per-Gate evidence. Evidence-bearing
v1 aggregate records remain immutable audit input under `legacy`; they are not promoted to current
`PASSED` or `FAILED`. A legacy rerun must keep the same release task and a non-regressing Plan fence,
remove `legacy`, rerun every current Gate including optional Gates against the exact new head, and reuse
no opaque legacy digest or evidence.

Master may declare a release candidate only when every required current Gate is `PASSED`, all required
source/provenance/digests bind to the same integrated head, and no required evidence is `NOT_PROVEN`.
Record the candidate status and exact candidate evidence before moving to publication.

## 3. Separate publication authorization from candidate approval

Before any push or production/release-system mutation, verify all of the following in a fresh read-only
check:

- the candidate still names the exact current integrated `release_task_id + release_head_sha`;
- the target repository, ref/path scope, route/provider, and any other target fields are the exact
  bounded target in the current authorization envelope;
- the publication grant is explicitly allowed, unexpired, digest-valid, and within its call/cost limits;
- any external-call, execution, or destructive capability needed by the release is separately authorized;
  candidate evidence and closeout do not lend it authority; and
- the release role and operator are the authorized owner for that mutation.

If any item is absent or `NOT_PROVEN`, stop with the candidate retained as an internal result. Do not
silently treat a `PASSED` candidate as permission to publish. A force push, deletion, rollback, or other
destructive ref mutation requires its own explicit destructive authorization; it is never implied by a
normal publication grant.

## 4. Push and release verification

When the authorized release role performs a push or release-system mutation, it first records the exact
target/ref and expected commit, then performs only that bounded action. Afterward it verifies the remote
or release-system result by reading the target ref/status and confirming it resolves to the expected
commit and release identity. Record the actual authorization and resulting evidence.

A failed, partial, ambiguous, or unverifiable push is not a successful release. Stop without force-push,
cleanup, rollback, or a second unbounded attempt; preserve the candidate, local refs, target evidence,
and error for the authorized release owner. A local candidate or closeout may remain valid for its exact
head, but it never proves that the remote mutation succeeded.

## 5. Master-owned local closeout

Closeout is a separate local recovery/archive step after publication decisions; it is not publication and
does not need to be bundled with a push. Run it only when all of these preconditions pass:

- the current v1 Plan is standalone-valid and every Dispatch entry is terminal;
- every Master handoff is terminal and every bound Worker Card is `IDLE`;
- the exact final Git HEAD is clean/reachable and matches fresh schema-v2 candidate evidence with
  `status: PASSED` and `legacy: null`; and
- the release identity, Plan fence, candidate identity, handoff mappings, and preserved material are
  consistent. Any `NOT_PROVEN` precondition blocks closeout.

Use the repository-owned `scripts/close_release.py` procedure with explicit Plan, Master Card, Worker Card,
and release identifiers when required. It validates before writing and creates exactly:

```text
state_root/history/releases/<release_task_id>/
├── dispatch-plan.json
├── master-card.active.json
└── closeout.json
```

Preserve the exact source Plan and ACTIVE Master Card bytes and the complete ordered handoff array.
Install the three files with same-directory, no-overwrite atomic writes in Plan → ACTIVE Master →
closeout order. Only after readback verification may the live Master Card become `IDLE` with the canonical
empty candidate and cleared lock. Closeout never clears a Worker Card, archives a conversation, deletes a
worktree/branch/history, or authorizes push, release, deploy, execution, external calls, destructive
actions, or v2 adoption.

### Idempotency and interruption

- Equal existing archive bytes are idempotent and may be verified again.
- Different bytes, changed Plan/Master/candidate/Git inputs, incomplete history, unsafe paths, dirty or
  unreachable state, or an interrupted write fail closed. Preserve the live Master `ACTIVE` lock and all
  evidence; do not overwrite, clean, rollback, or create an alternate archive.
- A recovery attempt must revalidate the exact source bytes and all preconditions before continuing. A
  partial archive is not proof of closeout; only exact no-overwrite/readback evidence can complete it.

## 6. Open the next independent release

After and only after a verified closeout, Master uses the Master-owned `scripts/rollover_release.py`
procedure. Rollover is not an ordinary Plan status transition and never rewrites the closed release.

1. Validate the archived Plan, archived ACTIVE Master snapshot, closeout digest, archived byte digests,
   terminal handoff count/digest, reachable historical release HEAD, and the exact live `IDLE` Master
   projection.
2. Stage a target Plan and Master independently. The target release ID differs; Plan and record revisions
   start at `1`; the target contains only new Task Specs; the target Master is `ACTIVE` with an empty
   handoff list and canonical empty candidate; and the target baseline and every initial Task Spec
   baseline equal the current clean Master HEAD.
3. Install exactly one immutable rollover receipt at
   `state_root/history/rollovers/<next-release-task-id>.json`, then compare-and-swap the live Plan and
   Master in order and validate the readback.
4. If interrupted after only the Plan replacement, use the receipt and exact staged target bytes only to
   complete forward. Any receipt conflict, source drift, inherited candidate/authorization/handoff,
   unsafe path, dirty current tree, or unreachable historical head stops without rollback, cleanup, or
   dispatch.

Rollover grants no Worker, external, push, publication, destructive, synchronization, or v2 authority.
