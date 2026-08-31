# Historical Plan Locators

Status: normative design for a future CLI change; this task does not implement the
new options.

## 1. Problem and decision

Historical validation can load a previous Plan from an archived snapshot while the
Master Card continues to persist the stable, normative locator of the Plan.  Those
two strings identify different things:

1. The **physical snapshot path** identifies the JSON file that the validator opens,
   parses, and hashes for this invocation.  It may be an archive path and may be a
   symlink path.
2. The **effective normative locator** is the value used for Plan/Master identity
   checks.  It is an explicitly supplied locator when one is supplied; otherwise it
   is the canonical physical snapshot path, which is the legacy fallback.

The CLI will therefore add two optional arguments:

```text
--plan-locator PLAN_LOCATOR
--previous-plan-locator PREVIOUS_PLAN_LOCATOR
```

`--plan` and `--previous-plan` remain the physical snapshot options with their
current meanings.  A locator is invocation context only.  It is never copied into a
Plan, Worker Card, or Master Card, never used to open a JSON file, and never treated
as an authorization route, provider, or execution target.

This design resolves the archive/locator mismatch while preserving all existing
historical diagnostics H01-H31 and all existing invocations that omit the new
options.

## 2. CLI contract

### 2.1 Option relationships

Each locator has exactly one matching physical Plan option:

| New option | Required matching option | Meaning |
| --- | --- | --- |
| `--plan-locator` | `--plan` | Normative locator for the current Plan snapshot. |
| `--previous-plan-locator` | `--previous-plan` | Normative locator for the previous Plan snapshot. |

The following rules are hard usage rules:

* `--plan-locator` without `--plan` is invalid.
* `--previous-plan-locator` without `--previous-plan` is invalid.
* The existing rule that `--previous-plan` requires `--plan` remains unchanged.
  Consequently, a previous locator cannot make a previous-only invocation valid.
* `--previous-plan-locator` with `--previous-plan` but without `--plan` reports the
  existing H01 first; it does not introduce a second historical relationship.
* A locator is a single path argument.  It is not a list, URI, glob, or JSON value.
* The new options do not alter the meanings or required pairings of
  `--previous-worker-card` and `--previous-master-card` (H02 and H03).

The two locator arguments are optional independently.  Supplying one does not
implicitly derive or enable the other.  In particular, a current locator may be
provided in current-only mode, and a previous locator may be provided for a partial
history in which only a previous Plan is supplied.

### 2.2 Absolute-path rule

An explicitly supplied locator must be absolute.  The validator does not perform
application-side `~` expansion.  Relative values, including `.`/`..`-rooted values
and a literal value beginning with `~`, fail before any snapshot is loaded.  The
physical `--plan` and `--previous-plan` options retain their existing relative-path
behavior for compatibility.

Locator argument errors use exit code 2, the existing usage-error class.  They use a
new `L` diagnostic namespace so that the meanings and numbering of H01-H31 remain
stable:

| ID | Condition | Exit |
| --- | --- | --- |
| L01 | A locator is supplied without its matching physical Plan option. | 2 |
| L02 | A supplied locator is not absolute, or cannot be converted to the canonical
  path form under the rules in §3. | 2 |

Precedence is deterministic: validate the existing historical pairings H01-H03;
then validate locator pairings (L01); then validate locator path form (L02); only
then load physical snapshots and run the existing H04-H31 checks.  Thus an invocation
that violates both H01 and L01 reports H01, while an invocation that has valid
historical pairings but a relative locator reports L02.  No existing H diagnostic is
renumbered, repurposed, or hidden by a locator error.

### 2.3 Exit and mode compatibility

The existing result classes remain unchanged:

* exit 0 means every requested check passed;
* exit 1 means a loaded record, digest, transition, or cross-record check failed;
* exit 2 means command usage or argument validation failed.

Locator presence does not change the history mode.  Current-only, partial-history,
and complete-history invocations retain the state-history rules and explicit
`NOT_RUN` reporting defined by `design/state-history-validation.md`:

| Supplied historical inputs | Mode | Locator effect |
| --- | --- | --- |
| No previous options | Current-only | Current locator may override only the current Plan/Master comparison. |
| Previous Plan, optionally previous cards | Partial or complete according to existing rules | Previous locator applies only to that physical previous Plan. |
| Previous Plan plus both previous cards | Complete history | Current and previous locator checks are both independently required. |

