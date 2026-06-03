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

- [x] All changed-area targeted tests pass
- [x] Full test suite passes (or known unrelated failures are documented)
- [x] No new failures in critical-path tests above
- [x] API contract changes documented and classified (N/A: no API contract changes in this cycle)
- [x] Migration notes added where needed (N/A: no migration-impacting changes in this cycle)

## Current Gate Snapshot (2026-06-03)

- Targeted critical-path suite passed:
  - `tests/test_security_hardening.py`
  - `tests/test_library_achievement_autosync.py`
  - `tests/test_backlog_collections.py`
  - `tests/test_achievement_schedule.py`
  - `tests/test_chat_room_commands.py`
  - `tests/test_dashboard_chat_layout.py`
- Full-suite validation passed: `1565 passed` via `python -m pytest`.
