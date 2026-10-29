# Novera — Git Flow, Codex and documentation protocol

Status: proposed · 2026-10-29

## Change lifecycle
Issue (NV-###) → branch → small commits → test/lint locally → draft PR → CI → review and product acceptance → merge to develop → controlled release to main.

For early Sprint 0, PRs can target main until develop is established; keep one change per PR.

## Branch examples
- `docs/NV-001-codex-engineering`
- `feature/NV-005-brapi-adapter`
- `fix/NV-007-missing-dividends`
- `perf/NV-009-query-planning`
- `experiment/NV-023-anomaly-detection`

## Standard commit messages
`feat(module): ✨ short description`
`fix(module): 🐛 short description`
`docs(architecture): 📚 document decision`
`test(domain): ✅ add edge cases`
`ci(github): configure checks`
`perf(storage): ⚡ reduce query time`

Emojis are optional. Keep Conventional Commits parser-friendly. Avoid unstandardized raw/remove/cleanup types where a standard type explains the change.

## PR checklist
- [ ] GitHub issue linked
- [ ] Clear scope and affected files
- [ ] Acceptance criteria addressed
- [ ] Local validation: commands plus real outputs
- [ ] CI status attached
- [ ] Financial data sources, dates, assumptions documented (if applicable)
- [ ] Secrets/permissions reviewed
- [ ] Notion documentation updated or handoff provided
- [ ] No live performance claims without verified data and methods

## Source of truth
GitHub = code, commits, CI, PRs. Notion = product specs, ADRs, roadmap, Kanban.
A Notion card must never be marked completed just because an AI agent says it finished: link an actual merged PR and evidence first. Note date and commit SHA when recording completion.

## Decision records
Use `docs/adr/ADR-XXXX-short-title.md` with Context, Decision, Alternatives, Consequences, Status, Date, Evidence and Rollback.

## First milestones
1. NV-001 minimal structure and documented setup.
2. NV-004 data contract; NV-002 extraction of reference code.
3. NV-003 tests offline.
4. NV-012 automated PR checks.

## References
- https://www.conventionalcommits.org/pt-br/v1.0.0/
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets
- https://docs.astral.sh/uv/guides/projects/
- https://docs.pytest.org/
- https://scikit-learn.org/stable/common_pitfalls.html
