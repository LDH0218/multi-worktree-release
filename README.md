# Multi-Worktree Release

A reusable Codex Skill and methodology for coordinating persistent tasks across multiple Git worktrees without confusing
conversation context, code identity, runtime identity, or authorization.

It covers:

- Master/Worker responsibility boundaries;
- durable task state cards and idempotent cross-task messages;
- immutable Worker handoffs and Master integration mappings;
- integrated-tree regeneration and release-candidate gates;
- conversation rotation, cancellation, supersession, and recovery;
- default-deny external calls, executions, publication, and destructive actions.

## Install in Codex

Ask Codex to install the skill from:

```text
https://github.com/LDH0218/multi-worktree-release
```

Then invoke it explicitly when desired:

```text
$multi-worktree-release audit this repository's multi-task and multi-worktree delivery model.
```

Automatic discovery remains enabled, so Codex may also select it for clearly matching governance work.

## Repository layout

```text
SKILL.md                                      Skill entrypoint and routing
agents/openai.yaml                            Codex UI metadata
references/methodology.md                     Operational contracts and state models
references/templates.md                       Copyable task, handoff, integration, and rotation templates
docs/multi-conversation-worktree-release-method.md
                                              Full Chinese methodology document
```

The root is directly installable as a Skill. The entrypoint uses progressive disclosure: it loads detailed methodology or
templates only when the active request needs them.

## Safety boundary

The Skill does not grant permission to create worktrees, change branches, call external services, create executions/jobs,
publish, delete data, or perform other destructive actions. Those actions still require repository-compatible, current,
explicit authorization.

## Validation

Validate the root skill with Codex's `skill-creator/scripts/quick_validate.py` validator. Also verify that
`agents/openai.yaml` parses, referenced files exist, and no scaffold placeholders remain.