Omitting both locator options is a strict compatibility mode: the validator uses the
same physical-path comparison that it uses today.  Existing Plan loading, schema
validation, digest validation, transition checks, H01-H31 meanings, exit codes, and
legacy current-only fixtures are unchanged.

## 3. Path model and normalization

The validator must keep the three path concepts below separate throughout one
invocation.  It must not replace one with another merely to simplify reporting.

| Name | Source | Used to read JSON? | Used for Plan/Master locator comparison? |
| --- | --- | --- | --- |
| `physical_input` | Exact value passed to `--plan` or `--previous-plan`. | Yes. | No, unless the locator is omitted and its canonical form is used as the fallback. |
| `physical_snapshot_path` | Canonical absolute form of `physical_input`. | It describes the opened snapshot and is the stable report identity. | Only as the legacy fallback. |
| `effective_locator` | Explicit locator, or `physical_snapshot_path` when omitted. | Never. | Yes; this is the sole expected path for the corresponding Master Card lock. |

The implementation should carry a value object equivalent to:

```text
PlanSnapshotRef {
  role: current | previous
  physical_input: string
  physical_snapshot_path: string
  effective_locator: string
  locator_source: explicit | physical-fallback
  snapshot_digest: sha256:<64 lowercase hex>
}
```

This is a report/runtime value, not a new persisted contract field.

### 3.1 Canonical form

For both physical paths and explicit locators, canonicalization uses the existing
POSIX path semantics and the equivalent of:

```python
Path(value).resolve(strict=False)
```

The rules are:

1. The physical input is opened using the supplied path under the existing H04/H05
   loading behavior.  A missing path or directory remains an existing physical-path
   failure; it is not converted into a locator-only success.
2. The canonical physical snapshot path is the absolute, normalized,
   symlink-resolved form of that input.
3. An explicit locator is checked for absoluteness first and then canonicalized with
   the same `resolve(strict=False)` algorithm.  Its target does not need to be an
   existing file because it is not opened.
4. `.` and `..`, repeated separators, and existing symlink components are resolved
   consistently.  POSIX case sensitivity is preserved; no case folding is applied.
5. The raw argument is retained for diagnostics.  Canonicalization never rewrites a
   JSON snapshot, a Master Card, or a persisted `dispatch_plan_path`.

Using the same canonicalization for the explicit and fallback forms preserves the
current `Path.resolve()` behavior when the new flags are omitted, including the
current behavior for symlinked physical paths.  It also makes a symlink locator
deterministic: a locator symlink resolving to the same canonical target matches,
while one resolving elsewhere does not.

The validator must not use a locator to locate or substitute a snapshot.  It reads
the physical input selected by `--plan`/`--previous-plan`, computes its digest, and
then uses the separately derived effective locator for identity checks.

### 3.2 Snapshot and contract digests

The parsed JSON at the physical snapshot path remains the sole input to its existing
schema, contract-digest, transition, and cross-record checks.  The report-only
`snapshot_digest` is computed from that parsed object exactly as specified by
`design/state-history-validation.md`.  Existing `plan_digest` and card digests keep
their current self-digest semantics.

The raw locator, canonical locator, `locator_source`, archive path, and invocation
role are not included in any persisted Plan or Card digest.  Two invocations may
read the same physical snapshot with different locator context; the snapshot and
record digests remain identical, while each invocation performs its own
Plan/Master locator check.

Historical Task Spec loading remains exact: a previous Plan must still reference
the historical Task Spec path and digest recorded in that archived Plan.  A current
Task Spec cannot be substituted merely because the physical previous Plan is stored
under an archive directory.  Locator selection does not relax H16 or any other
historical identity check.

## 4. Plan/Master consistency rule

`Master Card.dispatch_plan_path` is the persisted normative locator.  For every
Master Card that participates in the invocation, compare its canonical persisted
path to the effective locator of the Plan snapshot in the same record role:

```text
canonical(Master.dispatch_plan_path)
    == current_ref.effective_locator       # current Plan/Master pair

canonical(previous_Master.dispatch_plan_path)
    == previous_ref.effective_locator     # previous Plan/Master pair
```

