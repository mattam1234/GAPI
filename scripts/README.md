# Scripts Directory Reference

This folder contains maintenance, migration, diagnostics, and utility scripts for GAPI.

## How to run scripts

From the repository root:

```bash
python scripts/<script_name>.py [args]
```

Some scripts are interactive and prompt for confirmation or passwords.

## Safety levels

- **Safe**: Read-only checks or local non-destructive utilities.
- **Caution**: Updates DB data/schema or local config files.
- **High Risk**: Bulk rewrites/migrations or one-off repair scripts that can change many records/files.

---

## Script index (all files in `/scripts`)

| Script | Purpose | Typical usage | Safety |
|---|---|---|---|
| `check_admin_role.py` | Checks whether a user has the `admin` role and prints role details. | `python scripts/check_admin_role.py <username>` | Safe |
| `check_cache.py` | Prints per-user cached game counts and a sample cache record. | `python scripts/check_cache.py` | Safe |
| `check_password.py` | Verifies whether a plaintext password matches a user’s stored hash. | `python scripts/check_password.py <username> <password>` | Safe |
| `check_postgres.py` | PostgreSQL health check: config detection, connection test, schema visibility, user count. | `python scripts/check_postgres.py` | Safe |
| `copy_games.py` | Copies `mattam` user cached games to `admin`. One-off data-copy helper. | `python scripts/copy_games.py` | High Risk |
| `create_postgres_user.py` | Creates PostgreSQL user/database based on `.env`, grants privileges, tests DB login. | `python scripts/create_postgres_user.py` | Caution |
| `demo.py` | Runs a self-contained interactive demo of picker/favorites/multi-user/stats/export flows. | `python scripts/demo.py` (or `--quiet`) | Safe |
| `fix_current_user.py` | Rewrites `gapi_gui.py` assignments from `current_user` to `get_current_username()`. | `python scripts/fix_current_user.py` | High Risk |
| `fix_locks.py` | Removes `with current_user_lock:` blocks from `gapi_gui.py` and dedents code. | `python scripts/fix_locks.py` | High Risk |
| `fix_locks_and_proxy.py` | Combined rewrite: removes `current_user_lock` blocks and updates `current_user` assignments. | `python scripts/fix_locks_and_proxy.py` | High Risk |
| `generate_discord_banner.py` | Generates `static/discord-bot-banner-680x240.png` via Pillow drawing primitives. | `python scripts/generate_discord_banner.py` | Safe |
| `initialize_db.py` | Initializes DB schema using app models (`init_db`) and prints discovered tables. | `python scripts/initialize_db.py` | Caution |
| `list_db.py` | Prints table list and selected row counts for quick DB inspection. | `python scripts/list_db.py` | Safe |
| `migrate_add_discord_id.py` | Adds `users.discord_id` column and index if missing. | `python scripts/migrate_add_discord_id.py` | Caution |
| `migrate_add_suspension.py` | Adds suspension-related columns to `users` if missing. | `python scripts/migrate_add_suspension.py` | Caution |
| `migrate_database.py` | Legacy migration helper that adds `users.password` column if missing. | `python scripts/migrate_database.py` | Caution |
| `migrate_discord_mappings_to_db.py` | Imports Discord user mappings from `discord_config.json` into DB `users.discord_id`. | `python scripts/migrate_discord_mappings_to_db.py` | Caution |
| `migrate_password_column.py` | Widens `users.password` column (e.g., `VARCHAR(64)` → `VARCHAR(255)`). | `python scripts/migrate_password_column.py` | Caution |
| `migrate_to_postgres.py` | Interactive SQLite→PostgreSQL migration with automatic SQLite backup. | `python scripts/migrate_to_postgres.py` | High Risk |
| `remove_locks.py` | Removes `with current_user_lock:` blocks from `gapi_gui.py` (alternative implementation). | `python scripts/remove_locks.py` | High Risk |
| `reset_password.py` | Resets a user password hash in DB, with optional non-interactive confirmation bypass. | `python scripts/reset_password.py <username> <new_password> [--yes]` | Caution |
| `setup_postgres.py` | Windows-focused automated PostgreSQL setup (user/db creation + `.env`/`config.json` updates). | `python scripts/setup_postgres.py` | High Risk |
| `verify_discord_db.py` | Validates DB Discord integration (`discord_id` column, linked users, indexes). | `python scripts/verify_discord_db.py` | Safe |
| `verify_discord_db_only.py` | Scans `discord_bot.py` for DB-vs-file mapping behavior and reports findings. | `python scripts/verify_discord_db_only.py` | Safe |
| `verify_game_response.py` | Calls running API endpoints and prints picked-game payload field completeness. | `python scripts/verify_game_response.py` | Safe |

