# v1/v2 Migration and Protocol-Freeze Design

Status: design-only proposal for the future v2 adoption cycle. It does not change the current Skill, Schema, validator, CLI,
or any persisted v1 record. v1 remains the current normative protocol until the activation decision in Section 8.

This design consumes the three approved v2 inputs:

- `design/adaptive-operating-modes-v2.md` at `7a586b14df537f6d68e48c0ab16269f32dc346c4`;
- `design/state-authority-minimal-records-v2.md` at `d1437a3f4f86e4e6e8b1d26e26be2ea91a674ea7`; and
- `design/v2-policy-decisions.md` at `1d40711dbd8acbd902730b4757c45a6c0b105f54`.

The terms **MUST**, **MUST NOT**, **ONLY**, and **MAY** are normative for a later, separately authorized implementation.

## 1. Freeze invariants

1. Every ISOLATED or STRICT cycle has one immutable protocol fence before its first executable v2 assignment.
2. A cycle is interpreted by the fence that activated it. A later reader, Master rotation, or CLI invocation cannot silently
   reinterpret that cycle under another protocol, Schema, record family, or validator.
3. v1 records remain immutable read-only history. A v2 record may cite v1 evidence, but it cannot copy, rewrite, reauthorize,
   or promote that evidence into current v2 authority.
4. A missing, mixed, partial, unknown, or unverifiable protocol boundary fails closed. The reader never guesses from a file
   path, field that happens to be present, branch name, message, or current validator.
5. Before a fence is durably activated, the attempted cycle can be abandoned without creating v2 authority. After activation,
   the cycle is preserved under its frozen interpretation; after the first executable assignment it must be completed,
   cancelled, or superseded under v2.
6. A fallback is a new explicitly fenced cycle. It is never a reinterpretation of an old v1 or v2 cycle.

The current v1 protocol is not a failed v2 activation. It remains the authority for its own records until a separate v2 fence
is successfully persisted.

### 1.1 Repository-wide adoption boundary

A per-cycle fence answers which rules interpret one ISOLATED or STRICT cycle; it does not answer which protocol a new
repository operation should choose before that operation has a cycle fence. Repository-wide adoption therefore has its own
immutable record. It is the only authority that changes the default protocol for new operations, and it never rewrites the
meaning of an existing v1 record, v2 cycle, FAST receipt, or durable fence.

The repository adoption record has one immutable identity and one canonical digest. It contains at least:

```json
{
  "record_kind": "repository-adoption",
  "repository_id": "multi-worktree-release",
  "adoption_id": "opaque-never-reused-adoption-id",
  "default_protocol": "v2",
  "protocol_major": 2,
  "protocol_minor": 0,
  "record_family_id": "mwr-v2",
  "schema_identity": "schema-identity-digest",
  "validator_commit_sha": "full-validator-commit-sha",
  "validator_source_digest": "sha256:...",
  "adopted_at": "2026-08-30T00:00:00Z",
  "issuer_master_id": "master-identity",
  "predecessor_adoption_digest": null,
  "adoption_digest": "sha256:..."
}
```

`repository_id`, `adoption_id`, `default_protocol`, protocol major/minor, record-family identity, Schema identity, and
validator commit/source digest are the semantic adoption and implementation identity. `issuer_master_id`, `adopted_at`, and
the predecessor adoption digest are immutable activation provenance. Plan/Card revisions, Task Spec locators, branches,
worktrees, UI messages, check results, and current-pointer bookkeeping are audit metadata; they cannot select the default
protocol or replace an adoption identity. The adoption digest covers the complete immutable record with itself set to `null`.

The record has no mutable `current`, `cancelled`, or `rolled_back` field. An immutable repository index may point to the one
active adoption locator, but the record and pointer are published as one atomically visible adoption bundle. A later adoption
is an append-only new record whose `predecessor_adoption_digest` names the prior record. It never edits, deletes, or points
backward to make an older adoption current. An adoption update affects only operations that begin after its verified
activation; existing cycles and receipts retain their original adoption identity and digest.

#### FAST before and after adoption

