# Per-Gate Evidence and Safe Candidate Invalidation

Status: design-only correction for the `mwr-clarify-gate-evidence` task. This document does not change the current schema,
validator, or runtime behavior. The record shape below is a proposed successor projection that must be adopted through a
separately authorized contract change.

## 1. Problem and invariants

The current `candidate_evidence` contract binds one `gate_input_digest` to a list of checks:

```yaml
release_head_sha: <sha-or-null>
gate_input_digest: <sha-or-null>
status: NONE | STALE | PASSED | FAILED
checks:
  - command: <command>
    result: PASS | FAIL
    evidence_digest: <sha256>
```

That aggregate digest can establish that a set of inputs was summarized, but it cannot say which Gate consumed which
input. If one input changes, a consumer must either trust an unsafe partial comparison or invalidate everything. The
design below makes the per-Gate record the source of truth and keeps the aggregate digest only as a compatibility and
quick-consistency summary.

The following invariants are normative:

1. Evidence is bound to the exact integrated Master tree. A changed `release_head_sha` invalidates every Gate, even when a
   later commit happens to contain an equivalent tree.
2. A candidate is `PASSED` only when every required Gate has current, structurally valid, independently verifiable evidence.
   A matching digest is not itself authorization and is not a substitute for checking execution provenance.
3. A Gate or check that cannot be mapped to its inputs is stale, not passed. When selective dependency information is
   unavailable, the fallback is whole-candidate `STALE`.
4. Unaffected Gate evidence may be retained as historical evidence while the aggregate candidate remains `STALE`; it must
   never be presented as release-candidate approval.
5. Master recomputes final input and evidence projections from the integrated tree. Worker-local derived values are not final
   release evidence.
6. Digests use the canonical JSON rules already defined by the repository: UTF-8 JSON, recursively sorted object keys,
   preserved array order after explicit normalization, no insignificant whitespace, and no floating-point values.
7. State records contain digests and non-secret locators, never secrets, tokens, raw credentials, or unbounded command output.

## 2. Stable identities

### 2.1 Candidate binding

The evidence record is bound to this immutable candidate context:

```yaml
release_task_id: <Master release task ID>
release_head_sha: <full integrated-tree SHA>
plan_revision: <positive integer>
plan_digest: <sha256 digest of the persisted plan>
gate_registry_digest: <sha256 digest of the required Gate definitions>
```

The effective candidate identity is exactly `(release_task_id, release_head_sha)`. `release_head_sha` is the exact immutable
integrated-tree binding; it is not a mutable pointer to the current checkout. A different head is a new Git candidate and
invalidates every Gate. `plan_revision`, `plan_digest`, and `gate_registry_digest` are recorded context and audit metadata,
not additional candidate-key members.

In particular, the whole mutable `plan_digest` must not be used as a candidate key or as a blanket invalidator. A status-only
plan write may change `record_revision`, `updated_at`, or a whole-plan digest without changing any Gate's relevant inputs. Such
a write leaves the candidate identity and unaffected Gate evidence unchanged. Semantic plan, acceptance, authorization,
projection, or registry changes are handled by the per-Gate relevant source digests below. If those changes cannot be mapped
to Gates, the conservative result is whole-candidate `STALE`.

When the head changes, retain the old record as history and create a new record only with new evidence. When only the plan
context changes, re-evaluate the per-Gate relevant digests before deciding whether any Gate is stale.

### 2.2 Gate identity

`gate_id` is a stable, opaque logical identifier assigned by Master, for example:

```text
targeted-tests
shared-contracts
base-relative-audit
release-candidate
```

It must not contain a commit SHA, timestamp, array position, branch name, command text, or Worker conversation label. A Gate
record's stable identity is `(gate_id, gate_revision)`. `gate_revision` starts at 1 and increases when the Gate's required
behavior, success predicate, input contract, or execution policy changes. A changed revision fences all evidence for the old
revision even if the `gate_id` remains unchanged.

The required Gate set and each Gate definition come from the current persisted Master plan or an explicitly versioned Gate
registry. The set is not inferred from whichever evidence rows happen to exist. An absent or unavailable registry is a
validation failure and triggers whole-candidate `STALE`.

### 2.3 Check identity

