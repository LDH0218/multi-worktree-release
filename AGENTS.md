# Repository workflow

This repository dogfoods [multi-worktree-release](SKILL.md). Read its entrypoint, then only the
procedure needed for the current task; fully read selected instructions before acting.

- The main worktree/task is Master, owning planning, dispatch, independent handoff review, integration,
  candidate gates and publication decisions.
- Choose delivery by actual risk and coordination needs. Bounded single-owner work may be done directly
  by Master, including locally verifiable Schema, persistence or validator fixes. Use Master/Worker
  delivery for concurrent responsibilities, permission-boundary changes, irreversible migration,
  formal release certification or complex recovery. Freeze strict assignments to full SHAs and retain
  Task Specs, grants, acceptance and handoff evidence.
- Keep live coordination under `.codex/multi-worktree-release/` local and ignored. Preserve user changes.
- New Master and Worker tasks/conversations default to `gpt-6.1-sol`. Keep the existing role effort/tier
  choices unless explicitly changed: Master `high/default`, Workers `max/priority`. Pass model and effort
  explicitly at creation or authorized follow-up; verify requested runtime settings before dispatch.
  Historical assignments retain their profiles/digests; apply the new default through normal versioned
  publication, not by rewriting old evidence. An unavailable tier control is not proof of acceleration.
- Workers cannot merge, rebase, reset, synchronize, push, publish or widen scope unless their current
  Task Spec explicitly authorizes that exact action. Production publication needs separate explicit authority.
- Use `<responsibility-role>-<conversation-generation>` titles, without project prefixes by default.
  Master owns all durable role bindings; completion retains the current conversation/worktree.
  Creation, rotation and archive follow [Conversation Rotation](references/conversation-rotation-sop.md).
  Verify new conversations' actual default cwd/Git identity before dispatch. Distinguish new-worktree
  creation from exact retained-directory reuse; missing listings never authorize duplicate creation.
- Use [Task Lifecycle](references/task-lifecycle-sop.md) for STRICT delivery,
  [Release](references/release-sop.md) for certification/closeout/rollover, and
  [Exception and Recovery](references/exception-recovery-sop.md) for mismatches. Never bypass recovery stops.
  Other governance routes are selected in the Skill entrypoint, not loaded for every edit.
- [Operator Execution Map](references/operator-execution-map.md) is the command/order lookup:
  validate before mutation, integrate before Candidate, separate publication authorization, closeout
  before rollover. It grants no synchronization, cleanup, deletion or external authority.

Repository rules replace reusable defaults only explicitly and while preserving their safety properties.