Before a repository adoption record is durably active, v1 remains the normative protocol for explicitly v1-routed existing
work. Pilot A may exercise a FAST path only when an explicit, non-authoritative pilot/build manifest names its pilot identity,
protocol under test, implementation/schema digests, bounded scope, and `authority: non-authoritative`. That manifest is test
context, not a repository default, v2 authority, release evidence, or a replacement for a Plan/Card. An ambiguous new FAST
request has no implicit v1-or-v2 choice and fails closed; the pre-adoption manifest is the only permitted way for Pilot A to
exercise a non-authoritative v2 build path.

After the adoption bundle is active, a new FAST operation resolves the active repository adoption record and uses its
`default_protocol` and implementation identities. For the adopted record above that choice is v2. FAST still does not create
a Plan or Worker/Master Card. Every FAST request binds the resolved `adoption_id`, immutable adoption locator, and
`adoption_digest` in its validated request context, even when no durable receipt is required. A one-conversation local FAST
operation may remain ephemeral; when conversation rotation,
authorized external mutation, or recovery requires a durable Operation Receipt, that receipt MUST reference the exact
`adoption_id`, immutable adoption locator, and `adoption_digest`. The receipt is then the durable owner for that FAST event;
the adoption record remains the repository-wide default authority, and its authorization is never inferred from the receipt.

If the adoption record or active pointer is missing, conflicting, digest-mismatched, rolled back, or only partially visible,
new FAST operations fail closed. They do not guess v1 from a legacy path, guess v2 from a field, or create an unbound receipt.

#### Cycle references and formal activation order

Every new v2 ISOLATED or STRICT cycle fence MUST carry an immutable reference to the applicable repository adoption record:
`(adoption_id, immutable adoption locator, adoption_digest)`. The cycle keeps its own independent `cycle_id` and fence digest;
the adoption reference does not replace or collapse cycle identity. A cycle fence is created only after the adoption reference
has been resolved and verified. A later adoption update does not alter an active cycle fence, its owner roots, or its receipts.

Formal v2 activation is ordered and all-or-none:

1. Master completes the approved pilot and adoption decision, then performs read-only checks of the current v1 authority,
   the exact Schema/record-family identity, validator bytes/digest, and absence of a conflicting active adoption.
2. Master constructs one immutable repository adoption record and its canonical digest, plus the adoption index/pointer that
   will resolve new operations to it. Neither a draft record nor a pointer visible without the record is an adoption.
3. Master atomically persists the record, its immutable locator, and the pointer/manifest as one all-or-none transaction or
   immutable commit. No new v2 FAST operation or v2 cycle fence is admitted during an unverified partial write.
4. Master re-reads the persisted bytes, adoption digest, pointer, and implementation artifacts. Only after exact identity and
   visibility are proven does v2 become the repository default; new ISOLATED/STRICT fences may then be created with the
   adoption reference, as needed.

The activation outcome is handled as follows:

| Adoption condition | Required result | Prohibited result |
| --- | --- | --- |
| Missing adoption record or no active pointer | Keep v1 history readable; block new ambiguous v2-default operations and fences. | Do not infer a repository default from a path, branch, current code, or message. |
| Conflicting records or pointer/digest mismatch | Preserve every immutable record and block new operations until Master resolves the conflict. | Do not choose the newest-looking, oldest, or locally available record. |
| Rolled-back or non-monotonic pointer | Treat the rollback as an invalid repository state and fail closed. Recovery requires a new explicit adoption decision and record. | Do not reactivate an older adoption or silently return the default to v1. |
| Partially visible adoption bundle | Preserve the last complete valid checkpoint and block resolution until record, locator, pointer, and digest visibility are jointly proved. | Do not publish a cycle fence or receipt from a half-visible bundle. |
| Adoption record is durable but a later cycle fence fails | Keep the adoption record authoritative for new FAST selection; handle the failed cycle under its own fence rules. | Do not erase or rewrite the adoption record to repair a cycle. |

