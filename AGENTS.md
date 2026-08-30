# Repository workflow

This repository dogfoods the `multi-worktree-release` Skill.

- Use the main worktree and its Codex task as Master. Master owns planning, task publication, handoff review, integration, release-candidate gates, and publication decisions.
- Changes that affect contract schemas, state transitions, authorization, dispatch semantics, persistence, recovery, message identity, candidate evidence, or the validator require the Skill's Master/Worker workflow.
- Give each independent responsibility an isolated Codex task and Git worktree with a frozen full-SHA baseline, persisted Task Spec, default-deny authorization, explicit acceptance checks, and a structured handoff.
- Persist the normative Dispatch Plan under `.codex/multi-worktree-release/` in the Master worktree. Keep this live coordination state local and ignored by Git.
- Workers must not merge, rebase, reset, synchronize from Master, push, publish, or widen scope unless their current Task Spec explicitly authorizes that exact action.
- Master independently reviews and validates every handoff before integration. Production publication remains a separate explicit authorization.
- Trivial prose-only or repository-metadata edits may remain single-task when they do not alter executable governance or contract meaning.

Repository-owned instructions take precedence over reusable defaults only when they explicitly replace a rule and preserve its safety properties.
