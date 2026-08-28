from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request


class DmsPortal(http.Controller):
    """Rendering only.

    `website=True` is not optional here even though the `website` module is
    not a dependency: `http_routing` sets `request.is_frontend` from it, and
    without that flag `ir.qweb` skips `_prepare_frontend_environment`, so
    `portal.portal_layout` renders without `frontend_languages` and dies with
    `TypeError: object of type 'NoneType' has no len()` inside
    `portal.language_selector`. The 500 says nothing about the cause.

    Every write goes through a method on `dms.portal.api`. A controller that
    carries logic is a write path `/json/2` never travels, so the mobile
    client and the browser would stop agreeing about what an order is
    (CLAUDE.md section 6).
    """

    def _outlets(self):
        ids = request.env.user.dms_allowed_partner_ids()
        return request.env['res.partner'].sudo().browse(ids)

    @http.route('/my/dms', type='http', auth='user', website=True)
    def dms_home(self, **kw):
        return request.render('dms_portal.portal_home', {
            'outlets': self._outlets(),
        })

    @http.route('/my/dms/catalog', type='http', auth='user', website=True)
    def dms_catalog(self, outlet_id=None, **kw):
        try:
            rows = request.env['dms.portal.api'].dms_portal_catalog(
                outlet_id=outlet_id and int(outlet_id) or None)
        except AccessError:
            # 404, not 403. A 403 confirms the outlet exists; section 8 says
            # "no IDOR by numeric ID", and an id that answers differently for
            # a real outlet than for an invented one IS an oracle.
            return request.not_found()
        return request.render('dms_portal.portal_catalog', {
            'rows': rows,
            'outlets': self._outlets(),
            'outlet_id': outlet_id and int(outlet_id) or None,
        })

    @http.route('/my/dms/orders', type='http', auth='user', website=True)
    def dms_orders(self, **kw):
        orders = request.env['sale.order'].sudo().search([
            ('partner_id', 'in', self._outlets().ids),
            ('dms_flow_type', '=', 'dsr'),
        ], order='id desc', limit=80)
        return request.render('dms_portal.portal_orders', {'orders': orders})

    @http.route('/my/dms/order/<int:order_id>', type='http', auth='user',
                website=True)
    def dms_order(self, order_id, **kw):
        order = request.env['sale.order'].sudo().browse(order_id).exists()
        if not order or order.partner_id.id not in self._outlets().ids:
            return request.not_found()
        return request.render('dms_portal.portal_order', {'order': order})