A durable cycle fence is v2 audit state even when it exists before the first executable assignment. If activation must stop at
that point, Master appends an immutable closure record containing the fence digest, adoption reference, outcome
`ACTIVATION_CANCELLED`, reason, issuer, and time; the original fence bytes and locator remain retained and verifiable. This
is a cancellation of a durable v2 fence, not abandonment of v2 state. Only an unpersisted draft may be abandoned without
creating v2 authority. A cancelled durable fence cannot be erased, relabeled as v1, or reused for a later cycle.

## 2. Immutable protocol-fence identity

### 2.1 Fence identity and semantic meaning

The normative fence is one canonical, append-only value. Its identity is the following tuple, with no mutable status fields:

```text
(
  repository_adoption_id,
  repository_adoption_locator_identity,
  repository_adoption_digest,
  protocol_major,
  protocol_minor,
  record_family_id,
  schema_identity,
  validator_commit_sha,
  validator_source_digest,
  cycle_id,
  issuer_master_id,
  activated_at
)
```

`fence_digest` is the canonical digest of that complete tuple and is stored with the fence. It is a derived integrity value,
not a substitute for any tuple member.

| Field | Required role | Semantic identity or audit metadata | Immutability rule |
| --- | --- | --- | --- |
| `repository_adoption_id` | Exact prospective repository-default decision used to create the cycle | Semantic identity | It must match the verified adoption record and cannot be replaced within the cycle. |
| `repository_adoption_locator_identity` | Immutable locator identity for the adoption bytes | Semantic identity | Mutable paths or pointers are insufficient; the locator must resolve the same immutable bytes. |
| `repository_adoption_digest` | Canonical digest of the complete adoption record | Semantic identity | It is recomputed from the referenced record; mismatch blocks activation and recovery. |
| `protocol_major` | Breaking protocol family | Semantic identity | A change requires a new cycle and explicit adoption. |
| `protocol_minor` | Compatible rule revision within the major | Semantic identity | A change requires a new fence; it cannot rewrite an active cycle. |
| `record_family_id` | Delivery/release record-family vocabulary | Semantic identity | Every owner record in the cycle names the same family. |
| `schema_identity` | Schema/record-shape identity, including its content identity | Semantic identity | A missing or unavailable identity blocks the cycle. |
| `validator_commit_sha` | Exact validator implementation | Semantic execution identity | Readers use this exact implementation or fail closed. |
| `validator_source_digest` | Content digest of the validator implementation and declared dependencies | Semantic execution identity | It must match the bytes at the immutable validator locator. |
| `cycle_id` | Unique opaque identity for this protocol cycle | Semantic identity | It is never reused and is not a task ID, branch, worktree, or release SHA. |
| `issuer_master_id` | Master identity that activated the fence | Immutable activation provenance | Rotation may add an issuer event but cannot replace the original issuer. |
| `activated_at` | Activation instant with strict RFC 3339 form | Immutable activation provenance | It is written once in the atomic activation bundle. |
| `fence_digest` | Integrity digest of the complete fence tuple | Derived identity binding | It is recomputed from the tuple; status or audit fields are excluded. |

The adoption reference plus the protocol, implementation, and cycle fields form the semantic interpretation core.
`issuer_master_id` and `activated_at` are not rule semantics, but
they are part of the immutable fence identity and provenance binding; changing either changes the fence digest and therefore
requires a new cycle. The following are audit metadata and MUST NOT be used as protocol identity:

- Plan `record_revision`, `plan_revision`, and `plan_digest`;
- Task Spec IDs, task revisions, acceptance digests, and source-thread locators;
- Git baseline, branch, worktree, integrated head, tree, and changed-path observations;
- Worker/Master Card record revisions, message locators, UI titles, and `updated_at` values; and
- check results, candidate status, remote references, and publication receipts.

Audit metadata can be referenced by the fence or its owner records, but changing it must follow the owner record's own
append-only revision rules. It cannot change the protocol interpretation of an existing cycle.

### 2.2 Cycle and fence records

The activation bundle has one immutable fence record, one cycle manifest, and (for every post-adoption v2 cycle) the immutable
repository adoption reference. The manifest records the fence digest, adoption reference, and immutable locators for the owner
roots that exist in the selected mode. It does not duplicate their mutable payloads. A minimal conceptual shape is:

