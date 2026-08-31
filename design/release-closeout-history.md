# Durable Release Closeout History

Status: design-only proposal for the next implementation wave. This document does not change the current Schema,
validator, CLI, Skill, v1 records, publication authority, or protocol-v2 adoption state. The `schema_version: 2`
candidate mentioned below is the existing candidate-evidence format; it is not protocol-v2 adoption.

## 1. Decision

The live Master Card is a lock and progress projection. It is not the durable history of a completed release batch. A
successful closeout writes an immutable, Master-local archive before clearing the live release lock. The archive is the
recovery source for the final Dispatch Plan, the pre-clear ACTIVE Master Card, every Worker handoff, and the candidate
that justified completion.

The closeout mechanism is a v1-compatible local recovery mechanism:

1. It reads and validates the existing v1-authoritative Plan, Task Specs, Master Card, Worker handoffs, Git objects, and
   candidate evidence.
2. It writes an append-only archive under the `state_root` named by the current Plan.
3. It clears only the live Master projection after the archive and a completion record are durable.
4. It never rewrites a Task Spec, Plan history, Worker handoff, Git object, candidate evidence, or publication record.

The closeout outcome is `COMPLETED` only when the final integrated Git HEAD has a fresh, independently valid candidate
evidence v2 record with status `PASSED`, every current Dispatch entry is terminal, and every Master handoff is terminal.
An archive may exist while the final live-card write is waiting for recovery; that archive is an idempotent completion
intent, not permission to publish or to infer an external result.

The four result boundaries remain independent:

| Result | Closeout relationship |
| --- | --- |
| `DELIVERY COMPLETE` | Proved by terminal Worker handoffs and their accepted integration mappings. |
| `CANDIDATE PASSED` | Proved by fresh candidate-evidence v2 for the exact final release HEAD. |
| `GIT PUSHED` | Not performed or inferred by closeout. |
| `PRODUCTION PUBLISHED` | Not performed or inferred by closeout; it remains a separate STRICT action. |

## 2. Authority and identity boundaries

The records keep one owner per fact:

| Fact | Closeout source of truth | Closeout treatment |
| --- | --- | --- |
| Live scheduling and Dispatch status | Persisted Dispatch Plan | Preserve the exact Plan bytes and its existing `plan_digest`. |
| Immutable assignment content | Persisted Task Spec at its original locator | Preserve each task identity and digest; do not copy or rewrite assignment authority. |
| Pre-clear release lock and candidate projection | ACTIVE Master Card | Preserve its exact bytes before changing the live projection. |
| Handoff state and integration mapping | Master-owned `worker_handoffs` | Preserve every object, including terminal `REWORK_REQUESTED` history. |
| Repository bytes, HEAD, tree, reachability, and dirty state | Git | Re-read the exact final HEAD and tree; do not infer them from a card. |
| Candidate approval evidence | Candidate evidence v2 | Require fresh evidence for the final HEAD; the closeout is not a second candidate authority. |
| Closeout transition proof | `closeout.json` | Own the archive-to-IDLE intent and immutable references, not delivery or publication authority. |
| External authorization and outcomes | Existing authorization/publication records | Record no new authority and do not synthesize an external outcome. |

The closeout identity is the tuple `(release_task_id, closeout_revision)`. The directory makes one release task's
history addressable; `closeout_revision` starts at `1`. A retry with the same identity and the same bytes is a no-op. A
different identity, source digest, final HEAD, or outcome at the same locator fails closed and does not create a competing
interpretation.

Conversation text, task titles, branch names, model labels, and UI projections are not closeout authority. A conversation
loss must be recoverable from this archive, the immutable Task Spec locators, the current persisted records, and Git.

## 3. Fixed archive layout and path safety

The archive root is derived only from the validated current Plan:

```text
<state_root>/history/releases/<release_task_id>/
├── plan.snapshot.json
├── master.active.snapshot.json
├── handoffs/
│   ├── index.json
│   └── <task_id>/
│       └── r<task_spec_revision>-<task_spec_digest_hex>.json
└── closeout.json
```

`<state_root>` is the absolute `state_root` from the Plan. The implementation resolves the parent and verifies that the
final directory remains below `<state_root>/history/releases`; it does not follow a symlink outside that boundary. No
other archive file is normative. Temporary siblings used during an atomic write are never treated as completed history and
must not be deleted automatically after an interruption.

`release_task_id` and the task-id directory component use this archive-safe grammar:

```text
^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$
```

