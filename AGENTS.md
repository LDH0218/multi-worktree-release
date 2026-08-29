# AI Project Guide

This repository packages one reusable Codex Skill.

- `SKILL.md` is the operational entrypoint and routing authority.
- `references/methodology.md` owns the compact reusable contracts and state models.
- `references/templates.md` owns copyable messages and task-card examples.
- `docs/multi-conversation-worktree-release-method.md` is the long-form Chinese methodology.
- `agents/openai.yaml` owns user-facing Skill metadata.

Keep overlapping identity, state, authorization, handoff, integration, and rotation semantics aligned across these files.
Do not add repository-specific product rules to the reusable Skill. Preserve progressive disclosure: shared decisions belong in
`SKILL.md`; detailed contracts and templates belong in their references.

After changes, run the Skill Creator `quick_validate.py` validator, parse `agents/openai.yaml`, check links and referenced files,
and inspect the complete diff. Validation never grants external-call, runtime, publication, or destructive authorization.
