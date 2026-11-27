"""Database version control (db/migrate.py): migrations apply in order, undo exactly, run all-or-nothing, and an
applied file that was edited is refused. Every real migration in db/migrations/ is applied to an empty database,
undone and applied again; the database must come back exactly as it was.

Needs a THROWAWAY Postgres: RIGVIDEO_TEST_PG = a URL whose login may create databases. CI provides one and these tests
may not be skipped there; on a laptop without it they are skipped. Never point it at a real database."""
import os
import pathlib
import secrets
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db"))
import migrate  # noqa: E402

PG = os.environ.get("RIGVIDEO_TEST_PG")


def write(folder, files):
    folder.mkdir(exist_ok=True)
    for name, sql in files.items():
        (folder / name).write_text(sql)
    return folder


# ------------------------------------------------------------------ file rules (no database needed)

def test_repo_migrations_are_well_formed():
    migrate.migrations()                                            # raises on a gap, a bad name or a missing undo


@pytest.mark.parametrize("files,why", [
    ({"0001_a.up.sql": "CREATE TABLE a ();"}, "missing or empty"),
    ({"0001_a.up.sql": "x", "0001_a.down.sql": "  "}, "missing or empty"),
    ({"0001_a.up.sql": "x", "0001_a.down.sql": "x", "0003_c.up.sql": "x", "0003_c.down.sql": "x"}, "expected 0002"),
    ({"1_a.up.sql": "x"}, "name it"),
    ({"0001_a.up.sql": "x", "0001_a.down.sql": "x", "0001_b.up.sql": "x", "0001_b.down.sql": "x"}, "two names"),
])
def test_bad_migration_folders_are_refused(tmp_path, files, why):
    with pytest.raises(migrate.Refused, match=why):
        migrate.migrations(write(tmp_path / "m", files))


# ------------------------------------------------------------------ against a throwaway Postgres

@pytest.fixture
def db():
    if not PG:
        if os.environ.get("CI"):
            pytest.fail("CI must provide RIGVIDEO_TEST_PG; the migration tests may not be skipped there")
        pytest.skip("no throwaway Postgres (RIGVIDEO_TEST_PG)")
    import psycopg
    name = "rv_mig_" + secrets.token_hex(4)
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    url = PG.rsplit("/", 1)[0] + "/" + name
    yield url
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"DROP DATABASE {name} WITH (FORCE)")


def tables(url):
    import psycopg
    with psycopg.connect(url) as c:
        return sorted(r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                                              "AND table_name <> 'rigvideo_migrations'"))


def schema(url):
    """Everything a migration can change: columns, indexes, views, constraints, grants (public schema)."""
    import psycopg
    q = ["SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
         "WHERE table_schema = 'public' AND table_name <> 'rigvideo_migrations' ORDER BY 1, 2",
         "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename <> 'rigvideo_migrations' ORDER BY 1",
         "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = 'public' ORDER BY 1",
         "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
         "AND conrelid <> 'rigvideo_migrations'::regclass ORDER BY 1",
         "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants WHERE table_schema = 'public' "
         "AND table_name <> 'rigvideo_migrations' ORDER BY 1, 2, 3"]
    with psycopg.connect(url) as c:
        c.execute(migrate.TABLE)
        c.commit()
        return [c.execute(x).fetchall() for x in q]


TWO = {"0001_people.up.sql": "CREATE TABLE people (id int PRIMARY KEY, name text);",
       "0001_people.down.sql": "DROP TABLE people;",
       "0002_places.up.sql": "CREATE TABLE places (id int PRIMARY KEY); ALTER TABLE people ADD COLUMN place int;",
       "0002_places.down.sql": "ALTER TABLE people DROP COLUMN place; DROP TABLE places;"}


def test_up_down_and_back(db, tmp_path):
    m = write(tmp_path / "m", TWO)
    assert migrate.run("up", db, folder=m, log=lambda *a: None) == [1, 2] and tables(db) == ["people", "places"]
    assert migrate.run("down", db, folder=m, log=lambda *a: None) == [1] and tables(db) == ["people"]
    assert migrate.run("up", db, folder=m, log=lambda *a: None) == [1, 2]
    assert migrate.run("down", db, to=0, folder=m, log=lambda *a: None) == [] and tables(db) == []
    assert migrate.run("up", db, to=1, folder=m, log=lambda *a: None) == [1]


def test_status_and_dry_run_change_nothing(db, tmp_path):
    m = write(tmp_path / "m", TWO)
    out = []
    migrate.run("up", db, dry=True, folder=m, log=out.append)
    assert "CREATE TABLE people" in "\n".join(out) and tables(db) == []
    migrate.run("status", db, folder=m, log=out.append)
    assert "0001_people: waiting" in out


def test_a_failing_migration_leaves_nothing_behind(db, tmp_path):
    m = write(tmp_path / "m", {"0001_bad.up.sql": "CREATE TABLE half (id int); SELECT no_such_function();",
                               "0001_bad.down.sql": "DROP TABLE half;"})
    import psycopg
    with pytest.raises(psycopg.Error):
        migrate.run("up", db, folder=m, log=lambda *a: None)
    assert tables(db) == [] and migrate.run("status", db, folder=m, log=lambda *a: None) == []


def test_an_edited_applied_migration_is_refused(db, tmp_path):
    m = write(tmp_path / "m", TWO)
    migrate.run("up", db, folder=m, log=lambda *a: None)
    (m / "0001_people.up.sql").write_text("CREATE TABLE people (id int PRIMARY KEY, name text, extra int);")
    for cmd in ("up", "down", "status"):
        with pytest.raises(migrate.Refused, match="edited after it was applied"):
            migrate.run(cmd, db, folder=m, log=lambda *a: None)


def test_deleted_files_of_an_applied_migration_are_refused(db, tmp_path):
    m = write(tmp_path / "m", TWO)
    migrate.run("up", db, folder=m, log=lambda *a: None)
    for f in ("0002_places.up.sql", "0002_places.down.sql"):
        (m / f).unlink()
    with pytest.raises(migrate.Refused, match="files are gone"):
        migrate.run("status", db, folder=m, log=lambda *a: None)


def test_every_repo_migration_undoes_exactly(db):
    """Each real migration, one by one: apply, undo, and the database is exactly as before; then apply again."""
    ms = migrate.migrations()
    for v, n, _, _ in ms:
        before = schema(db)
        migrate.run("up", db, to=v, log=lambda *a: None)
        after = schema(db)
        migrate.run("down", db, to=v - 1, log=lambda *a: None)
        assert schema(db) == before, f"{v:04d}_{n}.down.sql does not undo its change"
        migrate.run("up", db, to=v, log=lambda *a: None)
        assert schema(db) == after, f"{v:04d}_{n} does not apply the same way twice"