The value is ASCII, at most 256 bytes, and contains no slash, backslash, empty segment, `.`/`..`, colon, NUL, whitespace,
or control character. The digest filename removes the literal `sha256:` prefix and uses exactly 64 lower-case hexadecimal
characters. Reject an unsafe ID before creating a directory; never sanitize it, truncate it, or reinterpret it as a path.
The current repository release task ID `mwr-hardening-2026-08-30` satisfies this grammar.

The archive directory is local coordination state. Repository policy may ignore or track it in a later implementation, but
that policy does not authorize cleanup or deletion of a completed archive.

## 4. Exact archived records

### 4.1 Plan snapshot

`plan.snapshot.json` is the exact UTF-8 byte sequence read from the validated current Dispatch Plan. It must include its
original `record_revision`, semantic `plan_revision`, `plan_digest`, release task identity, all task entries, and all
terminal status decisions. Its outer archive digest is:

```text
plan_snapshot_digest = SHA256(exact_bytes(plan.snapshot.json))
```

This is separate from the Plan's existing structured digest:

```text
plan_digest = SHA256(canonical_json(plan with plan_digest = null))
```

The implementation must verify both. Whitespace normalization, key reordering, status rewriting, or recomputation from a
different current Plan is a conflict, not an equivalent snapshot.

### 4.2 ACTIVE Master snapshot

`master.active.snapshot.json` is the exact UTF-8 byte sequence read from the validated ACTIVE Master Card before the IDLE
write. It preserves the complete `worker_handoffs` array and candidate evidence, not a compact reconstruction. Its outer
archive digest is:

```text
master_snapshot_digest = SHA256(exact_bytes(master.active.snapshot.json))
```

The snapshot must prove `state: ACTIVE`, the same `release_task_id`, `plan_revision`, `dispatch_plan_path`,
`dispatch_plan_digest`, and `frozen_baseline_sha` as the Plan context. An ACTIVE Card with a blocker, a different Plan
digest, or a changed release lock is not a closeout input.

### 4.3 Worker handoff archive

Every object in `master.active.snapshot.json.worker_handoffs` is written as one canonical JSON object at the deterministic
handoff path. The object itself remains the exact Master handoff value; the path is only a locator. Each handoff file is
represented once in `handoffs/index.json`, whose entries have exactly these fields:

```json
{
  "task_id": "<id>",
  "task_spec_revision": 1,
  "task_spec_digest": "sha256:<64-hex>",
  "plan_revision": 1,
  "dispatch_wave": 1,
  "source_thread_id": "<issuer-thread>",
  "role": "<role>",
  "frozen_baseline_sha": "<40-hex>",
  "authorization_envelope_digest": "sha256:<64-hex>",
  "acceptance_digest": "sha256:<64-hex>",
  "worker_commit_sha": "<40-hex>",
  "integrated_as_sha": "<40-hex-or-null>",
  "state": "INTEGRATED | REWORK_REQUESTED",
  "locator": "handoffs/<task_id>/r<revision>-<digest_hex>.json",
  "value_digest": "sha256:<64-hex>"
}
```

The `value_digest` is `SHA256(canonical_json(handoff_object))`; `index.json` is sorted by the full handoff identity
`(task_id, task_spec_revision, task_spec_digest, source_thread_id)`. Its archive digest is the SHA-256 of its exact bytes.
No handoff may be dropped because it is old, superseded, rejected, or not needed for the current aggregate result. A
terminal `REWORK_REQUESTED` handoff remains historical evidence and is never converted into `INTEGRATED` by closeout.

### 4.4 Closeout record

`closeout.json` is a canonical JSON object with exactly the following top-level fields; unknown fields are a validation
failure:

