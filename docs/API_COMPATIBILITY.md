# API Compatibility Policy

This policy defines how GAPI evolves `/api/*` endpoints while protecting existing clients.

## 1) Compatibility Goal

Default to **backward-compatible** API changes. Existing clients should continue working across minor/patch releases without urgent updates.

## 2) Versioning Strategy

- Current stable surface remains under `/api/*`.
- If incompatible behavior is required, introduce a versioned path (for example `/api/v2/*`) and keep the legacy path active through the deprecation window.
- Prefer additive evolution (new fields/params/endpoints) over destructive changes.

## 3) Change Classification

### Non-breaking
- Adding optional request fields
- Adding response fields (without removing/renaming existing fields)
- Adding new endpoints
- Adding alias parameters that preserve legacy behavior

### Breaking
- Removing or renaming endpoints, fields, or parameters
- Changing response shape/types in incompatible ways
- Tightening validation that rejects previously valid requests
- Semantic behavior changes that alter existing defaults

## 4) Deprecation Window

For breaking changes on active endpoints:
- Announce deprecation in `docs/CHANGELOG.md` and release notes.
- Keep deprecated behavior available for **at least two minor releases**.
- Provide migration guidance before removal.
- Track planned removal target version/date in changelog entries.

## 5) Documentation Requirements Per API Change

Every API-affecting change must include:
- OpenAPI spec updates (`openapi_spec.py`)
- Changelog entry with breaking/non-breaking classification
- Migration notes when client updates are required
- Tests for new/changed request and response behavior

## 6) Client-Safety Rules

- Avoid reusing existing fields for new semantics.
- Introduce new fields/flags for new behavior.
- Preserve existing defaults unless explicitly versioned.
- Keep legacy aliases for compatibility where feasible.

## 7) Release Gate

Do not ship API changes unless:
- compatibility classification is recorded,
- migration notes are present when needed,
- regression checks pass for core client paths.