The comparison is in addition to, and ordered with, the existing checks for
`dispatch_plan_digest`, `plan_revision`, `release_task_id`, and frozen baseline.
Those fields continue to be compared against the loaded Plan snapshot and current
history rules.  An IDLE Master with a null release lock continues to follow the
existing IDLE semantics; a locator flag does not manufacture a lock.

The consequences are explicit:

* With an explicit locator, the physical archive path is never compared to
  `Master.dispatch_plan_path`.
* Without an explicit locator, the canonical physical path is the exact legacy
  fallback and is compared as it is today.
* A persisted Master path that differs from the effective locator fails the existing
  H27 plan/Master mismatch check (exit 1).  H27 reports the actual persisted path,
  its canonical value, the expected effective locator, and whether that expectation
  came from `explicit` or `physical-fallback` context.
* There is no fallback from an H27 mismatch to the physical path, no attempt to
  rewrite the Master Card, and no automatic acceptance based only on equal Plan
  digests.
* Current and previous pairs are checked independently.  The current and previous
  effective locators need not be textually equal as a new standalone rule; they are
  valid when each corresponding Master lock and all existing historical checks are
  valid.  A stable normative locator for both records is the normal archive use
  case.

This preserves the distinction between content identity and locator identity: equal
Plan content does not permit a wrong release lock, and a different physical archive
path does not imply a different normative Plan when an explicit locator says
otherwise.

### 4.1 Cross-record validation order

After the option and path checks, validation proceeds in this order:

1. Load each physical snapshot and validate its schema and existing contract digest.
2. Derive `physical_snapshot_path`, `effective_locator`, and `snapshot_digest` for
   current and, if supplied, previous Plan roles.
3. Run all existing snapshot-to-snapshot history checks, including record/semantic
   revisions, transitions, historical Task Spec identity, and H01-H26/H30/H31
   behavior.
4. Run Plan/Worker and Plan/Master cross-record checks.  In the Master path portion,
   use the role-matched `effective_locator` and retain H27 as the failure ID.
5. Run the remaining handoff and candidate checks (H28-H29 and existing current
   behavior), then emit the report.

If a physical snapshot cannot be loaded, the existing physical-path diagnostic
 wins and no locator claim is inferred from a Master Card.  If a snapshot loads but
the Master lock mismatches, the result is H27 even if the physical file and Plan
digest are otherwise valid.

## 5. Reporting contract

The validator must distinguish physical and normative identities in both current and
historical output.  The machine-readable report adds the following fields to each
loaded Plan entry; additive fields do not invalidate existing consumers:

```text
record=dispatch-plan
role=current|previous
physical_input=<exact CLI path>
physical_snapshot_path=<canonical absolute path>
effective_locator=<canonical absolute locator>
locator_source=explicit|physical-fallback
snapshot_digest=sha256:<64 lowercase hex>
transition=<existing transition result>
```

The existing `plan_digest` remains separately reported and is not renamed to
`snapshot_digest`.  The report must not imply that the locator is part of either
digest.

For a Plan/Master check, include enough context to make an archive mismatch
diagnosable without opening another file:

```text
check=plan-master-locator
role=current|previous
master_dispatch_plan_path=<persisted value>
master_dispatch_plan_path_canonical=<canonical value>
expected_effective_locator=<canonical value>
locator_source=explicit|physical-fallback
result=PASS|FAIL|NOT_RUN
```

The human-readable legacy output keeps its existing check names and meanings.  A
new locator context line may be additive, but an omitted-locator invocation must
retain the existing result and exit behavior.  A `NOT_RUN` previous locator check
means the corresponding previous Plan/Master input was not supplied; it must not be
reported as a pass merely because a previous physical file was absent.

When a physical archive and an explicit locator differ, the report must show both.
When the locator is omitted, it must show `locator_source=physical-fallback` so a
reviewer can tell that the legacy comparison was intentionally used.  The validator
must never change `Master.dispatch_plan_path` in output or on disk to make these
values equal.

## 6. Historical and no-op examples

### 6.1 Current Plan with explicit locator

Invocation:

```text
validate --plan /repo/.codex/multi-worktree-release/dispatch-plan.json \
  --plan-locator /repo/.codex/multi-worktree-release/dispatch-plan.json
```

The current Master Card stores the same canonical `dispatch_plan_path`.  The
physical path and effective locator happen to be equal, but they are still recorded
as separate fields and the locator source is `explicit`.