Each check inside a Gate has a stable `(gate_id, gate_revision, check_id, check_revision)` identity. `check_id` is also
assigned by Master and is not derived from the command string or list index. A command, success predicate, timeout, or
runner-policy change changes the check's input manifest and therefore its `input_digest`; a semantic check change also
increments `check_revision`.

The command text or array order must not be used as identity. Duplicate Gate or check identities are invalid. An unknown or
unregistered identity is never merged by position or by command similarity.

## 3. Proposed evidence projection

The following is a proposed `schema_version=2` projection. It is intentionally shown separately from the current
`references/contracts.schema.json`; implementing it requires a future, separately authorized schema and validator change.

```yaml
schema_version: 2
release_task_id: <id>
release_head_sha: <full-sha>
# Context only; these do not extend the candidate identity.
plan_revision: <positive-integer>
plan_digest: <sha256-or-null>
gate_registry_digest: <sha256-or-null>
# Compatibility summary; derived from the rows below, never the provenance source.
gate_input_digest: <sha256-or-null>
status: NONE | STALE | PASSED | FAILED
legacy: null
gates:
  - gate_id: <stable-id>
    gate_revision: <positive-integer>
    required: true | false
    status: NONE | STALE | PASSED | FAILED
    input_digest: <sha256-or-null>
    evidence_digest: <sha256-or-null>
    input_sources:
      - source_id: <stable-source-id>
        kind: git-commit | git-tree | file | dispatch-plan | task-spec | acceptance | gate-registry | projection | toolchain | authorization
        locator: <non-secret locator>
        revision: <revision-or-null>
        value_digest: <sha256>
    checks:
      - check_id: <stable-id>
        check_revision: <positive-integer>
        command: <bounded command description>
        input_source_ids: [<source-id>]
        result: PASS | FAIL
        input_digest: <sha256>
        evidence_digest: <sha256>
        execution_ref: <non-secret execution reference-or-null>
        observed_artifacts:
          - locator: <non-secret locator>
            value_digest: <sha256>
    invalidation_reason: <reason-or-null>
```

`input_digest` is required for any `PASSED` or `FAILED` Gate/check. A `STALE` or `NONE` row may carry `null` only when the
record also carries an explicit reason for missing or invalid evidence. A Gate-level `evidence_digest` is required when the
Gate is current; it binds the complete set of check results. The top-level `gate_input_digest` is optional compatibility
metadata and, when present, is always recomputed from the per-Gate rows. `plan_digest`, `plan_revision`, and
`gate_registry_digest` in this projection are context; they must not become a direct invalidation condition for unrelated
Gates.

### 3.1 Input sources

Each Gate lists the sources it actually consumes. The source list is normalized by unique `source_id` before hashing. The
minimum sources normally include:

| `source_id` kind | Meaning | Change effect |
| --- | --- | --- |
| `integrated-tree` | Exact `release_head_sha` and tree used by the check | All Gates stale when the head changes |
| `base-tree` | Explicit base/frozen baseline for a base-relative check | Stale only dependent Gates when the base is unchanged at the candidate level |
| `dispatch-plan` | Canonical digest of only the semantic plan fields this Gate consumes | Stale only Gates whose selected plan fields changed |
| `task-spec` | Canonical digest of only the task-spec fields this Gate consumes | Stale only dependent Gates |
| `acceptance` | Canonical acceptance command/predicate digest | Stale the affected Gate/check |
| `gate-registry` | This Gate's definition/revision and requiredness | Stale this Gate; a required-set change makes the aggregate stale |
| `projection` | A generated output and exact integrated-tree value digest | Stale dependent Gates; Master regenerates it first |
| `toolchain` | Interpreter, validator, configuration, and runner-policy fingerprint | Stale checks using the changed toolchain |
| `authorization` | Bounded authorization-envelope digest for an explicitly permitted external source | Missing or unauthorized authority makes the Gate stale |

`value_digest` is the digest of the exact bytes or canonical structured value consumed. `revision` identifies the source
revision when one exists; it never replaces the value digest. A source locator must be stable and non-secret. Environment
variables are not implicitly inputs: the Gate either records an allowlisted, non-secret toolchain fingerprint or treats the
environment as unknown and falls back to `STALE`.

