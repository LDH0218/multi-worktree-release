# Dispatch Graph Invariants

Status: normative design for `schema_version: 1`. This document defines the graph and derived-state rules that a Dispatch
Plan validator must enforce. It deliberately does not implement the validator or change the JSON Schema.

The existing contract has two representations of dependencies. Keeping them distinct is the central rule:

- A persisted Task Spec's `dependencies.blocked_by` is the static, direct dependency graph for that task assignment.
- A Dispatch Plan entry's `blocked_by` is the live subset of those direct dependencies that is still unresolved at the
  plan's current `record_revision`.

The Task Spec remains unchanged for a status-only update. Clearing a resolved live blocker therefore changes the plan's
`record_revision`, but not its `plan_revision` or the Task Spec revision/digest. Adding, removing, or replacing a static
edge is an executable-content change and follows the normal task/plan revision rules.

## 1. Model and canonical sets

Let `T` be the set of task IDs in the plan, and let `spec(v)` be the complete persisted Task Spec for task `v`. The validator
must load and digest-check every referenced Task Spec before it validates graph state. Missing or mismatched specs make the
plan invalid; conversation text cannot supply a missing edge.

For each task `v`, define:

```text
D(v) = set(spec(v).dependencies.blocked_by)
P(v) = set(spec(v).dependencies.parallel_with)
L(v) = set(plan entry v.blocked_by)
U(v) = { u in D(v) | status(u) != INTEGRATED }
```

`D` is the graph's authoritative direct-edge set. An edge `u -> v` means that `v` cannot become dispatch-eligible until `u`
is integrated. Only `INTEGRATED` satisfies a dependency. `READY`, `PUBLISHED`, and `BLOCKED` are not completion; neither
`CANCELLED` nor `SUPERSEDED` satisfies a dependency. A downstream task that points at a cancelled or superseded upstream
task must be revised or superseded rather than silently treating that edge as complete.

The plan entry's live blocker set is normally `L(v) = U(v)`. Terminal tasks are no longer schedulable, so their historical
plan entries must use `L(v) = empty` even if their old static Task Spec had unresolved dependencies. For a non-terminal task,
`blocked_by` contains direct IDs only, never transitive ancestors.

All ID arrays are sets for validation and are serialized in ascending lexical task-ID order for deterministic records:

- no duplicate IDs;
- no self-reference;
- every ID is in `T`;
- plan and Task Spec projections use the same canonical ordering;
- `parallel_with` is a symmetric relation, so `u in P(v)` iff `v in P(u)`.

The plan entry's `parallel_with` must equal `P(v)` from its persisted Task Spec. A mismatch is not repaired by normalizing one
side; it is a stale or tampered task specification and must fail validation.

## 2. Direct and transitive dependency rules

The direct dependency graph is `G = (T, D)`. Its transitive closure is:

```text
Anc(v) = union of {u} union Anc(u), for every u in D(v)
```

with an empty set for a root task. The following are mandatory:

1. `D(v)` has no unknown, repeated, or self-referenced ID.
2. `G` is acyclic. A path from a task back to itself is invalid even when every edge is in a different Task Spec.
3. `D(v)` is direct-only and transitively reduced. If `u` is already reachable from another direct dependency of `v`, listing
   `u` directly is redundant and invalid. For example, with `A -> B -> C`, `D(C) = [B]` is valid while `D(C) = [A, B]` is
   invalid. This keeps the meaning of `blocked_by` unambiguous and makes a single edge the only immediate blocker witness.
4. Every direct edge has strict wave order (`wave(u) < wave(v)`), which also holds for every transitive edge.
5. A plan entry may not invent a live blocker: for every non-terminal `v`, `L(v) = U(v)` exactly. It may not omit an unresolved
   direct dependency either.

The graph is not inferred from task-ID order, worktree numbering, branch names, or `parallel_with`. A task with no direct edge
is a root even if another task happens to have the same wave.

