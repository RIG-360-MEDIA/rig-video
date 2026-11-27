# Database changes: versioned migrations

Every change to a database's structure (a new table or column, an index, a view, a role's grants) goes through a
**migration**: a numbered pair of files in `db/migrations/`.

| File | Holds |
|---|---|
| `NNNN_what.up.sql` | the change |
| `NNNN_what.down.sql` | how to undo it exactly |

Versions run 1, 2, 3... with no gaps. A migration without a working undo is refused.

**Why:** if a change breaks something, `down` puts the database back to the previous version.

## Using it

```bash
export MIGRATE_DB_URL=postgresql://<login allowed to change the schema>@<host>/<db>
python db/migrate.py status              # what is applied, what is waiting
python db/migrate.py up --dry-run        # print the SQL first
python db/migrate.py up                  # apply what is waiting
python db/migrate.py down                # undo the newest one
python db/migrate.py down --to 3         # go back to version 3
```

How it behaves:
- Each migration runs in **one transaction**, so it is applied completely or not at all.
- The database records what is applied in a table `rigvideo_migrations` (version, name, checksum, when, by whom).
- An applied migration file that is **edited afterwards is refused**. Never change an applied migration: undo it, or
  add a new one.
- Only one run at a time (an advisory lock).

## Rules

- **Never change a database by hand.** Every change is a migration in a pull request, so it is reviewed, tested and
  recorded in git.
- **The RIG news database (RIG Hetzner box) belongs to its owner.** Run migrations there only with the owner's go.
  RIG-Video's normal login there is read-only and cannot migrate.
- **Every migration is tested before it merges.** CI applies every migration to an empty test Postgres, undoes it and
  applies it again (`tests/test_migrations.py`). A migration whose undo does not restore the database fails the PR.
- **Write the undo for the structure, and think about the data.** Dropping a column in `down` loses what was written
  to it. If a change also moves or deletes data, say so in the PR and take a backup first.