---

## Detailed notes by category

### 1) Account and role operations

#### `reset_password.py`
- Resets a user’s password in the database using `database.hash_password`.
- Interactive by default; use `--yes` / `-y` for non-interactive environments.
- Fails if the user does not exist.

#### `check_password.py`
- Confirms whether a provided plaintext password matches stored credentials.
- Useful for debugging login/auth issues without changing data.

#### `check_admin_role.py`
- Prints role membership and whether the user currently has `admin`.
- Includes a printed one-liner you can run manually to grant admin.

### 2) Database setup and health

#### `initialize_db.py`
- Creates schema/tables via app database initialization logic.
- Safe to run multiple times (does not drop existing tables).

#### `check_postgres.py`
- Full health check for PostgreSQL-backed deployments.
- Verifies config sources (`.env`, `config.json`), engine creation, schema, and user count.

#### `create_postgres_user.py`
- Creates PostgreSQL user/database and grants privileges using `psql`.
- Reads connection and credential hints from `.env`.
- Prompts for PostgreSQL superuser password.

#### `setup_postgres.py` (Windows-oriented)
- Finds local `psql.exe`, creates `gapi` + `gapi_db`, updates `.env` and `config.json`, tests connection.
- Designed for local Windows setup workflows.
- Can modify local config files in-place.

### 3) Schema/data migration scripts

#### `migrate_database.py`
- Adds `password` column to `users` if absent (legacy helper).

#### `migrate_password_column.py`
- Widening migration for modern longer password hashes.
- Intended fix for truncation issues with newer hash formats.

#### `migrate_add_discord_id.py`
- Adds `discord_id` column + index to `users` if missing.

#### `migrate_add_suspension.py`
- Adds suspension metadata fields to `users`: status, reason, actor, timestamps.

#### `migrate_discord_mappings_to_db.py`
- Reads `discord_config.json` legacy mappings and pushes them into DB `users.discord_id`.
- Skips users that don’t exist in DB yet.

#### `migrate_to_postgres.py`
- Migrates data from local SQLite (`gapi.db`) to configured PostgreSQL backend.
- Creates timestamped SQLite backup before data copy.
- Interactive confirmation required before migration starts.

### 4) Verification and diagnostics

#### `verify_discord_db.py`
- Checks that Discord integration schema/data/index state is present in DB.

#### `verify_discord_db_only.py`
- Source-level verification that Discord bot user mapping behavior is DB-driven and not legacy JSON-driven.

#### `verify_game_response.py`
- API smoke-check helper that expects a server at `http://localhost:5000`.
- Registers/login test user and validates key fields in `/api/pick` response payload.

#### `check_cache.py`
- Quick DB cache visibility script for per-user `GameLibraryCache` counts.

#### `list_db.py`
- Prints table names and row counts for a fixed set of tables.

### 5) One-off code rewrite / maintenance scripts

> These scripts directly rewrite `gapi_gui.py`. Use only with version control and review.

#### `fix_current_user.py`
- Regex replacement for assignments based on `current_user`.

#### `fix_locks.py`
- Removes `with current_user_lock:` blocks and adjusts indentation.

#### `fix_locks_and_proxy.py`
- Combined lock-removal and current-user assignment rewrite pass.

#### `remove_locks.py`
- Alternative lock-removal implementation for `gapi_gui.py`.

### 6) Utility scripts

#### `generate_discord_banner.py`
- Pillow-based banner generator outputting `static/discord-bot-banner-680x240.png`.
- Requires `Pillow` and available fonts (falls back to default font when needed).

#### `demo.py`
- Runs a local, no-DB/no-Steam demo flow of core app concepts.
- Good for quick feature walkthroughs and CI demonstration output (`--quiet`).

#### `copy_games.py`
- Copies cached game rows from hardcoded source user (`mattam`) to target (`admin`).
- One-off helper with hardcoded usernames; review before any reuse.

---

## Recommended execution order for fresh PostgreSQL setup

1. `python scripts/setup_postgres.py` **or** `python scripts/create_postgres_user.py`
2. `python scripts/initialize_db.py`
3. `python scripts/check_postgres.py`
4. (Optional migration from SQLite) `python scripts/migrate_to_postgres.py`

---

## General precautions

- Always run scripts from the repository root unless a script explicitly says otherwise.
- Back up data before running any migration or bulk-update script.
- Review hardcoded-user scripts (`copy_games.py`) before execution.
- Commit or stash working tree changes before using file-rewrite scripts targeting `gapi_gui.py`.