```json
{
  "schema_version": 1,
  "record_kind": "release-closeout",
  "closeout_revision": 1,
  "release_task_id": "<id>",
  "outcome": "COMPLETED",
  "protocol": "v1-authoritative",
  "state_root": "<absolute-state-root>",
  "archive_locator": "history/releases/<release_task_id>",
  "issued_by": "<Plan issued_by>",
  "created_at": "<RFC3339>",
  "candidate_validated_at": "<RFC3339>",
  "plan_snapshot": {
    "locator": "plan.snapshot.json",
    "record_revision": 1,
    "plan_revision": 1,
    "plan_digest": "sha256:<64-hex>",
    "snapshot_digest": "sha256:<64-hex>"
  },
  "master_snapshot": {
    "locator": "master.active.snapshot.json",
    "record_revision": 1,
    "state": "ACTIVE",
    "release_task_id": "<id>",
    "plan_revision": 1,
    "dispatch_plan_digest": "sha256:<64-hex>",
    "frozen_baseline_sha": "<40-hex>",
    "snapshot_digest": "sha256:<64-hex>"
  },
  "candidate": {
    "locator": "master.active.snapshot.json#/candidate_evidence",
    "schema_version": 2,
    "release_task_id": "<id>",
    "release_head_sha": "<40-hex>",
    "plan_revision": 1,
    "plan_digest": "sha256:<64-hex>",
    "status": "PASSED",
    "legacy": null,
    "value_digest": "sha256:<64-hex>"
  },
  "git": {
    "final_release_head_sha": "<40-hex>",
    "final_release_tree_sha": "<40-hex>",
    "head_reachable": true
  },
  "worker_handoffs": {
    "index_locator": "handoffs/index.json",
    "count": 0,
    "index_digest": "sha256:<64-hex>",
    "all_terminal": true,
    "worker_locks": "ALL_IDLE"
  },
  "live_master_transition": {
    "from_state": "ACTIVE",
    "from_record_revision": 1,
    "to_state": "IDLE",
    "to_record_revision": 2
  },
  "external_authority": "NONE",
  "closeout_digest": "sha256:<64-hex>"
}
```

The example's numbers are placeholders; the field set and relationships are normative. `count` is the exact number of
archived Master handoffs. `worker_locks: ALL_IDLE` means every Worker Card bound to this release has already been
reconciled to IDLE; closeout never clears another Worker's lock. If a repository has no Worker assignments, the count is
zero and the index contains an empty canonical list.

`candidate.value_digest` is `SHA256(canonical_json(candidate_evidence))` over the full v2 evidence object in the ACTIVE
Master snapshot. It is not a newly invented candidate key. `closeout_digest` is:

```text
SHA256(canonical_json(closeout with closeout_digest = null))
```

All structured digests use the repository's existing UTF-8, recursively sorted-key, ordered-array, no-floating-point
canonical JSON rule. All file digests hash exact bytes. A digest proves integrity and identity; it grants no authorization.

## 5. Completion preconditions

The writer must validate all preconditions before the first archive write and revalidate the relevant source after every
read. Failure is fail-closed and leaves the live Master ACTIVE.

### 5.1 Plan and Task Specs

- The current Plan is standalone-valid and its `plan_digest` recomputes exactly.
- `release_task_id` is safe, equals the requested release task, and resolves below the Plan's `state_root`.
- Every current Plan entry has a terminal Dispatch status: `INTEGRATED`, `CANCELLED`, or `SUPERSEDED`. `READY`,
  `PUBLISHED`, `BLOCKED`, and `GATED` entries prevent `COMPLETED` closeout.
- Every referenced Task Spec remains readable, schema-valid, digest-valid, and at its original immutable locator. A
  status-only Plan revision may be historical context, but it may not silently replace the exact bytes selected for this
  closeout.
- Plan/Task Spec graph, dependency, model, authorization, and source-thread bindings remain valid. Closeout does not
  grandfather a newly changed assignment or repair a stale baseline.

### 5.2 Master, handoffs, and locks

- The source Master Card is standalone-valid, `ACTIVE`, and has no blocker. Its release lock and Plan context match the
  Plan snapshot exactly.
- Every Master handoff is schema-valid and terminal: `INTEGRATED` has a non-null `integrated_as_sha`; `REWORK_REQUESTED`
  has no integration mapping. No `RECEIVED` handoff is allowed.
- Current Plan entries and Master handoffs pass the existing cross-record consistency checks. Each current assignment that
  requires a handoff has one matching identity, digest, baseline, authorization digest, and outcome; preserved older
  rework history may remain only as validated historical lineage.
- Every bound Worker Card is `IDLE` before the Master closeout, or Master must first complete its separately governed
  reconciliation. The closeout writer never clears a Worker Card and never treats an absent card as permission to discard
  handoff evidence.

### 5.3 Fresh candidate and Git binding

- Candidate evidence is schema-version 2, has `legacy: null`, status `PASSED`, and the same `release_task_id`,
  `plan_revision`, and `plan_digest` as the selected Plan/Master context.
- The candidate's `release_head_sha` equals the current Master worktree HEAD and the closeout's
  `final_release_head_sha`. Git must resolve that full SHA and its exact tree SHA; a branch name or a patch-equivalent
  commit is insufficient.
