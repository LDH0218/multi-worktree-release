# Adaptive Operating Modes v2

Status: design-only proposal for a future protocol v2. This document does not change `SKILL.md`, the current JSON Schema,
the validator, or any persisted v1 record. The v1 protocol remains authoritative until a separately approved adoption task
defines a migration boundary.

## 1. Decision

Protocol v2 should make governance proportional to demonstrated risk. Every request starts in `FAST` and moves to a heavier
mode only when a concrete trigger requires it:

```text
FAST --isolation trigger--> ISOLATED --strict trigger--> STRICT
  \--------------------------strict trigger----------->/
```

The modes are execution policies, not quality levels. All three require a correct result, relevant tests, a reviewed diff,
and explicit authorization for external mutation. The difference is how much durable coordination and independent evidence
is necessary to obtain that confidence.

Mode selection must not depend on task titles, model choice, worktree numbering, or an agent's confidence claim. A repository
may add stricter local triggers, but it must not remove the default strict triggers defined here.

## 2. Goals and non-goals

The design has five goals:

1. Make low-risk work cheap enough that governance does not cost more than the change.
2. Preserve isolation, recovery, and authorization boundaries when concurrent work makes them necessary.
3. Reserve full historical state and release evidence for operations whose failure has material consequences.
4. Separate delivery coordination from release certification.
5. Give audits a severity model and a stopping rule so optional improvements do not expand the active release indefinitely.

This proposal does not define the final v2 JSON fields, migrate v1 history, split the validator, automate cleanup, or change
model routing. Those require later designs after the mode boundaries are accepted.

## 3. Mode selection

### 3.1 FAST is the default

Use `FAST` only while all of the following remain true:

- one bounded outcome can be completed in one current worktree without a concurrent Worker;
- no unresolved dependency graph or ownership overlap exists;
- the diff is atomic and can be reviewed as one unit;
- the change does not alter a persisted collaboration contract, authorization boundary, state machine, migration rule, or
  release-certification rule;
- no production mutation, destructive operation, paid or externally mutable execution, secret handling, or data migration is
  required;
- failure is locally reversible through an ordinary follow-up commit;
- repository instructions do not explicitly require isolation or strict certification.

Typical FAST work includes a focused bug fix, a small feature inside one ownership boundary, tests, ordinary documentation,
or repository metadata. A small line count does not override a risk trigger: a one-line authorization or migration change is
not FAST.

When the multi-worktree Skill is invoked for a request that remains FAST, the Skill should explicitly classify it and then
yield to the repository's ordinary single-task workflow. It should not manufacture a Dispatch Plan merely to prove that a
Dispatch Plan was unnecessary.

### 3.2 ISOLATED is for collaboration risk

Upgrade to `ISOLATED` when any of these conditions appears:

- a Worker needs a separate worktree or persistent conversation;
- two or more tasks may overlap in time;
- task ownership, dependencies, integration order, or frozen baselines matter;
- a contract, schema, validator, state transition, recovery rule, or generated projection changes without invoking a strict
  trigger;
- a handoff commit must remain independently reviewable;
- interrupted work must be recoverable without relying on conversation history.

ISOLATED preserves explicit assignment, frozen baseline, scoped authorization, Worker lock, handoff, and Master integration.
It does not automatically start release-candidate certification. Successful integration completes the delivery workflow
unless the user separately requests publication or repository policy requires a release gate.

### 3.3 STRICT is for consequence risk

Use `STRICT` immediately when any of these conditions is present:

- production publication, deployment, package release, public tag, or another externally visible release decision;
- destructive, irreversible, security-sensitive, credential-bearing, or data-migration activity;
- an external call or execution that can mutate remote state, create material cost, or resume an existing production run;
- authorization-envelope semantics or the mechanism enforcing authorization changes;
- recovery from ambiguous, inconsistent, partially persisted, or possibly tampered state;
- multiple repositories, hosts, release systems, or protected branches participate in one outcome;
- an explicit compliance, audit, provenance, or release-candidate evidence requirement applies;
- the user or repository explicitly requests STRICT.

STRICT uses the complete durable protocol and independently attributable release evidence. It may reuse valid ISOLATED
delivery records, but it cannot infer publication authority from them.

## 4. Required records by mode

The v2 record model should avoid copying the same state into every layer.

