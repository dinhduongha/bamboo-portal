from odoo import fields, models
from odoo.exceptions import AccessDenied


class ResUsers(models.Model):
    _inherit = 'res.users'

    sso_sub = fields.Char(
        string='SSO Subject (sub)', readonly=True,
        help='Unique subject identifier from SSO provider JWT',
    )
    tenant_id = fields.Char(
        string='ABP Tenant ID', readonly=True,
        help='Raw tenantid claim value from ABP JWT',
    )

    def _check_credentials(self, credential, env):
        """Support 'abp_token' credential type for web SSO login."""
        try:
            return super()._check_credentials(credential, env)
        except AccessDenied:
            if credential.get('type') == 'abp_token':
                abp_sub = credential.get('abp_sub')
                if abp_sub and self.sso_sub == abp_sub:
                    return {'uid': self.id, 'auth_method': 'abp_sso', 'mfa': 'default'}
            raise
