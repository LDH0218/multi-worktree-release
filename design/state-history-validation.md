# Historical State Validation Design

Status: design-only proposal for schema version 1. This document does not change the JSON Schema, the state records, or
the validator implementation.

## 1. Purpose and boundaries

The current validator checks each current snapshot independently. Its transition tables are exercised by self-tests, but
there is no way to provide the previous persisted snapshot that preceded a current one. This design adds a validation
model for a previous/current pair for the Dispatch Plan, Worker Card, and Master Card.

The design must preserve the following boundaries:

- A previous snapshot is evidence, not an instruction and never authorizes a write, run, publication, synchronization, or
  recovery action.
- Schema version 1 remains the field and enum authority. Historical validation adds relationships between two already-valid
  snapshots; it does not weaken current-snapshot validation.
- A snapshot is one complete JSON object. No implicit merge, patch, log replay, Markdown parsing, or “best effort” field
  filling is allowed.
- Git ancestry, commit reachability, test output, and release-system authorization remain separate Master gates. The CLI
  may validate the SHA shape and record relationships, but must not claim those external facts from a card field alone.
- This Worker supplies the design only. Implementing the flags or changing the contract files is out of scope.

## 2. CLI input model and compatibility

### 2.1 Existing and new options

The current options remain unchanged:

| Role | Current snapshot option | Input |
| --- | --- | --- |
| Dispatch Plan | --plan PATH | One UTF-8 JSON Dispatch Plan |
| Task specification | --task-spec PATH | One UTF-8 JSON Task Spec |
| Worker Card | --worker-card-json PATH | One UTF-8 JSON Worker Card |
| Master Card | --master-card-json PATH | One UTF-8 JSON Master Card |

Add exactly these optional previous-snapshot options:

| Role | Previous snapshot option | Pairing rule |
| --- | --- | --- |
| Dispatch Plan | --previous-plan PATH | Requires --plan PATH |
| Worker Card | --previous-worker-card PATH | Requires --worker-card-json PATH |
| Master Card | --previous-master-card PATH | Requires --master-card-json PATH |

Each PATH is opened read-only as UTF-8 JSON. The previous Worker Card option accepts the same JSON object accepted by
--worker-card-json; it does not parse the Markdown WORKTREE_TASK.md projection. A caller that wants to validate that
projection must first provide a contract-approved JSON export in a separate workflow.

The options are independent. A caller may validate only one record pair, or may provide all three pairs for a complete
historical cross-record check. A previous option without its current counterpart is a CLI input error, not a transition
failure. A missing file, malformed JSON document, schema-version mismatch, or incomplete object is a contract failure.

The plan's referenced Task Specs remain part of plan validation. For a previous plan, every referenced
task_spec_path must exist and contain the exact digest recorded by that historical plan. A current Task Spec file must
not be used as a substitute for an unavailable historical Task Spec. This prevents a mutable path from rewriting history.

### 2.2 Invocation modes

There are two modes:

1. **Current-only mode:** no previous option is supplied. Existing current-snapshot validation, self-tests, output, and exit
   behavior remain unchanged. In particular, an existing invocation such as
   python3 scripts/validate_contracts.py --plan CURRENT --task-spec TASK does not acquire a historical requirement.
2. **Historical mode:** at least one previous option is supplied. The corresponding current and previous objects are both
   validated, then their transition is checked. Current inputs not paired with a previous input are still current-validated,
   but no transition is inferred for them.

In historical mode, checks involving an omitted record are reported as NOT_RUN, never as PASS. Therefore a partial
invocation can prove the supplied pair, but it must not report “complete three-record history validated.” A release gate that
requires a complete bundle must require all three previous options and reject any NOT_RUN cross-record check. No new
strict-mode flag is needed for this design.

Use stable exit meanings:

- 0: every requested current, previous, transition, and executed cross-record check passed. Partial history is allowed only
  with an explicit partial result in the report.
- 1: a loaded snapshot, digest, transition, or executed cross-record check failed.
- 2: CLI usage failed, including a previous option without its current counterpart.

--skip-self-test may skip the existing self-test suite as it does today, but it must never skip snapshot or transition
validation. Historical validation is not merely a self-test.

### 2.3 Load and report order

The implementation should process inputs in this order, without changing any file:

