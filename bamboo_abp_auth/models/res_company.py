from odoo import fields, models
from odoo.tools.sql import column_exists, create_column

from ..utils import uuid7


class ResCompany(models.Model):
    _inherit = 'res.company'

    tenant_uuid = fields.Char(
        string='Tenant UUID', copy=False, index=True,
        default=lambda self: str(uuid7()),
        help='External tenant identifier. Matched against the ABP JWT "tenantid" '
             'claim to resolve the company on SSO login.',
    )

    _sql_constraints = [
        ('tenant_uuid_uniq', 'unique(tenant_uuid)', 'Tenant UUID must be unique.'),
    ]

    def _auto_init(self):
        """Backfill the column ourselves, one uuid per row.

        Odoo evaluates a field's `default` **once** when it adds the column and
        UPDATEs every existing row with that single value — so on any database
        with more than one company the unique constraint below could never be
        created ("unable to add constraint 'res_company_tenant_uuid_uniq'").
        Creating and filling the column here, before `super()` reaches
        `_add_sql_constraints`, gives each row its own key. Rows created later go
        through `create()`, where the default is evaluated per record.
        """
        if not column_exists(self.env.cr, self._table, 'tenant_uuid'):
            create_column(self.env.cr, self._table, 'tenant_uuid', 'varchar')
        self.env.cr.execute("SELECT 1 FROM pg_proc WHERE proname = 'uuidv7' LIMIT 1")
        # uuidv7() needs PostgreSQL 18; gen_random_uuid() (v4) is the fallback.
        # Both are volatile, so the UPDATE draws a fresh value per row.
        generator = 'uuidv7()' if self.env.cr.fetchone() else 'gen_random_uuid()'
        self.env.cr.execute(
            "UPDATE %s SET tenant_uuid = %s::text WHERE tenant_uuid IS NULL"
            % (self._table, generator)
        )
        return super()._auto_init()