## 3. Parallel claims and conflicts

`parallel_with` is an explicit pairwise claim that two tasks are eligible for the same dispatch wave. It is not a transitive
closure and it need not list every pair of independent tasks. An absent pair is not itself an error; a present pair is a claim
that must pass every check below.

For every unordered pair `{u, v}` named by `parallel_with`:

- `u != v`, both IDs are known, and the claim is present in both lists;
- neither task is a direct dependency of the other;
- neither task is a transitive ancestor of the other (`u not in Anc(v)` and `v not in Anc(u)`);
- `dispatch_wave(u) = dispatch_wave(v)`;
- the pair has no semantic ownership overlap, including overlapping authoritative output paths, contract ownership, or a shared
  active worktree;
- any shared generated projection is allowed only when it is explicitly Master-owned and regenerated from integrated sources,
  not concurrently edited by either Worker.

The direct and transitive checks are both required. For `A -> B -> C`, declaring `A parallel_with C` is invalid even though the
plan does not contain a direct `A`/`C` edge. A task can be independent without being named as a parallel peer; the claim is
validated conservatively because it promises same-wave concurrency.

`parallel_with` is therefore disjoint from the comparability relation induced by `D`:

```text
parallel(u, v) => wave(u) = wave(v)
                 and u not reachable from v
                 and v not reachable from u
                 and no semantic ownership conflict
```

Different wave numbers do not make a dependency valid for parallel execution. They mean that the tasks belong to different
dependency frontiers; omit the pair or revise the dependency/work partition before claiming parallelism.

## 4. Dispatch-wave derivation

Waves are a static topological projection of `D`, not a counter that changes as statuses change. After cycle and reference
validation, compute them in topological order:

```text
W(v) = 1                                      if D(v) is empty
W(v) = 1 + max(W(u) for u in D(v))             otherwise
```

The persisted `dispatch_wave` must equal `W(v)` exactly for every task, including terminal historical entries. It is not enough
for it merely to be greater than each dependency's wave. Status-only changes clear entries from `L(v)` but never recalculate a
wave. Thus a task whose only dependency just became `INTEGRATED` can move from `GATED` to `READY` at the same unchanged wave.

Consequences:

- roots are wave 1;
- every direct dependency is in a strictly smaller wave;
- a task with two dependencies waits for the deeper dependency frontier;
- a declared parallel pair is in one equal wave;
- a wave gap or a manually lowered wave is invalid, even if the task happens not to be blocked in the current snapshot.

## 5. Status and live-blocker consistency

The following table is normative. `U(v)` is computed from the static Task Specs and current plan statuses, while `L(v)` is the
persisted plan entry's `blocked_by`.

| `dispatch_status` | Required `L(v)` | Dependency eligibility | `blocked_tasks` | `ready_wave` candidate |
| --- | --- | --- | --- | --- |
| `GATED` | `U(v)`; may be empty for a non-dependency gate | not eligible | yes | no |
| `READY` | empty | all `D(v)` are `INTEGRATED`; preflight/gates pass | no | yes |
| `PUBLISHED` | empty | all `D(v)` are `INTEGRATED`; assignment is in flight | no | yes |
| `BLOCKED` | `U(v)`; may be empty for a Worker/Master exception | not eligible | yes | no |
| `INTEGRATED` | empty | all `D(v)` are `INTEGRATED` | no | no |
| `SUPERSEDED` | empty | terminal historical record | no | no |
| `CANCELLED` | empty | terminal historical record | no | no |

Additional status rules:

- `READY`, `PUBLISHED`, and `INTEGRATED` must have an empty plan `blocked_by`. A non-empty list is a stale derived state.
- `GATED` is the normal pre-dispatch state for unresolved dependencies. It may have `blocked_by: []` only when a separate
  verified gate, such as worktree preflight or semantic ownership, is the reason for gating; it must not fabricate a task ID to
  represent that reason.