```json
{
  "record_kind": "protocol-fence",
  "repository_adoption_id": "opaque-adoption-id",
  "repository_adoption_locator": "immutable-adoption-locator",
  "repository_adoption_digest": "sha256:...",
  "protocol_major": 2,
  "protocol_minor": 0,
  "record_family_id": "mwr-v2",
  "schema_identity": "schema-identity-digest",
  "validator_commit_sha": "full-validator-commit-sha",
  "validator_source_digest": "sha256:...",
  "cycle_id": "opaque-never-reused-cycle-id",
  "issuer_master_id": "master-identity",
  "activated_at": "2026-08-30T00:00:00Z",
  "fence_digest": "sha256:...",
  "owner_root_locators": []
}
```

This is JSON-shaped design notation, not a change to the current Schema. A cycle must not use a mutable path alone as an
immutable locator. A locator must identify a content-addressed object, immutable Git commit/blob/path, or append-only store
position whose bytes can be re-read and digested.

## 3. v1 read-only boundary and forward references

### 3.1 v1 remains v1

An active or terminal v1 cycle is always read using v1 protocol rules. A v2 reader MUST preserve:

- the exact historical bytes and canonical digest;
- the original path or immutable locator, including its historical revision;
- timestamps and record revisions;
- the complete historical Task Spec and its digest; and
- the original authorization and evidence syntax, even when v2 cannot execute it.

An active or terminal v1 cycle cannot be converted in place. No v1 record is converted in place. A current file at the same path cannot replace an unavailable historical Task Spec. A v1
terminal state is not a v2 terminal state, and a v1 active state is not an executable v2 assignment. Migration is a new v2
record and a new fence, with an explicit reference to the old record.

### 3.2 v2 may cite v1 evidence only as history

A v2 forward reference to v1 contains exactly:

```text
(v1 protocol identity, v1 record identity, immutable v1 locator, original v1 digest)
```

The reference is marked `audit_only: true`, `copied_payload: false`, and `executable_authority: false` in the conceptual
model. It may support provenance, compatibility reports, or a migration decision. It may not provide current mode selection,
authorization, assignment content, state, Gate result, publication permission, or release success. The v2 record stores the
reference and digest, not a copied v1 payload. If any tuple member is missing or the digest does not match the bytes at the
locator, the reference is unusable and the v2 decision fails closed.

### 3.3 Strictly read-only v1 adapter

The v1 adapter is read-only and has one permitted projection:

1. validate that the source v1 envelope is the canonical complete default-deny envelope under the original v1 contract;
2. create a new superseding v2 Task Spec with a new assignment identity and a newly computed v2 default-deny envelope digest;
3. copy no allowed capability, target, route, provider, budget, expiry, controlled input, or execution identity; and
4. record the v1 envelope as historical input, not as v2 authority.

Allowed, ambiguous, expired-for-use, noncanonical, incomplete, or otherwise non-default-deny v1 authority MUST NOT transfer.
An expired default-deny record that is not exactly canonical is also rejected; the adapter never treats expiry as permission to
reuse or silently renew it. A new v2 authorization must be independently published by Master under the new assignment.

Legacy v1 candidate evidence is audit-only. It may be preserved with its original digest, but it cannot produce a current v2
`PASSED` or `FAILED` result. Fresh v2 Gate evidence must independently bind every current Gate, including optional Gates when
the current registry contains them, to the current release task, exact release head, inputs, checks, provenance, and evidence.

## 4. First v2 activation sequence

### 4.1 Pre-fence read-only preflight

Master performs these checks without publishing an executable assignment:

1. Confirm that v1 remains the current protocol and that no active v2 cycle already owns the same delivery/release outcome.
2. Select `protocol_major`/`minor`, record family, Schema identity, validator commit, validator digest, unique `cycle_id`,
   issuer, and activation time from the approved adoption decision.
3. Verify that the exact Schema and validator artifacts named by the proposed fence are available and digestable. Do not use a
   current replacement merely because the named artifact is unavailable.
4. Read the relevant v1 records and preserve their bytes, digests, Task Specs, and immutable locators. Validate any intended v1
   forward reference without copying its payload.