### 6.2 Archived previous Plan with a fixed normative locator

Invocation:

```text
validate \
  --plan /repo/.codex/multi-worktree-release/dispatch-plan.json \
  --plan-locator /repo/.codex/multi-worktree-release/dispatch-plan.json \
  --previous-plan /archive/multi-worktree-release/dispatch-plan-r37.json \
  --previous-plan-locator /repo/.codex/multi-worktree-release/dispatch-plan.json
```

The previous snapshot is read and hashed from `/archive/.../dispatch-plan-r37.json`.
The previous Master Card may still persist:

```json
{"dispatch_plan_path": "/repo/.codex/multi-worktree-release/dispatch-plan.json"}
```

That is a valid match because the previous effective locator is the explicit fixed
normative path.  The archived Plan's historical Task Spec paths and exact digests
are still validated from the archived snapshot; the current Task Spec is not used
as a substitute.

### 6.3 Explicit locator mismatch

Suppose the physical previous Plan is `/archive/dispatch-plan-r37.json`, the
previous locator is `/repo/.codex/multi-worktree-release/dispatch-plan.json`, and
the previous Master persists `/archive/dispatch-plan-r37.json`.  The snapshot may
be perfectly valid, but the previous Plan/Master check fails H27 because the
persisted normative locator does not equal the explicit effective locator.  The
validator must not fall back to the archive path or rewrite the Master Card.

### 6.4 Symlinked physical snapshot and locator

Let `/archive/dispatch-plan-r37.json` be a symlink to
`/vault/plan-snapshots/r37.json`.

* `--previous-plan /archive/dispatch-plan-r37.json` reads the symlink-selected JSON,
  reports that exact `physical_input`, and derives the canonical physical path
  `/vault/plan-snapshots/r37.json` for the fallback case.
* Adding `--previous-plan-locator
  /repo/.codex/multi-worktree-release/dispatch-plan.json` makes the effective
  locator the canonical `/repo/.../dispatch-plan.json`, regardless of the archive
  location.  A Master with that fixed path passes.
* A locator symlink such as `/repo/current-plan.json ->
  /repo/.codex/multi-worktree-release/dispatch-plan.json` canonicalizes to the
  fixed target and passes.  A locator symlink resolving to a different path fails
  H27.

The symlink is never used to select a different JSON file after the physical Plan
option has been resolved.

### 6.5 No-op Plan

When current and previous physical snapshots contain the same Plan revision and
the same snapshot/contract content, the existing transition remains `NOOP`.  A
locator is not part of that transition calculation.  With current and previous
locators both matching their role-matched Master locks, the complete history check
passes and reports `NOOP` plus the two independent locator contexts.

If the same physical file is supplied for both roles but different explicit
locators are supplied, the snapshot transition is still evaluated according to the
existing no-op rules.  Locator checks are nevertheless performed independently; a
bad Master lock can still produce H27 and must not be hidden by `NOOP`.

## 7. Negative and positive test matrix

The future implementation should assert public arguments, output fields, diagnostic
ID, and exit code.  Existing H01-H31 fixture coverage remains mandatory.

