# -*- coding: utf-8 -*-
"""A `uuid` column that Odoo's ORM treats as a string."""

from odoo import fields


class Uuid(fields.Char):
    """A `fields.Char` stored in a native PostgreSQL ``uuid`` column.

    Odoo has no uuid field type. Storing one as ``varchar`` would work, but a
    real ``uuid`` column is what makes the UNIQUE index this addon relies on
    both small (16 bytes, not 36) and canonical: Postgres normalises case and
    hyphenation, so ``A1B2...`` and ``a1b2...`` cannot both be inserted. A
    varchar index would happily hold both and the dedup would silently fail for
    a client that formatted its uuid differently.

    Everything else is inherited. psycopg hands ``uuid`` values back as ``str``
    unless ``register_uuid()`` has been called, which Odoo does not do, so the
    ORM sees the same Python type it would for a Char.
    """

    type = 'char'

    @property
    def _column_type(self):
        return ('uuid', 'uuid')

    def update_db_column(self, model, column):
        # Char's own override converts varchar columns to a different length;
        # it does not understand this one. Fall back to the generic behaviour,
        # which creates the column when missing and leaves a matching one alone.
        return fields.Field.update_db_column(self, model, column)

    def convert_to_column(self, value, record, values=None, validate=True):
        # An empty string is not a uuid, and Postgres will say so. Null is the
        # honest representation of "this record has no client key".
        value = super().convert_to_column(value, record, values, validate)
        return value or None