5. Verify mode, ownership, dependency, authorization, worktree, and preserved-material preconditions. A strict trigger cannot
   be hidden in an ISOLATED or FAST pilot.
6. Compute the fence digest and the activation bundle digest from canonical values. A draft fence that has not been durably
   committed has no v2 authority and may be abandoned.

### 4.2 Atomic activation bundle

The fence and the cycle's foundational owner roots are persisted as one atomic transaction or one immutable activation commit.
The commit/transaction must make all-or-none visibility provable to readers:

1. write the immutable protocol fence;
2. write the cycle manifest with the fence digest and owner-root locators;
3. write the owner roots required by the selected mode; and
4. publish no executable assignment until the atomic bundle is durable and re-read with matching digests.

Logical owner creation order is:

| Mode | Owner-root order before the first executable assignment |
| --- | --- |
| ISOLATED delivery | Protocol Fence → Delivery Plan/cycle root → immutable Task Specs → Worker/Master delivery-lock projections. A Delivery Record is created only when a handoff exists. |
| STRICT release without delegated delivery | Protocol Fence → Release Plan/candidate identity → Gate Registry → current Release Evidence root. Action and Publication Records are created only for an authorized action or attempted publication. |
| STRICT release with delegated delivery | Protocol Fence → Delivery Plan/Task Specs/Worker roots → Release Plan → Gate Registry/Release Evidence root → bounded action record immediately before any strict action. |

Each root carries the same fence digest. Derived projections, cards, and reports never become a second authority for a root.
The first executable v2 assignment is published only after the bundle is verified. That publication is the irreversible
interpretation boundary: from then on, the cycle cannot return to v1 interpretation or silently use another v2 fence.

### 4.3 Failure before and after the fence

| Failure point | Required result | Prohibited result |
| --- | --- | --- |
| Draft assembly before durable fence | Abandon the draft; preserve any ordinary user material and record the failed attempt only as non-authoritative audit data. | Do not claim a v2 cycle or rewrite v1 records. |
| Atomic commit/transaction proves no fence was written | Retry a new pre-fence assembly only after a read-only proof; a never-committed `cycle_id` may be retired. | Do not publish an assignment from an uncommitted draft. |
| Commit outcome is uncertain | Treat the fence as possibly active, inspect the transaction/commit immutably, and block until visibility is proved. | Do not assume rollback to v1 or retry with the same identity blindly. |
| Fence is durable but an owner root is incomplete | Mark the v2 cycle `ACTIVATION_INCOMPLETE`, publish no assignment, and either complete or explicitly cancel it under v2. | Do not discard the fence or reinterpret the partial bundle as v1. |
| First executable v2 assignment exists | Complete, cancel, or supersede the assignment under the same fence and append-only history. | Do not fall back to v1 or relabel the assignment as a fresh FAST/local action. |

If atomicity cannot be demonstrated across the storage locations, the reader treats the bundle as partial and fails closed.
Recovery preserves the last complete valid checkpoint and uses a new Master decision where required.

## 5. Compatibility and CLI matrix

Protocol selection is explicit. A future public CLI may expose `--protocol v1|v2`; the option name can remain an implementation
parameter, but its behavior is fixed here. Existing v1 invocations retain their current output behavior until the v2 facade is
separately adopted.