| Case | Inputs/fixture | Expected result |
| --- | --- | --- |
| N01 | `--plan-locator /repo/plan.json` with no `--plan` | L01, exit 2; no snapshot load. |
| N02 | `--previous-plan-locator /repo/plan.json` with no `--previous-plan` | L01, exit 2; no snapshot load. |
| N03 | `--previous-plan /archive/r37.json --previous-plan-locator /repo/plan.json` with no `--plan` | H01 first, exit 2. |
| N04 | `--plan ./plan.json --plan-locator relative/plan.json` | L02, exit 2; physical path is not loaded. |
| N05 | `--plan plan.json --plan-locator ~/plan.json` (literal tilde) | L02, exit 2; no application-side tilde expansion. |
| N06 | Current-only `--plan /repo/plan.json --plan-locator /repo/plan.json`, matching current Master | Pass, exit 0; current-only history behavior and additive locator report. |
| N07 | Current-only `--plan /repo/plan.json --plan-locator /repo/normative.json`, current Master stores `/repo/normative.json` | Pass, exit 0; physical and effective paths are different and both are reported. |
| N08 | Current-only explicit locator, current Master stores the physical Plan path | H27, exit 1; no physical-path fallback. |
| N09 | `--previous-plan /archive/r37.json --previous-plan-locator /repo/plan.json`, partial history with no previous cards | Existing partial-history result; previous locator is used for any available check and omitted previous checks are `NOT_RUN`. |
| N10 | Complete history: current Plan/current locator plus archived previous Plan/previous locator and both previous cards, all role locks match | Pass when existing H01-H31 checks pass, exit 0. |
| N11 | Complete history with previous Master storing archive path while explicit previous locator is fixed normative path | H27, exit 1; archive path is not accepted as a fallback. |
| N12 | `--previous-plan /archive/r37.json` with no previous locator and previous Master storing the canonical archive path | Pass under legacy fallback if all other checks pass; report `physical-fallback`. |
| N13 | Same case as N12, but previous Master stores a fixed non-archive normative path | H27 under unchanged legacy physical-path behavior; adding the explicit previous locator is the migration path. |
| N14 | Physical Plan path is a symlink to a valid snapshot; no explicit locator | Existing resolved-physical fallback behavior; report raw input and canonical physical path. |
| N15 | Physical Plan path is a symlink; explicit locator symlink resolves to the Master’s canonical path | Pass if all records/digests match; locator is not opened. |
| N16 | Explicit locator symlink resolves to a different path than the Master lock | H27, exit 1. |
| N17 | Same revision and same snapshot for current/previous, matching current/previous locators | Existing `NOOP`, exit 0; locator context does not alter transition. |
| N18 | Same revision and same snapshot, but one role’s Master lock mismatches its effective locator | H27, exit 1; `NOOP` does not suppress cross-record validation. |
| N19 | Valid explicit locators but physical previous JSON is malformed or missing | Existing H04/H05 behavior, exit 1; locator does not bypass physical loading. |
| N20 | Physical previous JSON parses but its historical Task Spec is missing or digest-mismatched | H16, exit 1; no current Task Spec substitution. |
| N21 | Omit both new options for every existing current-only and historical fixture | Existing results and H01-H31 meanings unchanged; fallback is `physical-fallback`. |
| N22 | Same physical snapshot invoked once with no locator and once with an explicit equivalent locator | Same snapshot/Plan digests; independent reports, and equivalent Plan/Master result. |
| N23 | `--plan-locator` and `--previous-plan-locator` are both present but canonicalize to different valid paths | No standalone locator error; each role is checked against its own Master/history facts. |
| N24 | Explicit locator contains `.`/`..` or repeated separators but is absolute and resolves canonically | Pass path-form validation; comparison uses the canonical effective locator. |
| N25 | Current/previous Plan physical files are identical but their explicit locator contexts differ | Digest and transition remain content-based; any mismatch is reported only by the corresponding role’s cross-record check. |

The matrix deliberately includes both the archive-positive case and the legacy
archive-negative case.  This demonstrates that the new option is an explicit
migration fence rather than a silent change to old path semantics.

## 8. Implementation checklist and non-goals

An implementation is complete only when it can demonstrate all of the following:

1. Add the two options with the exact pairings and L01/L02 precedence above.
2. Keep `--plan`/`--previous-plan` as the only physical snapshot readers.
3. Derive and report both physical and effective values for current and previous
   roles.
4. Compare role-matched Master `dispatch_plan_path` values to effective locators,
   retaining H27 and the existing digest/revision/lock checks.
5. Preserve H01-H31, current-only behavior, partial-history `NOT_RUN` semantics,
   complete-history requirements, and exit classes.
6. Keep locator context out of Plan/Card snapshot and contract digests.
7. Cover the matrix in §7, including symlinks, no-op, malformed archive, digest
   mismatch, and fixed normative Master paths.
8. Run `python3 scripts/validate_contracts.py` and `git diff --check`.

This design does not authorize or require:

* any new JSON schema field or persisted `dispatch_plan_path` rewrite;
* copying, moving, repairing, or rewriting archived Plan/Task Spec/Card files;
* using a current Task Spec or current Plan as a historical substitute;
* changes to `SKILL.md`, `README.md`, `AGENTS.md`, `references/`, `scripts/`, or
  other governance paths;
* synchronization, merge, rebase, reset, push, publication, execution, or external
  calls.