1. Parse CLI arguments and enforce each previous/current pairing.
2. Load and validate all supplied current objects using the existing validators.
3. Load and validate all supplied previous objects using the same schema and digest checks.
4. Validate each supplied previous/current pair.
5. Validate cross-record consistency separately for the previous set and the current set, then validate the cross-record
   transition. Never combine a previous Plan with current cards or vice versa.
6. Print a deterministic report and return the exit code above.

For each JSON snapshot, compute a report-only snapshot_digest as the canonical SHA-256 of the parsed object. For Plan and
Task Spec records this supplements their contract digest; for Worker and Master Cards it supplies an identity for evidence
without adding a schema field. Report digests use the existing sha256:<64 lowercase hex> format and contain no secrets.

An illustrative historical report is:

    mode=historical
    record=worker-card
    previous_snapshot_digest=sha256:...
    current_snapshot_digest=sha256:...
    state_transition=ACTIVE -> AWAITING_INTEGRATION
    record_revision=7 -> 8
    checks=record_revision,state,identity,evidence
    cross_record=plan-worker:PASS,worker-master:PASS
    result=PASS

The report must distinguish PASS, FAIL, and NOT_RUN; an omitted previous record must be visible to a reviewer.

## 3. Common previous/current rules

### 3.1 Snapshot validity precedes transition validity

Both snapshots must independently pass the existing current validators before comparison. This includes exact top-level
fields, enum values, absolute paths, RFC 3339 timestamps, SHA shape, authorization completeness, and self-digests where the
contract defines them. A pair cannot turn an invalid current or previous object into a valid one.

The comparison uses parsed values and the canonical structured-data rules already used by the validator:

- null, booleans, integers, strings, arrays, and objects with string keys only;
- object keys sorted recursively, array order preserved, UTF-8 JSON without insignificant whitespace;
- no floating-point digest input;
- exact string preservation.

### 3.2 Record revision and time ordering

record_revision is the persistence-write fence for all three record types:

- If the previous and current records have the same record_revision, every other field must be identical. This is an
  idempotent replay, reported as NOOP; a changed payload with the same revision fails.
- If the current record has a greater record_revision, the comparison is a forward snapshot. Gaps are allowed because
  intermediate snapshots may not have been retained; the current revision need not equal previous plus one.
- A lower current record_revision always fails.
- updated_at may not move backwards. A changed timestamp requires a greater record_revision; a same-revision replay keeps
  the timestamp identical.

Every changed persisted record must therefore advance its record fence, while an exact duplicate may be safely revalidated.

### 3.3 Identity and digest immutability

The following identity is never changed in place for an active assignment:

task_id + task_spec_revision + task_spec_digest + source_thread_id

The plan additionally binds task identity to task_spec_path, owner_role, worktree, branch, and expected_head. The Worker
Card additionally binds worker_generation and frozen_baseline_sha. A changed objective, owner, worktree, expected head,
or authorization is a supersession, not an in-place revision, as required by the existing contract.

For the same task identity:

- a changed executable payload requires a higher task_spec_revision and a different task_spec_digest;
- an unchanged payload may be carried forward, including an explicitly recorded GRANDFATHER plan entry;
- an authorization-envelope digest change is always an authority-boundary change and requires a superseding task;
- a Worker or Master must not rewrite a handed-off worker_commit_sha; rework uses a successor task revision and commit.

The comparison treats omitted historical files, mismatched path contents, mismatched task-spec digests, and digest
collisions between equal identities as failures, not as new history.

## 4. Dispatch Plan transition rules

### 4.1 Plan-level monotonicity

plan_revision is non-decreasing. If it is unchanged, the semantic plan must be unchanged. A same-plan-revision update may
change only persistence or operational projections:

- record_revision, updated_at, and the recomputed plan_digest;
- task dispatch_status values, subject to the transition table;
- derived ready_wave, blocked_tasks, and validation results, provided they are recomputed from the unchanged plan.

Task IDs, task-spec paths and digests, dependency edges, parallel edges, ownership, worktrees, branches, expected heads,
revision decisions, and all other executable plan content must remain unchanged when plan_revision is unchanged. A semantic
change requires a higher plan_revision.

The current plan_digest and every historical plan_digest must equal the canonical digest of that complete snapshot. A plan
digest is recomputed after every accepted status-only or semantic update.

### 4.2 Dispatch-state transition

Allow the existing transitions, plus a same-state carry-forward:

| Previous | Current states allowed | Required evidence |
| --- | --- | --- |
| GATED | GATED, READY, CANCELLED, SUPERSEDED | blockers and preflight explain readiness or terminal decision |
| READY | READY, PUBLISHED, CANCELLED, SUPERSEDED | atomic persistence and publish/terminal evidence |
| PUBLISHED | PUBLISHED, BLOCKED, INTEGRATED, CANCELLED, SUPERSEDED | Worker exception, accepted mapping, or Master decision |
| BLOCKED | BLOCKED, PUBLISHED, CANCELLED, SUPERSEDED | blocker preservation and explicit recovery or terminal decision |
| INTEGRATED | INTEGRATED | terminal entry is preserved |
| CANCELLED | CANCELLED | terminal entry is preserved |
| SUPERSEDED | SUPERSEDED | terminal entry and replacement link are preserved |

Same-state rows are not permission to rewrite content; they cover a later record write with the same state and valid
operational evidence.

INTEGRATED, CANCELLED, and SUPERSEDED are terminal. No later snapshot may move them back to a live state, change their
task identity, or delete them. A task ID present in the previous plan must remain in the current plan, normally as the same
live entry or a preserved terminal entry. Removal without a terminal record is a history-loss failure.

### 4.3 Task revision decisions

For each task ID present in both plans:

- GRANDFATHER preserves the old task-spec digest and the old task_spec_plan_revision, even when the enclosing plan_revision
  increases.
- NEW and REVISE task specs bind to the current plan revision.
- REVISE requires a higher task-spec revision and a changed task-spec digest, with no supersession field changed.
- A changed objective, owner, worktree, expected head, or authorization cannot be represented as REVISE; the old task must
  be terminal and a new task with supersedes_task_id must carry the replacement.
- A task-spec revision or digest must not decrease or silently change under a terminal task.

New task IDs may be added only in a semantic plan revision and must satisfy the ordinary uniqueness, dependency,
worktree-availability, and overlap checks. Unchanged active tasks may continue across a plan revision only with a digest-
verified GRANDFATHER decision.

## 5. Worker Card transition rules

### 5.1 State transitions and evidence

The Worker Card has no terminal card state; IDLE is a cleared reusable state whose historical result is in last_task. Use
the existing state machine with explicit evidence:

| Previous | Current | Required evidence |
| --- | --- | --- |
| IDLE | IDLE | no active fields; default-deny authorization; unchanged or newer last_task |
| IDLE | ACTIVE | current plan/task match; all active identity fields populated |
| ACTIVE | ACTIVE | same assignment and authorization; only allowed progress/record fields changed |
| ACTIVE | AWAITING_INTEGRATION | atomic Worker commit exists in the handoff evidence; worker_commit_sha is full and integrated_as_sha is null |
| ACTIVE | BLOCKED | blocker_kind, blocker, blocked_since, and recovery_owner are present; assignment is preserved |
| ACTIVE | IDLE | explicit cancellation or supersession; last_task records the outcome; all active lock fields are cleared |
| AWAITING_INTEGRATION | AWAITING_INTEGRATION | handed-off commit and assignment identity are immutable |
| AWAITING_INTEGRATION | ACTIVE | explicit rework with a higher task revision/digest; old handoff remains immutable |
| AWAITING_INTEGRATION | BLOCKED | blocker evidence; handed-off commit is preserved |
| AWAITING_INTEGRATION | IDLE | accepted integration or recorded cancellation/supersession; last_task contains the mapping/outcome |
| BLOCKED | BLOCKED | blocker evidence remains present and assignment identity is preserved |
| BLOCKED | ACTIVE | explicit Master recovery; unchanged or valid higher task revision |
| BLOCKED | IDLE | recorded cancellation or supersession; active fields are cleared |

An ACTIVE -> IDLE transition is never a successful handoff. It is valid only for cancellation or supersession evidence.
Successful completion goes through AWAITING_INTEGRATION -> IDLE after Master acceptance.

### 5.2 Card field invariants

While the card is non-IDLE, its task ID, task-spec revision/digest/path, plan revision, dispatch wave, issuer, generation,
and frozen baseline remain equal to the bound plan/task unless this is the explicitly authorized higher-revision rework case.
allowed_paths, forbidden_paths, acceptance commands, and the complete authorization envelope remain unchanged for the
assignment.

The current card's authorization envelope digest must equal the persisted Task Spec's authorization digest. When the card
returns to IDLE, all active identity, scope, blocker, commit, release, and lock fields are null or empty as defined by the
existing schema, and the authorization object is exactly the canonical default-deny envelope. last_task preserves the
completed task identity, outcome, Worker SHA, and integration mapping.

