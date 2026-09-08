# Codex SDD Migration Plan

## Objective

Migrate the repository-scoped Codex SDD skills and worker configuration from
`../../ai-parrot` into Navigator, while preserving Navigator's existing SDD
workflow and project context.

## Scope

- Add every source `.agents/skills/sdd-*/SKILL.md`.
- Add `.codex/agents/sdd-worker.toml`.
- Update `AGENTS.md` with the repository knowledge-graph instruction used by
  the migrated SDD tooling.
- Replace the stale AI-Parrot-specific `.agent/CONTEXT.md` with Navigator
  architecture and SDD conventions.
- Do not migrate Claude-only files, Antigravity agent definitions, or source
  repository implementation examples.

## Risks and Mitigations

- The source skills assume per-spec task indexes. Navigator's scripts support
  that layout, so the skills are retained; the legacy monolithic index remains
  untouched.
- Source context names AI-Parrot components. It will be replaced with verified
  Navigator paths and commands.
- Existing untracked user files under `etc/` will not be modified.

## Validation

- Check every migrated skill's frontmatter and source references.
- Parse `.codex/agents/sdd-worker.toml` with Python `tomllib`.
- Confirm all referenced local SDD scripts, templates, and documentation exist.
- Review the final diff and working-tree status.
