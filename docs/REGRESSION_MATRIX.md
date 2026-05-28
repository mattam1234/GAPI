# Regression Matrix (Release Gate)

This matrix defines high-value checks that must pass before release cuts.

## Execution Baseline

- Test command: `python -m pytest tests/ -v --tb=short`
- Run targeted tests for changed areas first, then full-suite validation.

## Critical Paths

| Area | Why It Is Critical | Minimum Regression Checks |
|---|---|---|
| Authentication | Entry point for all protected APIs and UI tabs | Register/login/logout flow, session-protected routes, role-protected admin routes |
| Library Sync | Core data freshness and downstream feature health | Sync endpoint behavior, cache refresh behavior, post-sync side effects (including achievement queueing) |
| Backlog / Lists | Heavy user interaction and shared-list collaboration | List creation/update/delete, notes/status persistence, favorites integration, owner-vs-member actions |
| Schedule | Shared planning workflows and event coordination | Create/update/delete schedule, invite/member behavior, common-game filtering, Discord-event related safety checks |
| Chat | Multi-user coordination and real-time UX expectations | Room list rendering, create/join/send message flows, sidebar behavior, live update stream reliability |

## Release Checklist

- [ ] All changed-area targeted tests pass
- [ ] Full test suite passes (or known unrelated failures are documented)
- [ ] No new failures in critical-path tests above
- [ ] API contract changes documented and classified
- [ ] Migration notes added where needed