| Concern | FAST | ISOLATED | STRICT |
| --- | --- | --- | --- |
| Mode decision | one concise decision | persisted in delivery plan | persisted in release plan |
| Assignment | current request and repository scope | one authoritative Task Spec per Worker | same as ISOLATED |
| Dependency graph | none | only when more than one active assignment exists | required when release inputs have dependencies |
| Worker progress | ordinary task state | compact lock and progress projection | compact lock and progress projection |
| Integration mapping | commit history | Master records Worker SHA to integrated SHA | required and release-bound |
| Candidate evidence | none | none by default | required for the exact candidate identity |
| Publication authorization | exact user authorization at action time | exact user authorization at action time | persisted bounded grant plus action-time confirmation when policy requires it |
| Historical transition proof | none | only for recovery or disputed transitions | required for release-significant transitions |

Field authority should be singular:

- Task Spec owns immutable assignment content.
- Delivery Plan owns dependencies and Dispatch state.
- Worker record owns only the active worktree lock and progress.
- Integration record owns handoff acceptance and commit mapping.
- Release record owns candidate evidence and publication outcome.

Other records may reference an authority by ID, revision, and digest, but should not copy its full payload. A mismatch blocks
execution only when two records are expected to describe the same current fact.

FAST should not require a durable record by default. If it lasts beyond one conversation generation or performs an authorized
external mutation, write one compact operation receipt containing the objective, baseline, changed paths, checks, exact
authorization, result SHA or external reference, and outcome. That receipt replaces, rather than abbreviates, the four-card
protocol for FAST work.

## 5. Upgrade rules

An upgrade is mandatory as soon as a trigger is discovered. The agent stops the activity that crossed the boundary, preserves
the current tree and external state, and creates only the records newly required by the destination mode.

### FAST to ISOLATED

1. Stop before delegating or editing an overlapping ownership area.
2. Record the current HEAD, dirty paths, objective, completed checks, and preserved material.
3. Create the authoritative Task Spec and compact Worker lock from that checkpoint.
4. Continue in a separate worktree only after baseline and scope preflight pass.

### FAST or ISOLATED to STRICT

1. Stop before the first strict external or destructive action.
2. Revoke or preserve any earlier authorization without broadening it.
3. Freeze the candidate inputs and the protocol version used to interpret them.
4. Create release-specific evidence and obtain the exact publication authority.

Upgrade is prospective. It must not invent historical cards, executions, or evidence for work already completed under a valid
lighter mode. The upgrade checkpoint is the explicit boundary between the two policies.

## 6. Safe downgrade rules

Downgrade is a recovery and cost-control decision, never a way to bypass a failed gate.

`STRICT` may downgrade to `ISOLATED` only when no strict external or destructive action has started, all strict authority has
been revoked or expired, the candidate is explicitly abandoned, and the remaining outcome is delivery-only. Existing strict
evidence remains historical and cannot be relabelled as ISOLATED success.

`ISOLATED` may downgrade to `FAST` only after every Worker is integrated, cancelled, or returned to IDLE; no concurrent work,
dependency, dirty alternate worktree, or unresolved handoff remains; and the remaining task independently satisfies every
FAST condition. The downgrade starts a new FAST checkpoint rather than erasing the isolated history.

No downgrade is allowed:

- after a production, publication, destructive, or paid remote mutation has begun;
- while a release or Worker lock remains active;
- while a P0 or P1 finding is unresolved;
- after a gate failure when the purpose is to avoid rerunning or fixing that gate;
- when repository policy fixes a minimum mode.

If these conditions cannot be proved, remain in the current mode or cancel the outcome safely.

## 7. Delivery and release are separate workflows

Delivery answers: “Is the intended change correctly integrated?” Release answers: “May this exact integrated state be made
externally visible now?”

An ISOLATED delivery ends after Master accepts the handoff, records the integration mapping, and runs change-proportionate
tests. Candidate evidence is not created or invalidated during ordinary delivery unless a release has been requested.

A release starts from an immutable integrated commit and selects its own certification level. Any production publication is
STRICT even when the underlying delivery was FAST. The release workflow may consume delivery evidence, but it independently
binds tests, authorization, provenance, and publication outcome to the release commit.

This separation prevents every documentation or implementation commit from reopening an unrelated release-candidate state.

