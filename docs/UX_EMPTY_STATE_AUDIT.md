# UX Audit — Empty States & Loading Indicators

Scope: the "Empty States and Loading States" and "Naming and Labels" sections of
[UX_CONSISTENCY_CHECKLIST.md](UX_CONSISTENCY_CHECKLIST.md), audited against
`static/main.js` and `static/style.css`.

## Summary

| Checklist item | Status |
|---|---|
| Every data view has an explicit empty-state message | ✅ **Met** — ~37 empty states across the data views (library, favorites, backlog, lists, playlists, leaderboard, chat, schedule, notifications, plugins, VODs, friends, …). |
| Empty states explain the next action | ⚠️ **Mostly** — most read "No X yet. <do Y>"; a handful are terminal ("No notifications yet.") with no next step. |
| Loading indicators consistent in wording and visual style | ❌ **Not met** — empty states are spread across 4 CSS classes + 19 ad-hoc inline-styled divs, and 15 empty states reuse the `loading` class. |

Coverage is good; **consistency is the gap.** No code-behavior bug — this is
presentation drift accumulated as features shipped.

## Findings

### F1 — `class="loading"` reused for terminal empty states (15 sites)
Empty states are wrapped in the **loading** class, which is semantically a
spinner/in-progress indicator. Examples:

- `static/main.js:1887` — `'<div class="loading">No favorite games yet!</div>'`
- `static/main.js:2388` — `'…No users yet. Register using the login page!'`
- `static/main.js:4950` — `'…No playlists yet. Create one from the actions panel.'`
- `static/main.js:5847` / `:5853` — backlog "No list selected" / "No list entries"

These are not loading states; they are final empty states.

### F2 — four different empty-state classes
`loading` (×31, mixed loading + empty), `schedule-agenda-copy` (×13),
`dash-empty` (×6), `backlog-list-widget-empty` (×5). Each renders differently
outside list containers.

### F3 — 19 ad-hoc inline-styled empty divs
e.g. `style="color:var(--text-secondary);padding:20px;">No ignored games yet."`
— padding, font-size, and color vary per call site (`main.js` 6804, 7373, 7491,
7657, 7904, 9444, 9520, 9614, …).

## Recommended standard

Adopt a single **`.empty-state`** class for all terminal empty states (distinct
from `.loading`). `style.css:3995` already renders `.loading` and `.dash-empty`
identically inside `.list-container`, so `.dash-empty` is the natural base to
generalize from (dashed card + 🎮 affordance).

```
.empty-state {            /* terminal "nothing here yet" */
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:8px; min-height:140px; padding:22px; text-align:center;
  border-radius:var(--radius-lg); border:1px dashed rgba(255,255,255,0.08);
  color:var(--text-muted);
}
```

Keep `.loading` exclusively for in-progress states.

## Migration plan (risk-tiered)

- **Tier A — pixel-safe now:** the F1 sites whose target is a `.list-container`
  child. CSS already renders `.loading` == `.dash-empty` there, so swapping the
  class is visually identical and semantically correct.
- **Tier B — needs a visual pass:** the 19 inline-styled divs (F3) and empty
  states outside list containers, where `.loading`'s plain centered styling
  differs from the card styling. These should be migrated with a browser check.

**Recommendation:** apply Tier A behind a regression test (assert the migrated
data views no longer emit `class="loading"` for empty text), and schedule Tier B
as a reviewed UI pass with screenshots — per the checklist's "confirm
docs/screenshots updated when UI behavior materially changes" gate.

### Applied so far (Tier A)

Introduced the semantic `.empty-state` class (`style.css`, rendered identically
to `.loading`/`.dash-empty` inside `.list-container`) and migrated the empty
states whose target element is a confirmed `.list-container` child — provably
pixel-identical, no visual change:

- `users-list` — "No users yet…" (`main.js` `loadUsers`)
- `backlog-list` — "No list selected yet…" / "No list entries yet…"

Pinned by `tests/test_ux_empty_states.py`. Note `favorites-list` is **not** a
`.list-container`, so it stays in Tier B (its `.loading` renders as plain
centered text, not the card — migrating it would change visuals).

Remaining Tier A candidates (other `.list-container` children still using
`.loading` for empty text) and all Tier B sites are follow-up work.
