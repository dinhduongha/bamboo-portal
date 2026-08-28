"""Plan 16D, B16-09 — the debt sub-plan 08 named, closed.

    `dms.eb2b.order` still creates `sale.order` by its own path. It sets no
    `dms_flow_type` and never calls `dms_quote`, so that path has no credit
    check and no assortment check.
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestEb2bBridge(PortalCatalogCase):

    def _staged(self, product=None, qty=1, source='EB2B-1'):
        return self.env['dms.eb2b.order'].sudo().create({
            'res_partner_id': self.outlet_a.id,
            'company_id': self.parent.id,
            'channel': 'web',
            'order_source_id': source,
            'order_content': {'lines': [{
                'product_id': (product or self.product_a).id, 'qty': qty}]},
        })

    def test_conversion_now_produces_a_dsr_order(self):
        staged = self._staged()
        staged.action_convert_to_sale()
        order = staged.converted_to_sale_order_id
        self.assertTrue(order)
        self.assertEqual(order.dms_flow_type, 'dsr')
        self.assertEqual(order.dms_team_id, self.team)
        self.assertEqual(order.dms_distributor_company_id, self.dist)

    def test_a_sku_outside_the_assortment_is_now_refused(self):
        """The old path created the order regardless. `product_b` is in no
        assortment, so this used to become a `sale.order` nobody could
        deliver."""
        staged = self._staged(product=self.product_b, source='EB2B-2')
        with self.assertRaises(UserError):
            staged.action_convert_to_sale()
        self.assertFalse(staged.converted_to_sale_order_id)
        self.assertEqual(staged.order_status, 'pending')

    def test_an_order_over_the_credit_limit_is_now_refused(self):
        self.env['dms.outlet.credit'].sudo().search([
            ('res_partner_id', '=', self.outlet_a.id)]).write(
                {'credit_limit': 0.0})
        self.outlet_a.invalidate_recordset()
        staged = self._staged(source='EB2B-3')
        with self.assertRaises(UserError):
            staged.action_convert_to_sale()
        self.assertFalse(staged.converted_to_sale_order_id)

    def test_the_quantity_survives_the_key_rename(self):
        """The staging payload says `qty`; `dms_quote` reads `quantity`.
        Getting this wrong prices every line at the default of 1 and nothing
        raises."""
        staged = self._staged(qty=7, source='EB2B-4')
        staged.action_convert_to_sale()
        line = staged.converted_to_sale_order_id.order_line[0]
        self.assertEqual(line.product_uom_qty, 7)

    def test_the_method_kept_its_name(self):
        """Plan 06 section 11 forbids a big-bang cutover while clients still
        call the old action; 10B kept `action_submit` alive for the same
        reason. Only the route underneath changed."""
        self.assertTrue(
            hasattr(self.env['dms.eb2b.order'], 'action_convert_to_sale'))

    def test_converting_twice_is_refused(self):
        staged = self._staged(source='EB2B-5')
        staged.action_convert_to_sale()
        with self.assertRaises(UserError):
            staged.action_convert_to_sale()