For `dispatch-plan` and `task-spec`, the value is a canonical, explicitly selected semantic slice, such as
`dispatch-plan#task.<id>.acceptance` or `task-spec#acceptance[2]`, not the whole mutable document. The slice excludes
`record_revision`, `updated_at`, status-only dispatch fields, and other bookkeeping unless the Gate explicitly consumes one of
them. A status-only plan write therefore leaves the relevant `value_digest` and the dependent Gate's `input_digest` unchanged,
even if a whole-plan digest changes. A global `plan_revision` is a fence/audit value, not an automatic invalidation trigger.

The Gate-level `input_sources` table is the union of the sources used by that Gate. Each check records a sorted
`input_source_ids` subset into that table; a check-specific source is still included in the union. This makes the exact
per-check input set inspectable without duplicating source descriptors and lets a source change identify every affected Gate.

External sources remain default-deny. If a future task explicitly authorizes one, its route/provider, bounded input digest,
response/artifact digest, and authorization-envelope digest belong in the source manifest. An absent or expired authorization
is not a reason to reuse old evidence. Any authority-boundary change still requires the superseding-task procedure; a
per-Gate authorization digest is provenance, not permission to widen an existing task. This design does not grant any
external authority to the current task.

### 3.2 Check `input_digest`

For check `c`, compute:

```text
c.input_digest = SHA256(canonical_json({
  schema_version: 1,
  gate_id,
  gate_revision,
  check_id,
  check_revision,
  command_spec_digest,
  input_source_ids: source_ids_sorted_by_source_id,
  input_sources: resolved_sources_sorted_by_source_id,
  runner_policy_digest
}))
```

The manifest includes the exact command/arguments, working-tree binding, base when applicable, success predicate, bounded
timeout, and all declared input source digests through `command_spec_digest` and `runner_policy_digest`. It excludes the
result, evidence output, timestamps, and conversation labels. Thus a rerun with the same inputs has the same
`input_digest`, while a changed command, source, base, toolchain, or policy does not.

### 3.3 Gate `input_digest`

For Gate `g`, compute:

```text
g.input_digest = SHA256(canonical_json({
  schema_version: 1,
  gate_id,
  gate_revision,
  required,
  gate_definition_digest,
  input_sources: gate_sources_sorted_by_source_id,
  checks: [
    {check_id, check_revision, input_digest}
  ] sorted_by_check_id,
  runner_policy_digest
}))
```

The Gate digest is not formed by concatenating command text or by hashing an unordered map. It is the digest of the complete
normalized manifest, including every check's input digest. A change to one check therefore changes that Gate's digest without
requiring unrelated Gate digests to change.

The compatibility aggregate is:

```text
gate_input_digest = SHA256(canonical_json({
  schema_version: 1,
  release_task_id,
  release_head_sha,
  gates: [
    {gate_id, gate_revision, required, input_digest}
  ] sorted_by_gate_id
}))
```

This aggregate is useful for detecting that some per-Gate input changed, but it cannot identify the affected Gate. It
deliberately excludes the whole mutable plan digest, plan bookkeeping, and global registry digest. Any consumer that needs
selective invalidation must compare the individual Gate manifests and their relevant source projections.

### 3.4 Check and Gate `evidence_digest`

The check evidence digest binds the observed result to the exact inputs:

```text
c.evidence_digest = SHA256(canonical_json({
  schema_version: 1,
  gate_id,
  gate_revision,
  check_id,
  check_revision,
  input_digest,
  result,
  exit_code,
  stdout_digest,
  stderr_digest,
  observed_artifacts: artifacts_sorted_by_locator,
  runner_digest,
  execution_ref,
  observed_at
}))
```

`stdout_digest` and `stderr_digest` are digests of captured output, not permission to store the output in a state card. A
check failure caused by a test assertion may be a valid `FAIL`; an infrastructure error, timeout without a defined result,
missing artifact, or interrupted run has no valid PASS/FAIL evidence and makes the Gate `STALE`.

The Gate evidence digest binds its complete current result:

```text
g.evidence_digest = SHA256(canonical_json({
  schema_version: 1,
  gate_id,
  gate_revision,
  input_digest,
  checks: [
    {check_id, check_revision, result, evidence_digest}
  ] sorted_by_check_id
}))
```

An evidence digest that is copied to a different `input_digest`, Gate identity, release head, or check identity is invalid.
Master must recompute or independently verify these envelopes and the actual execution provenance. A digest is an integrity
check, not a grant of authority.

## 4. Invalidation and aggregation