- `BLOCKED` may have `blocked_by: []` when the Worker exception is not a dependency. The blocker evidence belongs in the
  Worker/Master state record; the graph must not encode an exception as a false edge.
- A non-terminal task with a dependency on `BLOCKED`, `READY`, or `PUBLISHED` work has that upstream ID in `U(v)` and therefore
  cannot be `READY` or `PUBLISHED`.
- An upstream `CANCELLED` or `SUPERSEDED` task remains unresolved for any non-terminal dependent. Master must revise the
  dependency or supersede/cancel the dependent; treating cancellation as success is invalid.
- Terminal entries remain in the plan for historical identity and digest checks, but never enter the current blocked or ready
  projections.

The status transition table in `references/methodology.md` remains authoritative for lifecycle changes. These invariants only
define whether a persisted snapshot is self-consistent; they do not authorize a Worker to change Dispatch status.

## 6. Derived `blocked_tasks` and `ready_wave`

The two plan-level fields are pure projections and must be recomputed, not hand-maintained.

### `blocked_tasks`

```text
B = { v in T | status(v) in {GATED, BLOCKED} }
plan.blocked_tasks = sort_lexically(B)
```

The list is unique, known, and contains every gated or blocked task, including a task blocked for a non-dependency reason with an
empty `blocked_by`. It excludes `INTEGRATED`, `SUPERSEDED`, and `CANCELLED` tasks. A non-empty `blocked_by` is sufficient to
require the task's status to be `GATED` or `BLOCKED`, but it is not the complete definition of `blocked_tasks` because an
operational exception can have no dependency edge.

### `ready_wave`

This contract uses `ready_wave` as the current dispatch frontier. A `PUBLISHED` task remains part of the frontier while its wave
is in flight; this makes the projection stable across message delivery and explains why a plan can retain `ready_wave: 1`
after wave 1 has been published.

```text
R = { v in T | status(v) in {READY, PUBLISHED} and L(v) is empty }
plan.ready_wave = min(dispatch_wave(v) for v in R), or null when R is empty
```

The next new publication is selected from `READY` tasks at `ready_wave`. `PUBLISHED` tasks affect the frontier but are not
published again. `INTEGRATED` tasks are excluded because they are complete. If no task is `READY` or `PUBLISHED`, `ready_wave`
is `null`, even when the plan contains gated or blocked work. A plan must not report a later wave as ready while an earlier
active frontier remains in flight under this single-frontier model.

## 7. Validator procedure and failure semantics

The derived-state validator should apply these checks in order and report the first violated invariant with task IDs and the
computed/actual values:

1. Validate schema, plan/task-spec digests, absolute paths, and exact plan/task identity.
2. Index unique task IDs, load each complete Task Spec, and compare static `D`/`P` projections.
3. Reject unknown, duplicate, or self references; build `D` and test acyclicity.
4. Compute `Anc(v)` (or an equivalent reachability structure) and reject redundant transitive direct edges.
5. Validate symmetric `parallel_with`, incomparable endpoints, equal waves, and semantic ownership/worktree conflicts.
6. Derive `W(v)` and require exact equality with every persisted `dispatch_wave`.
7. Derive `U(v)` from current statuses and require the exact live `blocked_by` rule for each status.
8. Recompute `blocked_tasks` and `ready_wave` and compare their canonical values with the plan.
9. Only then mark the corresponding plan validation checks `PASS`. A failed derived-state check is a plan failure; it cannot be
   hidden by setting the existing summary flags to `PASS`.

Status-only recalculation must increment `record_revision` and update the plan digest. It must not change `plan_revision`, task
spec revision/digest, static edges, or waves. Any incomplete atomic write, stale digest, or mismatch between the persisted
projection and recomputed value stops dispatch.

## 8. Valid fixtures

The fixtures below show only graph-relevant fields. `spec_blocked_by` is `D(v)` from the Task Spec; `plan_blocked_by` is `L(v)`
in the current plan.