| Input or operation | Required protocol/fence behavior | Result |
| --- | --- | --- |
| Standalone valid v1 record | Select v1 rules and original validator contract; preserve bytes and digest. | `PASS` under v1; never v2 authority. |
| Standalone valid v2 record | Select v2 explicitly or detect a complete unambiguous v2 fence; validate the full fence and referenced artifacts. | `PASS` only with a complete matching fence. |
| Standalone unknown or incomplete protocol | Do not infer from fields, path, branch, or current code. | `FAIL` closed. |
| Current/previous v1 snapshots | Both snapshots use v1 rules and immutable historical identities. | Historical v1 transition may run. |
| Current/previous v2 snapshots | Both snapshots name the same fence identity and valid record-family/schema/validator artifacts. | Historical v2 transition may run. |
| Previous v1 and current v2 | This is not an ordinary transition. Use an explicit read-only migration bridge and a new v2 cycle, if approved. | Default historical pair: `FAIL`/`NOT_RUN`, never guessed. |
| Current Plan, Worker, and Master records with one v1 protocol | Validate the complete v1 cross-record set under v1 rules. | `PASS` only for complete valid relations. |
| Current Plan, Worker, and Master records with one v2 fence | Validate cross-record identity, owner references, and the same fence digest. | `PASS` only for complete valid relations. |
| Current set mixes v1 and v2 authority records | No record may lend its protocol or authority to another. | `FAIL` closed. |
| Two current records supplied without a previous option | Run the available current cross-record relationship; omitted relationships remain `NOT_RUN`. | Preserve current-only CLI behavior; no historical transition inferred. |
| A previous option supplied without its current counterpart | Do not parse an implicit current record or compare a partial pair. | `FAIL` closed. |
| v2 record cites v1 evidence by the Section 3 tuple | Validate the immutable reference and original digest; keep the v1 payload audit-only. | Allowed as a forward reference, not as v2 authority. |
| Conversation rotation under one active fence | Reuse the exact fence/cycle; new Master records are append-only projections under it. | Allowed only after persisted handoff/issuer evidence. |
| Rotation changes protocol, Schema, validator, or cycle | Start a new fence and new cycle; preserve the old one. | Old cycle remains under its original rules. |
| `--protocol v1` with v2 input, or `--protocol v2` with v1 current authority | Do not auto-adapt or fall back. | `FAIL` with an actionable protocol mismatch. |
| No protocol flag with unambiguous single-protocol input | Route only when the record self-identifies one complete protocol and no mixed relation exists. | Otherwise `FAIL` and require explicit selection. |
| Post-adoption FAST request without a cycle fence | Resolve the active adoption bundle and require the request context to match its adoption ID, immutable locator identity, digest, protocol, and implementation identities. | `PASS` only for one complete match; missing, stale, conflicting, or mismatched adoption fails closed. |
| Post-adoption FAST Operation Receipt | Validate the receipt against the exact adoption record and active pointer that governed the request; no cycle fence is expected. | `PASS` only when request and receipt bind the same verified adoption identity; otherwise `FAIL`. |

The CLI must report `PASS`, `FAIL`, and `NOT_RUN` distinctly, including protocol/fence identity and canonical snapshot digests.
`NOT_RUN` is not evidence that a missing relation passed. Historical validation accepts no mixed authority unless a separate,
explicit adapter command produces a new v2 record and its own evidence.

## 6. Recovery and fail-closed procedures

| Condition | Recovery source and action | Stop rule |
| --- | --- | --- |
| Partial fence write | Inspect the atomic transaction/commit and all fence/root digests. If visibility is not provable, preserve the partial bytes and mark activation incomplete. | Never choose v1 merely because the v2 fence is incomplete. |
| Missing validator/Schema artifact | Recover the exact immutable artifact named by the fence, or keep the cycle blocked/cancelled. | Never substitute the current validator/Schema or guess compatibility. |
| Fence, record, or evidence digest mismatch | Preserve original bytes and locator; mark the reference untrusted and require Master recovery or a new cycle. | Never recompute a replacement digest over altered bytes or overwrite history. |
| Unavailable historical paths | Resolve an immutable commit/blob/store locator. If unavailable, retain the locator/digest and fail the affected check. | Never read a current file at the same mutable path as historical truth. |
| Lost conversations | Recover from the fence, cycle manifest, owner records, immutable Task Specs, Git, evidence, and preserved material. | Messages, elapsed time, and UI titles cannot authorize takeover or completion. |
| Activation interrupted | If the atomic bundle is visible, continue/cancel under its v2 fence; if not visible, prove absence before retrying. | Uncertain visibility is blocked, not silently rolled back. |
| Uncertain protocol selection | Preserve the last complete valid checkpoint and ask Master to publish an explicit protocol/fence decision. | Do not use v1 as a default or let a model/CLI guess. |
| Missing or mismatched adoption during FAST | Stop before work or external action, preserve any user material and receipt draft, and recover the last complete adoption bundle. | The absence of a cycle fence never permits guessing the repository default or emitting an unbound receipt. |
| Mixed authority or cross-record identity | Separate the records by protocol and owner, or create an approved new cycle. | No cross-protocol merge, promotion, or best-effort comparison. |
| User has dirty/untracked material | Record and preserve exact paths and status; keep it outside the new owner roots unless explicitly scoped. | No cleanup, reset, deletion, or implicit adoption. |

