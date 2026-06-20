# Branching Strategy

This project uses **GitHub Flow**: a single long-lived branch (`main`) that is always
deployable, with short-lived feature branches merged via pull request.

```
main ─────●──────●──────●────▶   (always deployable, protected)
           \    /  \    /
  feat/x    ●──●    |            branch → commit → PR → merge → delete
  fix/y             ●──●
```

## Rules

1. **`main` is protected and always deployable.** No direct pushes in the normal flow —
   every change lands through a pull request.
2. **Branch off `main`** for any work. Keep branches short-lived (hours to a few days).
3. **Open a PR early.** Merging requires:
   - a pull request (self-merge is allowed — no second reviewer required),
   - linear history (squash or rebase merge — no merge commits),
   - all PR conversations resolved.
4. **Delete the branch after merge** (locally and on the remote).

## Branch naming

Use a `type/short-description` slug in kebab-case:

| Prefix      | Use for                                  | Example                        |
| ----------- | ---------------------------------------- | ------------------------------ |
| `feat/`     | New feature or capability                | `feat/discord-rsvp-reminders`  |
| `fix/`      | Bug fix                                  | `fix/schedule-timezone-offset` |
| `refactor/` | Restructure without behavior change      | `refactor/extract-pick-domain` |
| `docs/`     | Documentation only                       | `docs/api-auth-guide`          |
| `chore/`    | Tooling, deps, config, housekeeping      | `chore/bump-fastapi-0-118`     |
| `test/`     | Adding or fixing tests only              | `test/backend-voting-coverage` |

## Commit messages

Follow Conventional Commits — `type(scope): summary` — matching the existing history:

```
feat(backend): migrate reputation routes to FastAPI
fix(schedule): correct RSVP validation for past events
```

## Typical workflow

```bash
git switch main
git pull                              # get latest
git switch -c feat/my-thing           # branch off main

# ... commit work ...

git push -u origin feat/my-thing      # publish
gh pr create --fill                   # open PR

# ... after CI/checks and self-review ...

gh pr merge --squash --delete-branch  # merge + clean up
git switch main && git pull           # resync local main
```

## Hotfixes

A hotfix is just a normal `fix/` branch off `main`, fast-tracked through a PR. There is no
separate release or hotfix branch — `main` is the release.

## Protection settings on `main`

The following are enforced via GitHub branch protection:

- Pull request required before merging (0 required approvals — solo self-merge allowed)
- Linear history required (no merge commits)
- Force pushes blocked
- Branch deletion blocked
- Conversation resolution required before merge
- Stale approvals dismissed on new commits

> Admin bypass is currently **enabled**, so the repo owner retains an escape hatch for
> emergencies. To make protection strict for everyone, enable "Include administrators"
> in the branch protection settings.
