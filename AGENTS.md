# Repository workflow

This repository dogfoods [multi-worktree-release](SKILL.md). Read its entrypoint, then only the
procedure needed for the current task; fully read selected instructions before acting.

- The main worktree/task is Master, owning planning, dispatch, independent handoff review, integration,
  candidate gates and publication decisions.
- Schema, state, authorization, dispatch, persistence, recovery, message identity, candidate or validator
  changes require Master/Worker delivery. Isolate independent responsibilities with frozen full SHAs,
  persisted Task Specs, default-deny grants, acceptance checks and structured handoffs. Trivial prose or
  metadata may remain single-task only when executable governance and contract meaning do not change.
- Keep live coordination under `.codex/multi-worktree-release/` local and ignored. Preserve user changes.
- Workers cannot merge, rebase, reset, synchronize, push, publish or widen scope unless their current
  Task Spec explicitly authorizes that exact action. Production publication needs separate explicit authority.
- Use `<responsibility-role>-<conversation-generation>` titles, without project prefixes by default.
  Master owns all durable role bindings; completion retains the current conversation/worktree.
  Creation, rotation and archive follow [Conversation Rotation](references/conversation-rotation-sop.md).
- Use [Task Lifecycle](references/task-lifecycle-sop.md) for STRICT delivery,
  [Release](references/release-sop.md) for certification/closeout/rollover, and
  [Exception and Recovery](references/exception-recovery-sop.md) for mismatches. Never bypass recovery stops.
  Other governance routes are selected in the Skill entrypoint, not loaded for every edit.
- [Operator Execution Map](references/operator-execution-map.md) is the command/order lookup:
  validate before mutation, integrate before Candidate, separate publication authorization, closeout
  before rollover. It grants no synchronization, cleanup, deletion or external authority.

Repository rules replace reusable defaults only explicitly and while preserving their safety properties.
