# -*- coding: utf-8 -*-
"""Foundation routes: health probe + capability discovery."""
import odoo
from odoo import http
from odoo.http import request

from .common import (
    API_ROOT,
    FASTAPI_PUBLIC_ROOT,
    available_apps,
    fastapi_mode_active,
    ok,
)


class BambooPublicMain(http.Controller):

    @http.route(API_ROOT + '/health', type='http', auth='public', methods=['GET'], csrf=False)
    def health(self, **kw):
        return ok(data={
            'status': 'ok',
            'service': 'bamboo_public_api',
            'odoo_version': odoo.release.version,
            'db': request.db,
        })

    @http.route(API_ROOT + '/meta', type='http', auth='public', methods=['GET'], csrf=False)
    def meta(self, **kw):
        """Which apps the React client should show — driven by installed modules."""
        company = request.env.company
        fastapi_on = fastapi_mode_active()
        return ok(data={
            'apps': available_apps(),
            # Which implementation is authoritative + the base path to call. The
            # React client uses `api_root` so the toggle needs no frontend redeploy.
            'api_mode': 'fastapi' if fastapi_on else 'controller',
            'api_root': FASTAPI_PUBLIC_ROOT if fastapi_on else API_ROOT,
            'company': {
                'name': company.name,
                'currency': company.currency_id.name,
                'country': company.country_id.code if company.country_id else None,
            },
            'languages': [
                {'code': l.code, 'name': l.name}
                for l in request.env['res.lang'].sudo().search([('active', '=', True)])
            ],
        })