- The candidate is fresh for this exact head and current Gate Registry. Master revalidates every current Gate and check
  against the integrated tree, including optional Gates. Every Gate has current, independently bound evidence; every
  required Gate is `PASSED`; optional Gate failures retain valid evidence and do not alter required-Gate aggregation.
  `NONE`, `STALE`, missing evidence, legacy-only evidence, opaque legacy digest reuse, mismatched head provenance, or an
  unverifiable registry prevents closeout.
- A status-only Plan write does not itself invalidate unrelated candidate inputs, but a changed semantic source, Gate
  Registry, authorization, toolchain, projection, or integrated HEAD requires the ordinary fresh revalidation. Closeout
  never promotes stale candidate evidence.

`external_authority` is always `NONE` for this design. A candidate pass does not authorize a push, tag, release, deploy,
execution, or production publication. Protocol-v2 adoption remains outside the closeout task.

## 6. Atomic write protocol

The operation is serialized per release-task directory and uses a no-overwrite `write_once` primitive:

1. Validate the complete source set and calculate all archive bytes and digest relationships without changing the live
   records.
2. Create the safe archive directory. If a final file already exists, compare its exact bytes; equal bytes are success,
   different bytes are a hard conflict.
3. Write and durably flush `plan.snapshot.json`, then atomically install it without replacing an existing final file.
4. Re-read and verify the Plan snapshot, then write and atomically install `master.active.snapshot.json`. Its exact bytes
   must still describe the same ACTIVE release lock and Plan digest.
5. Write each deterministic handoff object and `handoffs/index.json` with the same no-overwrite rule. Verify the complete
   index, all `value_digest` values, and terminal cross-record relationships.
6. Build and atomically install `closeout.json` only after the Plan, ACTIVE Master, handoff archive, candidate, and Git
   checks pass. Re-read the file, recompute `closeout_digest`, and verify the complete record.
7. Re-read the live Master Card. It must still be byte-equivalent to the archived ACTIVE snapshot (or to the exact active
   source snapshot used to create it). Build the canonical IDLE projection with `record_revision` incremented by one,
   `updated_at` advanced, all active release lock fields cleared, no Worker handoffs retained in the live projection, an
   empty candidate projection, and `blocker: null`. Atomically replace the live Master Card and flush its parent directory.
8. Read back the live Card and verify the IDLE transition, the expected record revision, and the immutable closeout digest.

The last write is the only live-release-lock mutation. A failed comparison, partial write, changed HEAD, changed Plan, or
changed Master Card stops the sequence and never silently chooses a newer value. The implementation must use a same-
directory temporary file, flush file contents when supported, atomically install the final name without replacement, and
flush the containing directory when supported. A malformed readback is a blocker, not a reason to repair by guesswork.

The live IDLE projection may use the repository's existing v1 empty candidate `NONE` shape (or an already adopted canonical
empty projection if the repository later has one); the archived ACTIVE snapshot remains the sole closeout evidence. No
current Schema field is added by this design.

## 7. Idempotency and conflict rules

Retries are safe only for the same release identity and the same immutable inputs:

- An absent final archive file is installed once.
- An existing file with identical bytes is reused without changing its timestamp or content.
- An existing file with different bytes, a different Plan/Master/candidate digest, a different final HEAD/tree, a changed
  handoff set, or a different closeout digest fails closed. Do not overwrite, merge, truncate, sanitize, or delete either
  version.
- If `closeout.json` is already valid and the live Card is still the exact expected ACTIVE snapshot, retry only the final
  ACTIVE-to-IDLE write. If the live Card is already the exact expected IDLE projection, the retry is complete and remains
  idempotent.
- If the live Card is ACTIVE but differs from the archived snapshot, or is IDLE with no matching closeout, report a
  reconciliation blocker. IDLE alone never proves that the release was completed.
- A changed final HEAD or semantic input starts a new explicitly published release task/cycle. It does not rewrite this
  archive or reuse its candidate evidence.

No cleanup is part of retry. Temporary files, conflicting bytes, and preserved handoff evidence remain available for Master
inspection. Any discard or replacement requires a separate, explicitly recorded Master decision.

## 8. Interruption and recovery matrix