### 4.1 Evaluation order

Master evaluates an existing record against the current integrated tree and plan in this order:

1. Validate the evidence envelope, identities, required Gate registry, digest formats, and exact field set. A changed global
   registry summary is diagnostic; compare each Gate's selected registry definition and requiredness source instead.
2. If there is no evidence and no legacy record, return `NONE`.
3. If the record is legacy-only, malformed, duplicated, has an unknown required Gate, or has any unverifiable digest,
   mark the known rows stale and use the whole-candidate fallback.
4. Compare candidate identity using only `release_task_id` and `release_head_sha`. If
   `current.release_head_sha != record.release_head_sha`, mark every Gate `STALE`. Do not attempt path disjointness or
   patch equivalence as a shortcut; the repository contract binds evidence to the full integrated SHA.
5. If the head is equal, derive the current normalized input manifest for every required Gate. Do not invalidate a Gate merely
   because the whole plan's `plan_revision`, `record_revision`, `updated_at`, or `plan_digest` changed. Compare the Gate's
   selected relevant plan/task/acceptance/authorization/registry/projection/toolchain source digests instead.
6. Compare each Gate's exact `input_digest` and verify its Gate/check evidence digest. Equal manifests retain their current
   status; any changed, missing, or unverifiable manifest makes only that Gate `STALE` when the Gate registry and source
   dependency map are valid.
7. Recompute the compatibility `gate_input_digest` from the current Gate rows. A mismatch is diagnostic; it never authorizes
   selective reuse by itself.
8. Aggregate the candidate using the precedence below. Persist the status transition atomically with the evidence record.

### 4.2 Selective invalidation

Suppose Gate `targeted-tests` consumes `integrated-tree` and the relevant acceptance-policy slice
`dispatch-plan#task.targeted-tests.acceptance`, while `base-relative-audit` consumes `integrated-tree` and `base-tree`. If a
semantic acceptance predicate changes in the plan but no repository file changes, the release head remains unchanged and only
`targeted-tests` becomes `STALE`; `base-relative-audit` may retain current evidence. The candidate still becomes `STALE`
because a required Gate is incomplete. After the stale Gate is rerun and verified, the candidate can return to `PASSED` if no
other required Gate is stale or failed.

If a plan write changes only `record_revision`, `updated_at`, or another status-only field excluded from the selected
`dispatch-plan` slice, no Gate becomes stale. The whole `plan_digest` may change, but it is audit metadata and is not a
selective invalidation input. Conversely, changing the tracked `scripts/validate_contracts.py` file changes the integrated Git
tree and therefore produces a new `release_head_sha`; that event invalidates every Gate. It is never a valid same-HEAD
selective-invalidation example.

An input shared by multiple Gates invalidates every Gate that declares that source. A Gate that fails to declare a consumed
source is a provenance defect, not permission to reuse the evidence. If source-to-Gate dependency data is missing, stale, or
ambiguous, use the whole-candidate fallback.

### 4.3 Conservative whole-candidate `STALE` fallback

The following conditions mark all candidate evidence `STALE`, even if some rows appear individually unchanged:

- `release_head_sha` changed;
- legacy evidence has only aggregate `gate_input_digest` provenance;
- the required Gate set is missing or changed without a compatible migration;
- the source dependency map cannot be reconstructed;
- a required Gate/check is missing, duplicated, unknown, or has an invalid identity;
- any input/evidence digest is malformed or does not recompute;
- an evidence result cannot be tied to the exact integrated tree and bounded runner;
- plan, acceptance, authority, or generated-projection changes cannot be mapped to affected Gates;
- a record is partially written or mixes revisions from different plan fences.

Whole-candidate stale means “not currently approved,” not “the product failed.” It preserves historical evidence for audit but
requires all required Gates covered by the fallback to be rerun before `PASSED` can be declared.

### 4.4 Aggregate status precedence

Use this deterministic rule after per-Gate validation:

```text
if there is no evidence and no legacy material:
    candidate.status = NONE
elif any required Gate is missing, NONE, STALE, legacy, or unverifiable:
    candidate.status = STALE
elif any required Gate is FAILED with valid current evidence:
    candidate.status = FAILED
elif every required Gate is PASSED with valid current evidence:
    candidate.status = PASSED
else:
    candidate.status = STALE
```