Recovery is itself an ISOLATED or STRICT concern according to consequence. It records the old and new cycle/fence identities,
reason, preserved material, and resulting lock state. A v2 fallback never changes the meaning of a v1 or earlier v2 snapshot.

## 7. Abandonment, cancellation, supersession, and rollback

The boundaries are explicit:

1. **Before the fence:** the draft is not v2 authority and may be abandoned. Any retry is a new uncommitted draft; no historical
   v1 record is touched.
2. **After the fence but before an executable assignment:** the fence is already durable v2 state. If activation cannot proceed,
   preserve it and close the cycle as an explicit v2 activation cancellation; retain the original bytes and append the closure
   evidence rather than erasing the fence. Do not relabel it v1. No assignment may be published from an incomplete bundle.
3. **After the first executable v2 assignment:** the cycle remains v2 until the assignment and all dependent records are
   completed, cancelled, or superseded under the same fence. A changed protocol, validator, Schema, authority boundary, or
   cycle identity requires a new superseding cycle, not an in-place rewrite.
4. **Fallback:** a new cycle may start only after Master records the old outcome and creates a fresh fence. A fallback can cite the
   old cycle as immutable history, but cannot reinterpret its v1/v2 state or reuse its `cycle_id`.

Rollback means stopping future work and preserving history; it does not mean changing the protocol label of an existing record.
No downgrade is allowed to avoid a failed Gate, unresolved P0/P1, active lock, started publication/destructive/paid mutation,
or repository minimum mode. The existing FAST/ISOLATED/STRICT policy defaults remain in force inside every v2 cycle.

## 8. Three pilot gates and the v2 activation decision

The pilots exercise the boundary without making v2 normative. Each pilot starts from an approved fence or remains explicitly
pre-fence as noted below, and each produces a read-only report with protocol, fence, record, and evidence digests.

### Pilot A — FAST local

Run one bounded local operation in one conversation with no collaboration, recovery, or external mutation. It must create no
Plan or Card and normally no Operation Receipt. The gate checks:

- before repository adoption, the operation names an explicit non-authoritative pilot/build manifest and never treats it as the
  repository default or v2 authority;
- after repository adoption, the operation resolves the immutable repository adoption record and, if a receipt is required,
  records its adoption identity and digest without creating a Plan or Card;
- mode classification remains FAST under the approved defaults;
- the request and Git checkout are sufficient recovery sources for the one-generation operation;
- no external capability is called or implied by a model/profile; and
- a forced conversation-loss simulation treats unrecorded work as unfinished rather than inventing a receipt.

Stop if any external action is attempted, a collaboration/contract/recovery trigger is hidden, or the reader claims completion
from conversation text alone.

### Pilot B — ISOLATED delivery

Run one separate Worker delivery with a frozen baseline, immutable Task Spec, Delivery Plan, Worker Card, handoff, and Master
integration mapping. The gate checks:

- the protocol fence is atomically persisted before the first executable assignment;
- all owner references use one fence and one record-family/Schema identity;
- current/previous and current cross-record checks distinguish `PASS`, `FAIL`, and `NOT_RUN`;
- conversation rotation and recovery restore the last complete checkpoint without rewriting v1 or v2 history; and
- delivery completion does not produce candidate, push, or production-publication authority.

Stop on any partial fence treated as complete, digest mismatch accepted as a warning, mixed protocol accepted, unauthorized
scope/authority expansion, or handoff/integration evidence not bound to the exact owner records.

### Pilot C — STRICT non-production dry-run or explicitly authorized release

Prefer a non-production dry-run that performs no remote mutation. If an actual release action is selected, it requires a fresh,
bounded explicit authorization for the exact artifact/ref and remains outside production publication unless separately approved.
The gate checks:

