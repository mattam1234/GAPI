# UX Consistency Checklist

Use this checklist when shipping UI updates across tabs/features.

## Naming and Labels

- [ ] Tab names, card titles, and button labels use consistent terminology
- [ ] Similar actions use the same verbs (Create/Add, Remove/Delete, Save/Update)
- [ ] Cross-feature entities (list, schedule, room, session) are named consistently

## Empty States and Loading States

- [ ] Every data view has an explicit empty-state message
- [ ] Empty states explain next action clearly (what to click/do next)
- [ ] Loading indicators are consistent in wording and visual style

## Modal and Dialog Behavior

- [ ] Open/close behavior is consistent (button, backdrop, Esc if supported)
- [ ] Primary/secondary actions are positioned consistently
- [ ] Validation errors are shown in predictable locations and tone

## Feedback and Error Messaging

- [ ] Success messages are concise and action-specific
- [ ] Error messages explain what failed and what user can do next
- [ ] Permission/auth errors are clearly distinguished from validation errors

## Accessibility and Interaction Quality

- [ ] Focus order is usable in keyboard navigation paths
- [ ] Action controls include visible hover/focus states
- [ ] Color and icon usage does not carry meaning alone

## Final UX Review Gate

- [ ] Spot-check new/changed flows in dashboard, lists, schedule, and chat tabs
- [ ] Confirm no duplicated controls or stale labels remain after refactors
- [ ] Confirm docs/screenshots are updated when UI behavior materially changes