`STALE` takes precedence over `FAILED`: a current failure plus an unrelated stale Gate is not a complete current result. An
empty required Gate set is a plan error and cannot produce `PASSED`. Optional Gates affect the candidate only according to an
explicit `required: false` declaration in the current registry; unknown requiredness is whole-candidate `STALE`.

When a new head is observed, do not overwrite the old `release_head_sha` while leaving old rows marked `PASSED`. Either keep
the historical record at its original head with status `STALE`, or atomically replace the entire record with a new-head record
whose required Gate rows are newly evaluated.

## 5. Migration from aggregate-only evidence

### 5.1 Legacy detection

Legacy evidence is a record with the current v1 `checks` array and an aggregate `gate_input_digest`, but no stable Gate rows
with per-Gate and per-check input manifests. A command string, array order, or aggregate hash is not a stable Gate identity.

### 5.2 Safe default migration

Migration is lossless and idempotent:

1. Preserve the original record under a `legacy` audit field or immutable historical record, including its original
   `release_head_sha`, status, checks, and `gate_input_digest`.
2. Record the digest of the legacy object and a migration reason such as `LEGACY_AGGREGATE_ONLY`.
3. Do not synthesize `gate_id` from the command, list index, or timestamp. Do not copy the aggregate digest into every
   per-Gate `input_digest`.
4. Set the current candidate status to `STALE` for any legacy record that contains evidence, including legacy `PASSED` and
   legacy `FAILED`. Legacy `NONE` with no checks and no digest may remain `NONE`.
5. Require a fresh, Master-verified run for every required Gate. Only then may new per-Gate rows be current and the aggregate
   status become `PASSED` or `FAILED`.

This intentionally sacrifices reuse of an old `PASSED` result when the old record cannot prove per-Gate provenance. It prevents
one changed input from being mistaken for an unaffected Gate.

The preserved legacy-only v2 record is therefore an audit waypoint, not a terminal dead end. Historical transition validation
may replace it with a fresh per-Gate rerun only when the new record has `legacy: null`, keeps the same non-null
`release_task_id` and exact `release_head_sha`, uses a non-regressing Master plan fence, and independently validates its full
current registry, source map, check provenance, input digests, and evidence digests. No aggregate or check digest from the
opaque legacy object may be reused. The Master record revision and timestamp still advance monotonically. Rewriting the
legacy-only object, promoting it without complete current evidence, or changing identity, head, plan authority, registry,
provenance, or digests remains an H25 failure.

### 5.3 Optional exact legacy adapter

A future migration tool may use a versioned adapter only if it has the complete old Gate registry, the exact old digest
algorithm, a one-to-one command-to-check mapping, and all source values needed to recompute the legacy aggregate. Even then,
the default result remains `STALE` until a fresh run binds evidence to the new per-Gate format. An adapter may produce
audit-only `MIGRATED_LEGACY` rows to guide reruns, but it must never promote an opaque or partially reconstructed legacy
`PASSED` record. The migration is valid only when it is idempotent and preserves the original bytes/digests.

## 6. Evidence fixtures

The fixtures below are examples for the proposed projection, not inputs to the current v1 validator. The repeated hexadecimal
values are format-valid illustrative digests; an implementation fixture must recompute every digest from its exact canonical
payload rather than copying these examples.

### 6.1 Valid current candidate

Both required Gates have current evidence for the same integrated head. The top-level `gate_input_digest` is a derived summary.