### Fixture V1: initial wave with one gated dependent

```yaml
tasks:
  schema:
    spec_blocked_by: []
    plan_blocked_by: []
    parallel_with: [docs]
    dispatch_wave: 1
    dispatch_status: PUBLISHED
  docs:
    spec_blocked_by: []
    plan_blocked_by: []
    parallel_with: [schema]
    dispatch_wave: 1
    dispatch_status: READY
  consumer:
    spec_blocked_by: [schema]
    plan_blocked_by: [schema]
    parallel_with: []
    dispatch_wave: 2
    dispatch_status: GATED
blocked_tasks: [consumer]
ready_wave: 1
```

`schema` and `docs` are incomparable, same-wave, and assumed to have disjoint ownership. `consumer` correctly waits for the
published-but-not-integrated `schema` task. The plan is ready at wave 1 because that wave still has an active `PUBLISHED` task.

### Fixture V2: resolved live blocker without changing the static graph

```yaml
tasks:
  schema:
    spec_blocked_by: []
    plan_blocked_by: []
    parallel_with: []
    dispatch_wave: 1
    dispatch_status: INTEGRATED
  consumer:
    spec_blocked_by: [schema]
    plan_blocked_by: []
    parallel_with: []
    dispatch_wave: 2
    dispatch_status: READY
blocked_tasks: []
ready_wave: 2
```

The `consumer` Task Spec and wave remain unchanged. Only the live plan blocker cleared after `schema` became `INTEGRATED`.

## 9. Invalid fixtures

| Fixture | Invalid combination | Required result |
| --- | --- | --- |
| I1 | `A.blocked_by = [A]` | Reject self-reference. |
| I2 | `B.blocked_by = [missing-task]` | Reject unknown dependency. |
| I3 | `A -> B` and `B -> A` | Reject dependency cycle. |
| I4 | `A -> B -> C`, with `C.blocked_by = [A, B]` | Reject redundant transitive direct edge `A`. |
| I5 | `A.parallel_with = [B]`, but `B.parallel_with = []` | Reject asymmetric parallel claim. |
| I6 | `A -> B` and `A.parallel_with` includes `B` | Reject direct dependency/parallel conflict. |
| I7 | `A -> B -> C` and `A.parallel_with` includes `C` | Reject transitive dependency/parallel conflict. |
| I8 | `A.parallel_with = [B]` but `W(A) != W(B)` | Reject same-wave claim with different derived waves. |
| I9 | `A -> B`, `dispatch_wave(A)=1`, `dispatch_wave(B)=1` | Reject wave equality where strict order is required. |
| I10 | `schema` is `PUBLISHED`; `consumer` has static dependency on it but plan `blocked_by=[]` and status `READY` | Reject omitted unresolved live blocker. |
| I11 | `schema` is `INTEGRATED`; `consumer` retains plan `blocked_by=[schema]` | Reject stale resolved live blocker. |
| I12 | A task is `PUBLISHED` with non-empty `blocked_by` | Reject status/live-blocker mismatch. |
| I13 | A task is `GATED` but its ID is absent from `blocked_tasks` | Reject incomplete blocked projection. |
| I14 | `blocked_tasks` contains an `INTEGRATED` task or an unknown ID | Reject terminal/unknown blocked projection. |
| I15 | `ready_wave=2` while a `READY` or `PUBLISHED` task exists at wave 1 | Reject incorrect ready frontier. |
| I16 | No `READY`/`PUBLISHED` tasks but `ready_wave=1` | Reject non-null frontier with empty ready set. |
| I17 | Plan `parallel_with` differs from the Task Spec projection | Reject cross-record graph mismatch. |
| I18 | Two named parallel tasks share an authoritative output or active worktree | Reject semantic parallel conflict. |
| I19 | A task depends on `CANCELLED`/`SUPERSEDED` work and is marked `READY` | Reject treating terminal failure/supersession as dependency success. |

## 10. Negative-test matrix

