from odoo import fields, models


class ResGroups(models.Model):
    _inherit = 'res.groups'

    role_code = fields.Char(
        string='SSO Role Code', index=True, copy=False,
        help='ABP JWT role name mapped to this group. On SSO login, any group '
             'whose role_code matches a JWT "role" claim is granted to the user.',
    )