| Interruption point | Required recovery |
| --- | --- |
| Before directory or Plan snapshot | Keep Master ACTIVE; revalidate all inputs and retry from the beginning. |
| After Plan snapshot, before ACTIVE Master snapshot | Compare the stored Plan bytes/digest; reuse only an exact match, then re-read ACTIVE Master. |
| During/after ACTIVE Master snapshot | Atomic readback must yield either no final file or the exact stored bytes; a conflict blocks. Do not clear the live lock. |
| During handoff files or index | Reconcile every file and index entry against the ACTIVE snapshot; missing entries may be completed, conflicts block; never omit a handoff. |
| After `closeout.json`, before live IDLE | Verify the closeout and source snapshot, then retry only the expected ACTIVE-to-IDLE transition. The archive remains the durable completion intent. |
| During live IDLE replacement | Atomic replacement permits only the old valid ACTIVE card or the new valid IDLE card. Any malformed/unknown result blocks manual Master recovery. |
| After live IDLE readback | Verify the archive, closeout digest, expected IDLE revision, and cleared fields. Never delete the archive or reconstruct history from the IDLE projection. |
| Conversation loss at any point | Recover from persisted archive files, Plan/Task Spec locators, Master Card, Worker Cards, and Git; do not depend on message replay. |
| Missing Task Spec, unavailable history path, digest mismatch, or changed Git HEAD | Fail closed and preserve all bytes; request Master reconciliation or a new release task. Never guess, migrate, or reset. |

If the live Master is IDLE while an archive is incomplete, the states are inconsistent. Recovery must preserve the partial
archive and treat the closeout as unproven; it must not fabricate a closeout after the fact. If the live Master remains
ACTIVE after a valid closeout, retry the final transition or leave it ACTIVE for explicit Master recovery. A closeout record
does not authorize a forced state change.

## 9. Minimal implementation and negative-test order

The next implementation should remain modular and v1-compatible:

1. Safe release-task/path resolution and archive layout checks.
2. Canonical/exact-byte digest helpers and no-overwrite atomic `write_once` primitive.
3. Read-only Plan, Task Spec, Master, handoff, Worker Card, candidate, and Git precondition readers.
4. Fixed snapshot and handoff index writers with conflict detection.
5. Closeout record construction and self-digest/readback verification.
6. Final Master ACTIVE-to-IDLE projection writer with expected-source compare and crash recovery.
7. Public CLI routing and reporting, without adding closeout authority to FAST or any publication path.
8. End-to-end fixtures for each interruption point and current cross-record validation.

The acceptance matrix must include at least:

| Fixture | Expected result |
| --- | --- |
| Complete terminal Plan + ACTIVE Master + fresh v2 PASSED candidate + all IDLE Worker Cards | Closeout and IDLE transition succeed. |
| Unsafe release ID, path escape, symlink escape, or digest filename mutation | Fail closed before archive creation. |
| Nonterminal Dispatch entry, `RECEIVED` handoff, missing handoff, duplicate identity, or mismatched Task Spec digest | No closeout; live Master remains ACTIVE. |
| Candidate v1, legacy-only, stale, missing optional evidence, wrong head, or registry/input digest mismatch | No closeout; candidate is not promoted. |
| Existing identical archive bytes | Idempotent success/no-op. |
| Existing conflicting Plan, Master, handoff, index, or closeout bytes | Fail closed with preserved evidence and no overwrite. |
| HEAD or semantic Plan/Gate input changes between validation and write | Abort before IDLE; require fresh revalidation/new cycle. |
| Crash before each of the four required phases | Recovery follows the interruption matrix and never guesses. |
| Closeout exists but live Card is still ACTIVE | Retry only the exact final transition. |
| Live Card is IDLE without a matching closeout | Reconciliation blocker; do not infer completion. |

These checks are design acceptance criteria for the future implementation; this task itself changes no executable contract or
CLI.

## 10. Non-goals and rollout boundary

- No Schema, validator, Skill, CLI, Task Spec, Dispatch Plan, Worker Card, or Master Card contract change is made here.
- No v2 protocol adoption, repository adoption record, v1 bulk migration, or historical rewrite is introduced.
- No push, tag, GitHub Release, deployment, production publication, execution, destructive operation, or external call is
  created or inferred.
- No archive cleanup, retention deletion, reset, synchronization, merge, rebase, or branch operation is authorized.
- Candidate evidence remains release evidence; a closeout is not a release approval and cannot change Gate aggregation.
- The implementation parameters intentionally left for the next task are the local archive retention policy, the exact
  atomic filesystem primitive on each supported platform, the card serializer, CLI presentation, and the Master recovery
  ownership handoff. Choosing those parameters must preserve the field set, identity, digest, ordering, and fail-closed
  rules above.
