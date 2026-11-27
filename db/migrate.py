"""Version control for database changes. Every change to a database's structure is a numbered pair of files in
db/migrations/: NNNN_what.up.sql (apply) and NNNN_what.down.sql (undo). This tool applies them in order and can undo
them, so a change that breaks something is rolled back to the previous version. See db/README.md.

  python db/migrate.py status            what is applied, what is waiting
  python db/migrate.py up [--to N]       apply every waiting migration (or up to version N)
  python db/migrate.py down [--to N]     undo the newest migration (or every one above version N)
  add --dry-run to print the SQL without running it

The database is the URL in MIGRATE_DB_URL (a login allowed to change the schema; never the read-only one).
Each migration runs in one transaction: it applies completely or not at all. A table rigvideo_migrations in the
database records what is applied and each file's checksum; an applied file that was edited afterwards is refused
(write a new migration instead)."""
import argparse
import hashlib
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")
TABLE = """CREATE TABLE IF NOT EXISTS rigvideo_migrations (version int PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now(), applied_by text NOT NULL DEFAULT current_user)"""
LOCK = 727274                                                       # one migration run at a time (advisory lock key)


class Refused(RuntimeError):
    pass


def migrations(folder=HERE / "migrations"):
    """[(version, name, up_sql, down_sql)] in order. Refuses gaps, duplicates and a missing or empty undo."""
    found = {}
    for f in sorted(pathlib.Path(folder).glob("*.sql")):
        m = NAME.match(f.name)
        if not m:
            raise Refused(f"{f.name}: name it NNNN_what.up.sql / NNNN_what.down.sql")
        v, name, kind = int(m.group(1)), m.group(2), m.group(3)
        found.setdefault(v, {"name": name})
        if found[v]["name"] != name:
            raise Refused(f"version {v} is used by two names")
        found[v][kind] = f.read_text()
    out = []
    for i, v in enumerate(sorted(found), 1):
        x = found[v]
        if v != i:
            raise Refused(f"versions must run 1, 2, 3...: expected {i:04d}, found {v:04d}")
        for kind in ("up", "down"):
            if not (x.get(kind) or "").strip():
                raise Refused(f"{v:04d}_{x['name']}.{kind}.sql is missing or empty: every change needs its undo")
        out.append((v, x["name"], x["up"], x["down"]))
    return out


def checksum(sql):
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


def applied(con):
    con.execute(TABLE)
    return {r[0]: (r[1], r[2]) for r in con.execute("SELECT version, name, checksum FROM rigvideo_migrations ORDER BY version")}


def check(ms, done):
    have = {v: (n, checksum(u)) for v, n, u, _ in ms}
    for v, (n, c) in done.items():
        if v not in have:
            raise Refused(f"the database has {v:04d}_{n} applied but its files are gone")
        if have[v][1] != c:
            raise Refused(f"{v:04d}_{n}.up.sql was edited after it was applied: undo it first, or add a new migration")


def run(cmd, url, to=None, dry=False, folder=HERE / "migrations", log=print):
    import psycopg
    ms = migrations(folder)
    with psycopg.connect(url, autocommit=True) as con:
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            done = applied(con)
        check(ms, done)
        if cmd == "status":
            for v, n, _, _ in ms:
                log(f"{v:04d}_{n}: {'applied' if v in done else 'waiting'}")
            return sorted(done)
        if cmd == "up":
            todo = [m for m in ms if m[0] not in done and (to is None or m[0] <= to)]
        else:
            top = sorted(done, reverse=True)
            todo = [m for m in reversed(ms) if m[0] in done and (m[0] > to if to is not None else m[0] == (top[0] if top else -1))]
        for v, n, up, down in todo:
            sql = up if cmd == "up" else down
            log(f"{'apply' if cmd == 'up' else 'undo'} {v:04d}_{n}")
            if dry:
                log(sql)
                continue
            with con.transaction():                                 # all of it or none of it
                con.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
                con.execute(sql)
                if cmd == "up":
                    con.execute("INSERT INTO rigvideo_migrations (version, name, checksum) VALUES (%s, %s, %s)", (v, n, checksum(up)))
                else:
                    con.execute("DELETE FROM rigvideo_migrations WHERE version = %s", (v,))
        return sorted(applied(con))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["status", "up", "down"])
    ap.add_argument("--to", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    url = os.environ.get("MIGRATE_DB_URL")
    if not url:
        sys.exit("Set MIGRATE_DB_URL to the database to change (a login allowed to change its schema).")
    try:
        run(a.cmd, url, a.to, a.dry_run)
    except Refused as e:
        sys.exit(f"refused: {e}")


if __name__ == "__main__":
    main()