worker_commit_sha is required for AWAITING_INTEGRATION, must not be replaced for the same task identity, and is never
treated as proof that Git ancestry or tests passed. Those facts remain handoff and Master-gate evidence.

## 6. Master Card transition rules

### 6.1 Master state and release lock

The Master Card state machine is:

| Previous | Current states allowed | Required evidence |
| --- | --- | --- |
| IDLE | IDLE, ACTIVE | no stale release lock, or a persisted current plan for activation |
| ACTIVE | ACTIVE, BLOCKED, IDLE | progress, blocker evidence, or completed/cancelled/superseded release |
| BLOCKED | BLOCKED, ACTIVE, IDLE | preserved blocker, explicit recovery, or reconciled terminal release |

While ACTIVE or BLOCKED, release_task_id, plan_revision, dispatch_plan_path, dispatch_plan_digest, and
frozen_baseline_sha identify one release task. An IDLE card clears those active release lock fields but may retain candidate
evidence as historical evidence.

### 6.2 Worker handoff history

worker_handoffs is append-only by the message identity task_id + task_spec_revision + task_spec_digest + source_thread_id.
A duplicate identity must have the same digest and immutable fields. It may move through the following evidence states:

| Previous handoff | Current handoff | Required evidence |
| --- | --- | --- |
| absent | RECEIVED | matching task and authorization/acceptance digests |
| RECEIVED | RECEIVED | no semantic change |
| RECEIVED | INTEGRATED | immutable Worker SHA and non-null integrated_as_sha mapping |
| RECEIVED | REWORK_REQUESTED | Master finding and successor-task/rework evidence |
| INTEGRATED | INTEGRATED | terminal mapping is unchanged |
| REWORK_REQUESTED | REWORK_REQUESTED | terminal historical handoff is unchanged |

INTEGRATED and REWORK_REQUESTED are terminal handoff states. Handoffs cannot be removed, reordered to conceal history,
or rewritten with a new Worker SHA. A higher task revision creates another handoff identity and leaves the old one intact.

### 6.3 Candidate evidence

Candidate evidence is keyed by the exact integrated-tree release_head_sha and gate_input_digest:

- NONE has null head and digest and an empty check list.
- PASSED or FAILED has a non-null head, gate-input digest, and non-empty checks; every check has an evidence digest.
- STALE preserves evidence that exists but is not usable for release.
- A change to integrated-tree HEAD invalidates all prior candidate evidence. The next snapshot must mark it STALE or
  clear it to NONE before new evidence is accepted.
- A changed plan, authorization, acceptance input, or generated projection invalidates the affected gate input digest. The
  affected evidence must be recomputed; unchanged gate evidence may remain valid only if its input digest is unchanged.
- A status flip with the same head and gate-input digest is not accepted without new check evidence. A PASSED result cannot
  silently become FAILED, or vice versa, by changing only the status.

PASSED is a Master declaration and requires the required integrated-tree and release gates to be present. The CLI checks
the evidence shape and record relationships; it does not independently execute those gates.

## 7. Cross-record consistency

Cross-record validation is run on the previous snapshot set and on the current snapshot set independently. When both sides
of a relationship are not supplied, the relationship is NOT_RUN, not inferred.

| Relationship | Required current/previous invariant |
| --- | --- |
| Plan ↔ Worker Card | A non-IDLE card maps to one plan task with equal task identity, path, owner, worktree, branch, baseline, and authorization digest. ACTIVE/AWAITING_INTEGRATION maps to PUBLISHED; BLOCKED maps to BLOCKED. An IDLE card has cleared active fields and its last_task maps to a preserved terminal plan entry when present. |
| Plan ↔ Master Card | A non-IDLE Master card's release lock matches the plan path, digest, release task, plan revision, and baseline. Each handoff identity refers to a plan task with matching task-spec, authorization, acceptance, wave, and baseline facts. |
| Worker Card ↔ Master Card | An AWAITING_INTEGRATION Worker has one matching RECEIVED handoff with the same Worker SHA and no integration mapping. An accepted INTEGRATED handoff maps to an IDLE Worker last_task or to the explicitly recorded completion checkpoint; a rework handoff maps to the successor task rather than mutating the old identity. |
| Candidate ↔ integrated work | PASSED candidate evidence has complete checks and an exact head/input digest. A changed integrated head or gate input cannot retain usable old evidence. |

The cross-record comparison must reject:

- a plan entry and Worker Card that disagree on task revision, digest, worktree, branch, baseline, or authorization;
- a Master handoff for an unknown task, an unknown task revision, or a different source thread;
- a Worker commit that differs from the matching handoff;
- a terminal plan task whose Worker Card still holds an active lock;
- a Master card that claims INTEGRATED while the matching Worker Card has changed identity or lost its handoff commit;
- a PASSED candidate while required handoffs or integrated-tree evidence are missing.

These checks operate on coherent snapshot sets. They do not permit an asynchronous mismatch to become a hidden exception.
Callers that intentionally inspect one side of an in-flight event should supply only that pair and accept the explicit
partial-history result.

## 8. Valid and invalid transition examples

The examples abbreviate unchanged fields with “same”; each real input remains a complete JSON object.

### 8.1 Valid examples

| Record | Previous → current | Why valid |
| --- | --- | --- |
| Plan | READY, record 4, plan 1 → PUBLISHED, record 5, plan 1 | Publish follows the table; task spec and plan digests are unchanged/recomputed, and persistence evidence exists. |
| Plan | PUBLISHED, record 5 → BLOCKED, record 6 | Worker exception preserves identity and records a blocker. |
| Plan | plan 1 → plan 2, active task remains revision 1 with GRANDFATHER and task_spec_plan_revision: 1 | Semantic plan revision preserves an unchanged active assignment correctly. |
| Worker | IDLE, record 1 → ACTIVE, record 2 | Persisted published task matches every active card identity field and default-deny envelope. |
| Worker | ACTIVE, record 7 → AWAITING_INTEGRATION, record 8 | Full Worker SHA is present, integration SHA is null, and acceptance evidence is handed off. |
| Worker | AWAITING_INTEGRATION, record 8 → IDLE, record 9 | Master accepted the commit; active fields are cleared and last_task stores COMPLETED plus the mapping. |
| Worker | AWAITING_INTEGRATION, task revision 1 → ACTIVE, task revision 2 | Explicit rework uses a higher revision and new digest; the original handoff remains immutable. |
| Master | RECEIVED handoff → INTEGRATED handoff | Worker SHA is unchanged and integrated_as_sha supplies the mapping. |
| Candidate | PASSED at head A → STALE at head B → PASSED at head B | Integrated-tree change invalidates old evidence before new gates establish a new candidate. |

### 8.2 Invalid examples

| Record | Previous → current | Failure |
| --- | --- | --- |
| Plan | INTEGRATED → PUBLISHED | Terminal dispatch state has an illegal outgoing transition. |
| Plan | task content changes with task-spec revision 1 → revision 1 | Executable content changed without a higher revision and new digest. |
| Plan | active task moves to a new worktree under the same task ID | Worktree identity changed; it requires supersession, not revision. |
| Plan | old task ID disappears from the current plan | Historical terminal evidence was deleted. |
| Worker | ACTIVE → IDLE with no cancellation/supersession outcome | Successful handoff was bypassed and last_task is incomplete. |
| Worker | AWAITING_INTEGRATION → ACTIVE with the same task revision/digest | Rework was requested without a successor task revision. |
| Worker | ACTIVE → BLOCKED with a changed authorization envelope | Authority changed in place; it requires supersession. |
| Master | INTEGRATED handoff has a different Worker SHA from RECEIVED | Handed-off evidence was rewritten. |
| Master | candidate remains PASSED after integrated HEAD changes | Old candidate evidence was not invalidated. |
| Cross-record | plan says PUBLISHED, Worker Card says BLOCKED | Dispatch and Worker state mapping disagree. |
| Cross-record | Worker SHA differs from matching Master handoff | The records do not describe the same handoff. |

## 9. Negative-test matrix

The following matrix is the minimum proposed test surface for a later implementation. “Fail” means exit code 1 unless
otherwise noted; “usage” means exit code 2. Tests use complete fixtures with only the listed field changed.

