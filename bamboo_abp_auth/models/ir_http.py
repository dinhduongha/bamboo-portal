import logging

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _authenticate(cls, endpoint):
        """Authenticate a Bearer token **that this AuthServer issued**.

        Anything else — no token, an HS256 token from bamboo_token_auth, a JWT
        from another issuer, an opaque string — goes straight to `super()`, which
        is what makes this module coexist with the other Bearer handlers on the
        same server instead of racing them for the header.
        """
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header[:7].lower() == 'bearer ':
            token = auth_header[7:].strip()
            if token and cls._token_is_ours(token):
                try:
                    cls._authenticate_bearer(token)
                    return
                except Exception as exc:
                    # Our token, but not usable: expired, bad signature, no role
                    # claim. Fail open to the session path rather than 401 — a
                    # stale Bearer must not break a valid session cookie.
                    _logger.warning(
                        'bamboo_abp_auth: Bearer authentication failed: %s', exc)

        return super()._authenticate(endpoint)

    @classmethod
    def _token_is_ours(cls, token):
        """Is this token worth validating — i.e. did our AuthServer issue it?

        Decided from the JOSE header and the unverified `iss` claim. That is
        routing, not authentication: nothing is granted on the strength of these
        values, and `AbpOidc.validate_token` still verifies signature, audience,
        expiry and issuer immediately afterwards. Reading them here only avoids
        paying for a JWKS fetch and an RS256 verification on every request that
        was never ours to begin with.
        """
        from odoo.addons.bamboo_abp_auth.controllers.auth import AbpOidc

        try:
            import jwt
        except ImportError:
            return False
        try:
            alg = jwt.get_unverified_header(token).get('alg')
            iss = jwt.decode(token, options={'verify_signature': False}).get('iss')
        except Exception:
            return False  # not a JWT at all (opaque/reference token, garbage)

        if alg == 'HS256':
            # One we minted at /api/v1/auth/callback. bamboo_token_auth's are
            # HS256 too but carry no `iss`, so they are never claimed here.
            return iss == AbpOidc.SELF_ISSUER
        if alg == 'RS256':
            return AbpOidc.is_configured() and AbpOidc.issued_here(iss)
        return False

    @classmethod
    def _authenticate_bearer(cls, token):
        """Validate Bearer token and set session for API requests (direct uid set)."""
        user, _claims = cls._validate_and_provision(token)
        request.session.uid = user.id
        request.session.login = user.login
        request.update_env(user=user.id)

    @classmethod
    def _validate_and_provision(cls, token):
        """Validate JWT and find-or-create the Odoo user. Returns (user, claims).

        Config-only: OIDC params come from odoo.conf (`openid_*`) via AbpOidc; the
        tenant is resolved by matching the JWT `tenantid` claim to a company's
        `tenant_uuid`. Does NOT touch request.session — callers set up the session.
        """
        from odoo.addons.bamboo_abp_auth.controllers.auth import AbpOidc

        env = request.env(user=1)  # SUPERUSER for lookup / provisioning

        if cls._is_self_issued(token):
            return cls._user_from_self_token(env, token), {}

        claims = AbpOidc.validate_token(token)

        sub = claims.get('sub')
        if not sub:
            raise Exception('JWT missing required "sub" claim.')

        tenant_id = claims.get('tenantid')
        ou_ids = claims.get('ouid', [])
        if isinstance(ou_ids, str):
            ou_ids = [ou_ids]
        roles = claims.get('role', [])
        if isinstance(roles, str):
            roles = [roles]
        if not roles:
            raise Exception('JWT has no role claims. Access denied.')
        email = claims.get('email', '')
        full_name = claims.get('name', email or sub)

        # Resolve company from tenantid via res.company.tenant_uuid
        company = env.company
        if tenant_id:
            match = env['res.company'].sudo().search([
                ('tenant_uuid', '=', tenant_id),
            ], limit=1)
            if match:
                company = match
            else:
                _logger.warning(
                    'bamboo_abp_auth: tenantid=%s has no company with a matching '
                    'tenant_uuid; falling back to %s', tenant_id, company.name,
                )

        # Optional LaoID identity: when the ABP JWT carries a `laoid` claim it is
        # the LaoID `sub`. If laoid_auth is installed, reconcile to the SAME
        # res.users it provisions (matched on its provider_key) so a user who
        # signs in via either path is one record. Guarded by field presence so
        # bamboo_abp_auth keeps zero hard dependency on laoid_auth.
        Users = env['res.users']
        has_laoid = 'provider_key' in Users._fields
        laoid_sub = claims.get('laoid')

        # Find or auto-provision user
        is_new_user = False
        user = Users.search([('sso_sub', '=', sub)], limit=1)
        if not user and has_laoid and laoid_sub:
            user = Users.search([('provider_key', '=', laoid_sub)], limit=1)
        if not user:
            is_new_user = True
            create_vals = {
                'name': full_name,
                'login': email or sub,
                'email': email,
                'sso_sub': sub,
                'tenant_id': tenant_id,
                'company_id': company.id,
                'company_ids': [(4, company.id)],
            }
            if has_laoid and laoid_sub:
                create_vals.update({'provider': 'laoid', 'provider_key': laoid_sub})
                if 'laoid_sub' in Users._fields:
                    create_vals['laoid_sub'] = laoid_sub
            # allow_create_user: laoid_auth blocks manual user creation otherwise.
            user = Users.sudo().with_context(allow_create_user=True).create(create_vals)
            _logger.info('bamboo_abp_auth: Auto-provisioned user %s (sub=%s)', user.login, sub)
        else:
            updates = {}
            if user.sso_sub != sub:
                updates['sso_sub'] = sub
            if user.company_id.id != company.id:
                updates['company_id'] = company.id
                updates['company_ids'] = [(4, company.id)]
            if tenant_id and user.tenant_id != tenant_id:
                updates['tenant_id'] = tenant_id
            if has_laoid and laoid_sub and not user.provider_key:
                updates.update({'provider': 'laoid', 'provider_key': laoid_sub})
            if updates:
                user.sudo().write(updates)

        # Only sync groups and organizations on initial provisioning, so
        # administrators can adjust them afterwards without being reset.
        if is_new_user:
            cls._sync_user_groups(env, user, roles)
            cls._sync_user_organizations(env, user, ou_ids, company)

        return user, claims

    @classmethod
    def _is_self_issued(cls, token):
        """Cheap unverified check: does this token claim to be one of ours?"""
        from odoo.addons.bamboo_abp_auth.controllers.auth import AbpOidc

        try:
            import jwt

            claims = jwt.decode(token, options={'verify_signature': False})
        except Exception:
            return False
        return claims.get('iss') == AbpOidc.SELF_ISSUER

    @classmethod
    def _user_from_self_token(cls, env, token):
        """Verify one of our own tokens and return the user it names.

        No provisioning here: the SSO round-trip that minted this token already
        did that, and re-running it would need `role` claims our token does not
        carry. This is the cheap path — an HMAC verification and one read, no
        JWKS fetch, no IdP round-trip.
        """
        from odoo.addons.bamboo_abp_auth.controllers.auth import AbpOidc

        claims = AbpOidc.validate_self_token(token, env)
        uid = claims.get('uid')
        if not uid:
            raise Exception('Token has no "uid" claim.')
        user = env['res.users'].sudo().browse(int(uid)).exists()
        # `active` matters: archiving a user is how an administrator revokes
        # access, and a token minted before that must stop working.
        if not user or not user.active:
            raise Exception('Token names user %s, which no longer exists.' % uid)
        return user

    @classmethod
    def _sync_user_groups(cls, env, user, roles):
        """Assign groups whose `role_code` matches an ABP role claim."""
        if not roles:
            return
        groups = env['res.groups'].sudo().search([('role_code', 'in', roles)])
        if groups:
            user.sudo().write({'groups_id': [(6, 0, groups.ids)]})

    @classmethod
    def _sync_user_organizations(cls, env, user, ou_ids, company):
        """Link res.organization records to the user from the JWT `ouid` claims.

        Each ouid is an OrganizationId (uuid), matched/created on
        res.organization.abp_ou_id. Guarded by field/model presence so bamboo_abp_auth
        stays standalone — this no-ops unless erp_base_extends is installed
        (it provides both res.organization and res.users.organization_ids).
        """
        if not ou_ids:
            return
        if 'res.organization' not in env or 'organization_ids' not in env['res.users']._fields:
            return
        org_ids = []
        for ou_id in ou_ids:
            org = env['res.organization'].get_or_create_by_abp_ou_id(
                ou_id, name=ou_id, company=company,
            )
            if org:
                org_ids.append(org.id)
        if org_ids:
            user.sudo().write({'organization_ids': [(6, 0, org_ids)]})
