"""Talk to PostgreSQL through psql: deploy a script, read back what was created.

psql is the one tool every PostgreSQL install has, so there's no driver to install.
The connection is anything psql's -d accepts: a database name, "host=... port=...
dbname=...", or a postgresql:// URL. Passwords come from the usual places (~/.pgpass,
PGPASSWORD); this module never prints the connection string.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from .model import Column, ForeignKey, Table

TIMEOUT_S = 120

CATALOG_QUERY = r"""
SELECT coalesce(json_agg(t ORDER BY t.name), '[]'::json)
FROM (
  SELECT c.relname AS name,
         obj_description(c.oid, 'pg_class') AS comment,
         (SELECT json_agg(json_build_object(
                    'name', a.attname,
                    'type', format_type(a.atttypid, a.atttypmod),
                    'not_null', a.attnotnull,
                    'identity', a.attidentity <> '') ORDER BY a.attnum)
            FROM pg_attribute a
           WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS columns,
         (SELECT json_agg(a.attname ORDER BY k.ord)
            FROM pg_constraint p
            CROSS JOIN LATERAL unnest(p.conkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
           WHERE p.conrelid = c.oid AND p.contype = 'p') AS primary_key,
         (SELECT json_agg(a.attname)
            FROM pg_constraint u
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = u.conkey[1]
           WHERE u.conrelid = c.oid AND u.contype = 'u'
             AND cardinality(u.conkey) = 1) AS unique_columns,
         (SELECT json_agg(json_build_object(
                    'column', a.attname,
                    'references', r.relname,
                    'on_delete', CASE f.confdeltype WHEN 'c' THEN 'cascade'
                                                    WHEN 'n' THEN 'set null'
                                                    WHEN 'r' THEN 'restrict'
                                                    WHEN 'd' THEN 'set default'
                                                    ELSE 'no action' END)
                  ORDER BY a.attnum)
            FROM pg_constraint f
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = f.conkey[1]
            JOIN pg_class r ON r.oid = f.confrelid
           WHERE f.conrelid = c.oid AND f.contype = 'f'
             AND cardinality(f.conkey) = 1) AS foreign_keys
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = :'schema' AND c.relkind = 'r'
) AS t;
"""


class DatabaseError(RuntimeError):
    pass


def psql(db: str, sql: str, *variables: str) -> str:
    """Run SQL through psql and return its output; raise with psql's error message.

    -X skips ~/.psqlrc (it could change the output format), ON_ERROR_STOP makes the
    first error stop the script with a non-zero exit code.
    """
    exe = shutil.which("psql")
    if exe is None:
        raise DatabaseError("psql isn't on PATH: install the PostgreSQL client tools")
    cmd = [exe, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-d", db]
    for var in variables:
        cmd += ["-v", var]
    try:
        run = subprocess.run(cmd, input=sql, capture_output=True, text=True,
                             timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise DatabaseError(f"psql didn't finish within {TIMEOUT_S} s") from None
    if run.returncode != 0:
        raise DatabaseError(run.stderr.strip() or f"psql exited with {run.returncode}")
    return run.stdout


def schema_exists(db: str, schema: str) -> bool:
    out = psql(db, "SELECT count(*) FROM pg_namespace WHERE nspname = :'schema';",
               f"schema={schema}")
    return out.strip() == "1"


def deploy(db: str, script: str) -> None:
    """Run the generated script. It holds its own BEGIN/COMMIT: all or nothing."""
    psql(db, script)


def introspect(db: str, schema: str) -> list[Table]:
    """The tables in `schema`, read from the catalog into the same model build() makes."""
    found = json.loads(psql(db, CATALOG_QUERY, f"schema={schema}") or "[]")
    tables = []
    for t in found:
        unique = set(t["unique_columns"] or [])
        cols = [Column(c["name"], c["type"], not_null=c["not_null"], unique=c["name"] in unique,
                       identity=c["identity"]) for c in t["columns"] or []]
        fks = [ForeignKey(f["column"], f["references"], f["on_delete"])
               for f in t["foreign_keys"] or []]
        tables.append(Table(t["name"], cols, t["primary_key"] or [], fks, t["comment"]))
    return tables