| ID | Inputs / mutation | Expected result |
| --- | --- | --- |
| H01 | --previous-plan PREV without --plan CUR | Usage failure; no file is loaded. |
| H02 | --previous-worker-card PREV without --worker-card-json CUR | Usage failure. |
| H03 | --previous-master-card PREV without --master-card-json CUR | Usage failure. |
| H04 | Previous path is absent or is a directory | Contract failure with the path; no fallback to current. |
| H05 | Previous JSON is malformed | Contract failure before transition checks. |
| H06 | Previous/current schema_version differs from 1 | Contract failure. |
| H07 | Current record_revision is lower than previous | Fail: revision regression. |
| H08 | Same record revision but changed timestamp or payload | Fail: changed snapshot reused a record fence. |
| H09 | updated_at moves backwards | Fail: time ordering. |
| H10 | Plan plan_revision decreases | Fail: semantic revision regression. |
| H11 | Same plan revision but dependency, worktree, or acceptance content changes | Fail: hidden semantic plan change. |
| H12 | Plan PUBLISHED -> READY | Fail: illegal dispatch transition. |
| H13 | Plan INTEGRATED -> BLOCKED | Fail: terminal state reopened. |
| H14 | Task revision decreases, or content changes with the same revision/digest | Fail: task identity/revision violation. |
| H15 | GRANDFATHER entry copies the new plan revision into task_spec_plan_revision | Fail: grandfather provenance was lost. |
| H16 | Previous plan references a missing or digest-mismatched historical Task Spec | Fail: previous plan cannot be verified. |
| H17 | Worker ACTIVE -> AWAITING_INTEGRATION without a Worker SHA | Fail: missing handoff evidence. |
| H18 | Worker ACTIVE -> IDLE with no cancellation/supersession outcome or uncleared fields | Fail: invalid reset. |
| H19 | Worker rework returns to ACTIVE without a higher task-spec revision | Fail: mutable handoff identity. |
| H20 | Worker non-IDLE task ID, baseline, worktree, or authorization differs from the plan | Fail: cross-record identity mismatch. |
| H21 | Worker BLOCKED has no blocker kind, blocker, blocked time, or recovery owner | Fail: incomplete exception evidence. |
| H22 | Master removes a prior handoff or changes its Worker SHA | Fail: append-only handoff violation. |
| H23 | Master marks a handoff INTEGRATED with null integrated_as_sha | Fail: missing integration mapping. |
| H24 | Candidate NONE retains a head, gate digest, or checks | Fail: invalid empty evidence. |
| H25 | Candidate remains PASSED after a release-head change | Fail: stale candidate accepted. |
| H26 | Candidate status flips with unchanged head/input and no new check evidence | Fail: unverifiable result change. |
| H27 | Current Master release lock points to a different plan path/digest or plan revision | Fail: plan/master mismatch. |
| H28 | Worker AWAITING_INTEGRATION has no matching Master RECEIVED handoff | Fail when both records are supplied; NOT_RUN if Master previous/current input is omitted. |
| H29 | Master INTEGRATED handoff has no matching Worker SHA/last_task mapping | Fail when both records are supplied. |
| H30 | Only one previous record is supplied and output claims complete three-record history | Fail report-contract test; partial result must be explicit. |
| H31 | No previous options, with the existing current-only fixture suite | Pass with legacy behavior and no historical requirement. |

## 10. Backward compatibility and rollout

The compatibility promise is intentionally narrow:

- Existing current flags and their meanings do not change.
- Omitting every previous option performs no historical comparison and does not require historical files.
- A previous option never changes or infers the current snapshot; it only adds checks after current validation.
- Existing schema validation and python3 scripts/validate_contracts.py self-tests remain passing.
- The first implementation should add focused unit fixtures for the matrix above and preserve the existing current-only
  command as a regression test.
- A caller can adopt history incrementally: first validate one record pair, then provide all three previous records and
  require that no cross-record check is NOT_RUN.

The design does not add a schema field for a previous snapshot, transition evidence, or snapshot history. Previous inputs
are CLI evidence for one validation invocation. Persisted history remains the responsibility of the Dispatch Plan, immutable
Task Specs, Worker Card last_task, Master handoffs, and the release evidence records.

## 11. Implementation acceptance checklist

A future implementation of this design is complete only when it:

1. Adds exactly the three previous options and enforces the current/previous pairing rules.
2. Validates both sides independently before comparing them.
3. Enforces record and semantic revision monotonicity, terminal states, immutable identity, digest integrity, and required
   transition evidence for all three record types.
4. Runs Plan/Worker/Master cross-record checks without mixing snapshot generations.
5. Emits deterministic evidence with PASS, FAIL, and NOT_RUN distinctions and the appropriate exit code.
6. Preserves current-only compatibility and does not parse WORKTREE_TASK.md implicitly.
7. Adds negative tests H01-H31 (or an equivalent complete matrix) and continues to pass
   python3 scripts/validate_contracts.py and git diff --check.
