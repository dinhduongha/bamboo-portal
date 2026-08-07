# -*- coding: utf-8 -*-
"""The invariant that keeps `-u bamboo_idempotency` from destroying the keys.

A test cannot run `odoo -u` against itself, so it checks the property that
makes the update safe instead: every `field_<model>__bamboo_uuid` xmlid must be
`noupdate`. `ir.model.data._process_end` skips exactly those, and it is what
deleted 321 of 408 columns — and every key stored in them — the one time this
was not true.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSchemaSurvivesUpdate(TransactionCase):

    def test_field_xmlids_are_noupdate(self):
        self.env.cr.execute(r"""
            SELECT module, name FROM ir_model_data
             WHERE model = 'ir.model.fields'
               AND name LIKE 'field\_%\_\_bamboo\_uuid'
               AND COALESCE(noupdate, false) = false
             ORDER BY module, name
        """)
        unprotected = self.env.cr.fetchall()
        self.assertFalse(
            unprotected,
            "These bamboo_uuid field xmlids are not noupdate, so the next "
            "`-u` of the module that owns them drops the column and every key "
            "in it: %s" % (unprotected,),
        )

    def test_every_storable_model_has_the_column(self):
        """A gap here means an earlier update already ate part of the schema."""
        missing = []
        for name, model in self.env.registry.items():
            if model._abstract or model._transient or not model._auto:
                continue
            if 'bamboo_uuid' not in self.env[name]._fields:
                continue
            self.env.cr.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = 'bamboo_uuid'",
                (model._table,),
            )
            if not self.env.cr.fetchone():
                missing.append(name)
        self.assertFalse(
            missing,
            "Models whose table lost bamboo_uuid — reinstall the module, a "
            "plain `-u` does not put them back: %s" % (missing,),
        )