## 8. FAST publication path

FAST permits a short Git publication path only when publication itself does not trigger STRICT under repository policy. The
minimum sequence is:

```text
verify branch and clean baseline
-> inspect the complete diff
-> run the targeted and repository-required checks
-> create one atomic commit
-> obtain explicit authorization for the exact repository, branch, and commit
-> perform a non-force fast-forward push
-> verify the remote ref and report the SHA
```

Failure or uncertainty stops the path. A retry needs the same still-current authorization and must first determine whether the
remote mutation already occurred. Tags, releases, deployments, protected publication branches, force updates, and multi-ref
pushes are STRICT by default unless repository policy explicitly and safely narrows them.

## 9. Severity and stopping rules

Every review finding has one severity:

| Severity | Meaning | Current-release effect |
| --- | --- | --- |
| P0 | authorization breach, security issue, data loss, destructive ambiguity, or unverifiable production state | stop immediately; release blocked |
| P1 | demonstrated correctness, recovery, identity, integration, or release-evidence failure | affected work blocked until fixed or explicitly cancelled |
| P2 | maintainability, usability, performance, or resilience debt without a demonstrated current failure | record for the next planned scope; does not block release |
| P3 | optional improvement, polish, or speculative hardening | backlog only |

An audit defines its coverage areas before it starts. Each area receives one primary pass; additional passes examine only
changes made after that pass or evidence that invalidates it. Equivalent findings are deduplicated by violated invariant and
affected surface, not by wording.

The active release stops accepting new work when:

- all declared acceptance checks pass;
- no P0 or P1 finding remains open;
- every active Worker has a terminal delivery outcome;
- release authority is either unused or has one verified outcome;
- remaining P2 and P3 findings are recorded outside the active release scope.

A P2 or P3 issue enters the active release only through an explicit user scope decision. “It would be better” is not a release
blocker. A new P0 or P1 may reopen only its affected mode, task, or Gate.

## 10. Protocol freeze

Each ISOLATED or STRICT cycle binds one protocol identity before the first executable assignment:

```text
protocol_major + protocol_minor + schema identity + validator commit
```

That interpretation remains fixed for the cycle. Status writes and task revisions may evolve under the frozen protocol, but
the meaning of fields, transitions, authorization, and Gates may not. A protocol implementation change applies to a new cycle
or requires an explicit protocol-migration task that stops affected execution and preserves the old interpretation.

Compatibility readers may validate older records, but compatibility logic must not silently change the active cycle's
meaning. A patch to the Skill repository is not itself permission to reinterpret an already published assignment.

## 11. Governance cost control

Do not add a second detailed cost state machine. Use three operational limits:

- FAST permits one mode decision, one implementation pass, one review pass, and one validation batch before an exception must
  justify more ceremony.
- ISOLATED creates records only for active assignments and keeps release evidence off until requested.
- STRICT records only evidence that can change a release or recovery decision; optional diagnostics remain ordinary logs.

If setting up the chosen mode is likely to cost more than implementing and validating the task, re-evaluate the mode. Stay in
a heavier mode only when a concrete trigger prevents the cheaper one. Cost pressure never removes an authorization, safety,
or recovery trigger.

## 12. Adoption order and acceptance questions

Adopt this design in separate, frozen steps:

1. Approve the mode definitions, trigger matrix, severity model, and stopping rules.
2. Define the v2 authority map and minimal records without compatibility code.
3. Define v1 read-only compatibility and the protocol-freeze boundary.
4. Split delivery validation from release certification behind one stable CLI facade.
5. Pilot FAST on low-risk repository work, then ISOLATED delivery, then one STRICT publication.
6. Make v2 normative only after all three pilots meet their declared cost and safety outcomes.

Before implementation, resolve these policy questions:

- May a repository explicitly permit lightweight tag publication outside STRICT, or are all tags always STRICT?
- Is the FAST operation receipt required for every push or only when conversation recovery is needed?
- Which protected branches or release systems require action-time confirmation in addition to persisted authority?
- What repository-owned conditions may force ISOLATED for otherwise FAST contract changes?

Until those decisions are made, use the conservative defaults in this document: tags and release systems are STRICT, a FAST
push records a compact receipt, and any contract change is at least ISOLATED.