```yaml
schema_version: 2
release_task_id: mwr-hardening-2026-08-30
release_head_sha: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
plan_revision: 1
plan_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
gate_registry_digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
gate_input_digest: sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
status: PASSED
legacy: null
gates:
  - gate_id: targeted-tests
    gate_revision: 1
    required: true
    status: PASSED
    input_digest: sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    evidence_digest: sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
    input_sources:
      - source_id: integrated-tree
        kind: git-commit
        locator: master-integrated-tree
        revision: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
        value_digest: sha256:1111111111111111111111111111111111111111111111111111111111111111
      - source_id: validator
        kind: file
        locator: scripts/validate_contracts.py
        revision: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
        value_digest: sha256:2222222222222222222222222222222222222222222222222222222222222222
    checks:
      - check_id: contract-validator
        check_revision: 1
        command: python3 scripts/validate_contracts.py
        input_source_ids: [integrated-tree, validator]
        result: PASS
        input_digest: sha256:3333333333333333333333333333333333333333333333333333333333333333
        evidence_digest: sha256:4444444444444444444444444444444444444444444444444444444444444444
        execution_ref: local-master-run-001
        observed_artifacts: []
  - gate_id: base-relative-audit
    gate_revision: 1
    required: true
    status: PASSED
    input_digest: sha256:5555555555555555555555555555555555555555555555555555555555555555
    evidence_digest: sha256:6666666666666666666666666666666666666666666666666666666666666666
    input_sources:
      - source_id: integrated-tree
        kind: git-commit
        locator: master-integrated-tree
        revision: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
        value_digest: sha256:7777777777777777777777777777777777777777777777777777777777777777
      - source_id: frozen-baseline
        kind: git-commit
        locator: task-frozen-baseline
        revision: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
        value_digest: sha256:8888888888888888888888888888888888888888888888888888888888888888
    checks:
      - check_id: diff-integrity
        check_revision: 1
        command: git diff --check
        input_source_ids: [integrated-tree, frozen-baseline]
        result: PASS
        input_digest: sha256:9999999999999999999999999999999999999999999999999999999999999999
        evidence_digest: sha256:abababababababababababababababababababababababababababababababab
        execution_ref: local-master-run-002
        observed_artifacts: []
```

### 6.2 Valid selective-stale candidate

Here only `targeted-tests` consumed a changed acceptance-policy slice. No repository file changed, so the candidate keeps the
same `release_head_sha`; the unaffected Gate remains current, but the aggregate is correctly `STALE` until the affected Gate
is rerun.

```yaml
schema_version: 2
release_task_id: mwr-hardening-2026-08-30
release_head_sha: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
# A semantic plan revision is context here; candidate identity is still release_task_id + release_head_sha.
plan_revision: 2
plan_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
gate_registry_digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
gate_input_digest: sha256:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd
status: STALE
legacy: null
gates:
  - gate_id: targeted-tests
    gate_revision: 1
    required: true
    status: STALE
    input_digest: null
    evidence_digest: null
    input_sources:
      - source_id: acceptance-policy
        kind: acceptance
        locator: dispatch-plan#task.targeted-tests.acceptance
        revision: plan-revision-2
        value_digest: sha256:abababababababababababababababababababababababababababababababab
    checks: []
    invalidation_reason: INPUT_SOURCE_CHANGED
  - gate_id: base-relative-audit
    gate_revision: 1
    required: true
    status: PASSED
    input_digest: sha256:5555555555555555555555555555555555555555555555555555555555555555
    evidence_digest: sha256:6666666666666666666666666666666666666666666666666666666666666666
    input_sources:
      - source_id: integrated-tree
        kind: git-commit
        locator: master-integrated-tree
        revision: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
        value_digest: sha256:7777777777777777777777777777777777777777777777777777777777777777
      - source_id: frozen-baseline
        kind: git-commit
        locator: task-frozen-baseline
        revision: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
        value_digest: sha256:8888888888888888888888888888888888888888888888888888888888888888
    checks:
      - check_id: diff-integrity
        check_revision: 1
        command: git diff --check
        input_source_ids: [integrated-tree, frozen-baseline]
        result: PASS
        input_digest: sha256:9999999999999999999999999999999999999999999999999999999999999999
        evidence_digest: sha256:abababababababababababababababababababababababababababababababab
        execution_ref: local-master-run-002
        observed_artifacts: []
```

### 6.3 Invalid evidence examples

```yaml
# Invalid: duplicate stable Gate identity and an aggregate PASSED status.
gates:
  - gate_id: targeted-tests
    gate_revision: 1
    status: PASSED
    input_digest: sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    evidence_digest: sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
  - gate_id: targeted-tests
    gate_revision: 1
    status: PASSED
    input_digest: sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    evidence_digest: sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
status: PASSED
```

```yaml
# Invalid: the check input changed but its old evidence digest was reused.
check_id: contract-validator
check_revision: 1
input_digest: sha256:abababababababababababababababababababababababababababababababab
result: PASS
evidence_digest: sha256:4444444444444444444444444444444444444444444444444444444444444444
```