These are the minimum negative cases for an implementation or review harness. Each test must assert rejection and identify the
computed set/value in the diagnostic; accepting a malformed record is a contract failure.

| ID | Mutation | Invariant exercised | Expected diagnostic focus |
| --- | --- | --- | --- |
| N01 | Add an unknown ID to Task Spec `blocked_by` | Reference closure | task ID and unknown dependency |
| N02 | Add a duplicate or self ID to `blocked_by` | Canonical direct set | duplicate/self reference |
| N03 | Make a two-node cycle | Acyclicity | cycle path or participating IDs |
| N04 | Add a transitive ancestor as a second direct edge | Direct-only reduction | redundant ancestor |
| N05 | Remove one side of a parallel pair | Symmetry | both task IDs |
| N06 | Put a direct dependency pair in `parallel_with` | Direct conflict | dependency and parallel pair |
| N07 | Put an ancestor/descendant pair in `parallel_with` | Transitive conflict | reachability path |
| N08 | Keep a valid independent pair but alter one wave | Same-wave parallel claim | actual and derived waves |
| N09 | Lower a dependent task's persisted wave by one | Wave recurrence | actual and `1 + max(parent wave)` |
| N10 | Leave a non-integrated direct dependency out of plan `blocked_by` | Live blocker completeness | expected `U(v)` vs actual `L(v)` |
| N11 | Keep an integrated dependency in plan `blocked_by` | Live blocker freshness | stale blocker ID |
| N12 | Set `READY`, `PUBLISHED`, or `INTEGRATED` with live blockers | Status projection | status and non-empty `L(v)` |
| N13 | Set `GATED`/`BLOCKED` but omit its ID from `blocked_tasks` | Blocked projection completeness | expected blocked ID set |
| N14 | Add a terminal/unknown task to `blocked_tasks` | Blocked projection membership | invalid list member |
| N15 | Set `ready_wave` above the minimum active frontier | Ready projection | expected minimum wave |
| N16 | Set non-null `ready_wave` with no active ready frontier | Empty-frontier rule | expected `null` |
| N17 | Alter Task Spec `parallel_with` without the plan projection | Persisted graph identity | plan/spec mismatch |
| N18 | Mark overlapping authoritative paths as parallel | Ownership conflict | conflicting paths/owners |
| N19 | Make a dependent `READY` after its upstream is cancelled | Dependency satisfaction | unsatisfied terminal upstream |
| N20 | Delete a referenced Task Spec or change its digest | Persisted source integrity | path/digest mismatch |

## 11. Complexity

Let `n = |T|`, `m = sum_v |D(v)|`, and `p` be the number of undirected `parallel_with` claims.

- ID indexing, duplicate/reference checks, symmetry checks, status projections, `blocked_tasks`, and `ready_wave` are
  `O(n + m + p)` after the Task Specs are loaded.
- DFS cycle detection and topological wave derivation are `O(n + m)` with adjacency lists.
- A full ancestor/reachability closure using a BFS/DFS from every task is `O(n(n + m))` time and `O(n^2 + n + m)` space in
  the worst case. This supports both transitive-reduction checks and all parallel comparability checks.
- If only the `p` declared pairs need comparability checks, reachability search can instead be bounded by
  `O(p(n + m))` time, at the cost of repeating searches. Bitset closure reduces the practical constant to roughly
  `O(n(n + m) / word_size)` for dense reachability while retaining `O(n^2 / word_size)` closure storage.
- Canonical sorting adds `O(n log n + m log m + p log p)` in the straightforward implementation; it is not part of graph
  correctness, but is required for deterministic persisted projections and digests.

The linear pass is sufficient for references, statuses, waves, and plan projections. A validator that claims to enforce
transitive parallel conflicts or redundant direct-edge rejection must also account for the closure cost; it must not describe
those checks as `O(n + m + p)` without stating an incremental index or an equivalent precomputed reachability structure.
