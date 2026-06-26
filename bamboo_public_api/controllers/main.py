# -*- coding: utf-8 -*-
"""Foundation routes: health probe + capability discovery."""
import odoo
from odoo import http
from odoo.http import request

from .common import API_ROOT, available_apps, ok


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
        return ok(data={
            'apps': available_apps(),
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