- the Release Plan, Gate Registry, per-Gate evidence, action record, and optional Publication Record use one immutable fence;
- legacy v1 evidence is preserved as audit-only and every current v2 Gate has fresh independent evidence;
- candidate passed, Git pushed, and production published remain separate results;
- unknown protocol, missing Schema/validator artifact, mixed authority, and uncertain remote outcome all fail closed; and
- no publication, external call, execution, or destructive action occurs in the dry-run.

Stop on any reused opaque v1 digest, missing optional/current Gate evidence, candidate-to-publication inference, production
mutation without separate authorization, or unresolved remote/persistence uncertainty.

### 8.1 Measurable adoption and stop criteria

Each pilot passes only when all of the following are true:

- 100% of declared current/previous and cross-record cases are classified as `PASS`, `FAIL`, or `NOT_RUN` with no guessing;
- 100% of fence, owner, and forward-reference digests reproduce from immutable bytes;
- all protocol-mismatch, missing-artifact, partial-write, conversation-loss, and uncertain-selection negative cases fail closed;
- zero unauthorized external calls, executions, publications, destructive actions, synchronization, or scope expansion occur;
- no v1 bytes or historical Task Specs are rewritten; and
- no unresolved P0/P1 finding remains in the pilot outcome.

Any failed criterion stops the pilot and keeps v2 non-normative. P2/P3 findings are recorded outside the pilot scope and do not
expand it without explicit user approval.

### 8.2 Formal v2 activation decision

Master may make v2 normative only after Pilots A, B, and C each have an accepted report, the complete compatibility and
negative matrix passes, all stop criteria are clear, and the user/owner explicitly approves adoption. Formal activation first
atomically persists and verifies the repository adoption record and its active pointer; only then does Master create any new
protocol-fenced cycle whose `activated_at`, issuer, validator, Schema/record-family identity, cycle ID, and adoption reference
are fixed. The decision applies prospectively only; every existing v1 cycle remains v1 read-only history.

## 9. Modular implementation order

This order is deliberately modular and begins with the repository-default foundation, not Schema or validator changes:

1. Implement immutable repository-adoption storage, canonical locator identity, atomic record-plus-pointer publication,
   readers, canonical digest re-read checks, and negative fixtures for missing, conflicting, partial, rolled-back, or
   digest-mismatched adoption bundles. No v2-default request is routable before this layer passes independently.
2. Implement FAST adoption resolution and request/Operation Receipt binding, including fail-closed public fixtures that prove
   a missing or mismatched adoption is rejected without relying on a cycle fence.
3. Implement v1 read-only readers and the strict default-deny-only adapter; preserve v1 bytes and original digests.
4. Implement immutable cycle-fence storage, canonical locators, cycle manifests, atomic activation, digest re-read checks,
   and complete adoption-reference binding in `fence_digest`.
5. Implement v2 fence/owner readers and compatibility/forward-reference checks, including mixed-protocol fail-closed paths.
6. Implement ISOLATED delivery validation: Plan/Task Spec/Worker/Master owner relations, historical snapshots, rotation, and
   recovery.
7. Implement STRICT release validation: Release Plan, Gate Registry, fresh per-Gate evidence, action records, and publication
   boundaries.
8. Add CLI protocol routing and explicit previous/current/cross-record reporting behind the existing public facade only after
   adoption and fence readers already enforce their respective identity checks.
9. Add remaining fixtures and negative matrices for missing artifacts, digest mismatch, partial fences, mixed protocols, v1 references,
   uncertain push outcomes, and conversation loss.
10. Run Pilots A–C, collect measurable reports, and make the formal activation decision.
11. Only after adoption approval, open a separate task for Schema, validator, Skill, and other formal-contract changes. This task
   does not begin or authorize that work.

## 10. Non-goals

- rewriting, bulk-migrating, or reauthorizing v1 history;
- changing the current Schema, validator, Skill, CLI, or persisted contract;
- choosing a publication provider or granting external authority;
- treating a fence, Plan, Card, receipt, branch, or model profile as a substitute for action authorization;
- using a fallback cycle to erase a failed or cancelled cycle; or
- declaring a release candidate or production publication from a delivery or pilot result.