```yaml
# Legacy-only: syntactically recognizable, but not current per-Gate evidence.
schema_version: 1
release_head_sha: 595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37
gate_input_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
status: PASSED
checks:
  - command: python3 scripts/validate_contracts.py
    result: PASS
    evidence_digest: sha256:4444444444444444444444444444444444444444444444444444444444444444
```

The first two records are rejected or marked stale during validation. The legacy record is preserved as history and migrated
to current `STALE`; it is never automatically promoted to `PASSED`.

## 7. Negative-test matrix

The future validator and Master gate evaluator should cover at least this matrix. “Reject” means the record is not accepted as
current evidence; when a durable candidate status is required, the safe persisted result is `STALE`.

| ID | Mutation or condition | Expected per-Gate result | Expected candidate result |
| --- | --- | --- | --- |
| N01 | Duplicate `(gate_id, gate_revision)` | Reject duplicate; no merge by position | `STALE` |
| N02 | Unknown Gate or check ID | Reject the unknown row | `STALE` |
| N03 | Required Gate missing | Missing row is not implicitly passed | `STALE` |
| N04 | `status: PASSED` with a Gate `STALE` or missing input digest | Do not accept PASS | `STALE` |
| N05 | Stored `input_digest` differs from Master-derived digest | Affected Gate `STALE` | `STALE` |
| N06 | Check input changed while old `evidence_digest` is reused | Reject evidence binding | `STALE` |
| N07 | Gate evidence digest does not recompute from check rows | Reject Gate evidence | `STALE` |
| N08 | Check says PASS but exit code/artifact/provenance contradicts it | No valid PASS/FAIL result | `STALE` |
| N09 | Current head differs from stored `release_head_sha` | Every Gate `STALE` | `STALE` |
| N10 | One declared source changes, with a valid dependency map | Only dependent Gates `STALE` | `STALE` while any required Gate is stale |
| N11 | A source changes, but the dependency map is missing or ambiguous | All Gates `STALE` | `STALE` |
| N12a | Plan write changes only `record_revision`, `updated_at`, or an excluded status-only field | No Gate invalidation | Existing aggregate status may remain unchanged |
| N12b | A semantic plan/acceptance/authorization/projection source changes with a valid per-Gate map | Only dependent Gates `STALE` | `STALE` while any required Gate is stale |
| N12 | Plan, acceptance, authorization, or projection changes with no affected-Gate mapping | All Gates `STALE` | `STALE` |
| N13 | A Gate definition/requiredness source changes, or the whole required Gate set changes | Affected Gate `STALE`; a required-set change makes the aggregate incomplete | `STALE` |
| N14 | Legacy v1 record has only aggregate `gate_input_digest` | Preserve as legacy; no synthetic per-Gate digest | `STALE` |
| N14a | Preserved legacy-only v2 is followed by a complete independent rerun for the same task/head | Replace audit waypoint with fresh per-Gate rows; reuse no legacy digest | Freshly aggregate to `PASSED` or `FAILED` |
| N15 | Legacy v1 record has `status: NONE` and no checks/digest | No evidence to invalidate | `NONE` |
| N16 | Current required Gates all pass, one optional Gate fails, and `required: false` is explicit | Required rows remain current; report optional failure | `PASSED` according to the declared policy |
| N17 | Optional/required classification is absent or unknown | Classification cannot be trusted | `STALE` |
| N18 | Secret or unbounded output appears in a persisted source/evidence field | Reject persistence and redact from state | `STALE` |
| N19 | Record mixes plan revisions or is partially written | Reject mixed-fence record | `STALE` |
| N20 | One current required Gate fails and another required Gate is stale | Preserve valid failure as history, but stale wins aggregation | `STALE` |
| N21 | Tracked `scripts/validate_contracts.py` changes in the integrated tree | New `release_head_sha`; every Gate `STALE` | `STALE` |

## 8. Adoption boundary

This design intentionally leaves implementation work for a future authorized contract task:

- extend the schema with the candidate binding, Gate/check identities, source manifests, and nullable stale-row semantics;
- update the validator with canonical digest recomputation, migration handling, and the negative tests above;
- update the Master card and Dispatch/Worker evidence projections without changing Worker authorization boundaries;
- recompute all final evidence from the integrated Master tree and invalidate current release-candidate evidence whenever the
  integrated head or a mapped Gate input changes.

For this task, only this design document and the ignored Worker card are in scope. No schema, validator, runtime, external
service, publication, or production behavior is changed.
