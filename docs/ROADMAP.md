# 🗺️ GAPI Roadmap

This roadmap now separates shipped capabilities from the next iteration so priorities stay clear.

## ✅ Recently Delivered (v2.7.0 → v3.0.0)

### Platform and Product Surface
- Service/repository architecture migration for core domain areas
- OpenAPI + Swagger endpoints (`/api/openapi.json`, `/api/docs`)
- Expanded multi-platform support and integration work
- Dashboard-first single-page UI with integrated leaderboard and chat layout updates

### Collaboration and Social
- Voting enhancements, schedule improvements, and shared-list workflows
- Discord bot and Discord linking improvements
- Multi-user picker enhancements and friend-scoped user selection

### Reliability and Operations
- Larger automated test coverage and CI workflow hardening
- Systemd units for deployment and controlled auto-restart
- Background sync improvements (library and achievement sync flows)

## 🎯 Next Iteration Priorities

1. **Documentation governance refresh**
   - Keep roadmap focused on active priorities instead of completed history
   - Keep architecture and API policy docs aligned with code changes

2. **API compatibility discipline**
   - Apply a defined deprecation window
   - Ensure extensions/mobile clients have transition-safe aliases and migration notes

3. **Focused regression confidence**
   - Run a stable regression matrix for: auth, sync, backlog/lists, schedule, and chat
   - Gate releases on those critical-path checks

4. **Release hygiene standardization**
   - Enforce consistent changelog categories
   - Require migration notes for behavior/schema/API changes
   - Require explicit breaking vs non-breaking classification

5. **UX consistency pass**
   - Align naming, empty-state messaging, and modal behavior across newer tabs/features
   - Reduce visual/interaction drift as new features ship

## 📦 Supporting Docs for This Iteration

- [Architecture Map](ARCHITECTURE_MAP.md)
- [API Compatibility Policy](API_COMPATIBILITY.md)
- [Regression Matrix](REGRESSION_MATRIX.md)
- [UX Consistency Checklist](UX_CONSISTENCY_CHECKLIST.md)
- [Changelog](CHANGELOG.md)
- [Contributing Guide](CONTRIBUTING.md)

## 📝 Notes

- Priority order may change based on production issues and community feedback.
- Security and correctness fixes remain higher priority than feature additions.
