"""Immutable DDL for legacy migrations which used live ORM definitions.

These checked-in snapshots replace runtime app.models imports. New model fields
must be introduced by a new migration, never by regenerating this baseline.
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op


def create_table(revision: str, table: str, *, checkfirst: bool = False) -> None:
    schema = json.loads(Path(__file__).with_name("legacy_tables.json").read_text(encoding="utf-8"))
    statements = schema[revision][table]
    if checkfirst and sa.inspect(op.get_bind()).has_table(table):
        return
    for statement in statements:
        op.execute(sa.text(statement))


def drop_table(table: str, *, checkfirst: bool = False) -> None:
    if checkfirst and not sa.inspect(op.get_bind()).has_table(table):
        return
    op.drop_table(table)
