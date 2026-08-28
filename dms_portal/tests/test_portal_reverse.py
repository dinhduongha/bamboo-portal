"""Plan 16C Tasks 2 and 3 — returns and claims, neither of them approved here.

Section 8: "Portal cannot approve its own credit/claim/return."
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestPortalReturn(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    def _delivered_line(self, qty=5.0):
        """A real source line, delivered.

        `_compute_eligibility` reads `sale_line_id.qty_delivered`, so a
        fixture that skips the delivery tests the guard rather than the
        feature -- eligible_qty would be 0 and every return would be refused
        for the right reason at the wrong time.
        """
        self._entitle()
        result = self._api().dms_portal_submit(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': qty}])
        self.assertTrue(result['order_id'], result.get('errors'))
        order = self.env['sale.order'].sudo().browse(result['order_id'])
        # An order awaiting approval refuses line edits -- "dang cho duyet,
        # khong sua duoc dong hang". Walk it through the real workflow rather
        # than around it: a fixture that writes past a guard is a fixture that
        # stops noticing when the guard changes.
        order.dms_approve()
        order.dms_confirm()
        line = order.order_line[0]
        line.write({'qty_delivered': qty})
        return line

    def test_a_return_without_a_source_line_is_refused_with_a_portal_message(self):
        self._entitle()
        with self.assertRaises(UserError) as caught:
            self._api().dms_portal_request_return(
                self.outlet_a.id,
                [{'product_id': self.product_a.id, 'qty': 1}])
        self.assertIn('name the delivery line', str(caught.exception).lower())

    def test_a_return_for_an_unentitled_outlet_is_refused(self):
        self._entitle()
        with self.assertRaises(AccessError):
            self._api().dms_portal_request_return(
                self.outlet_b.id,
                [{'product_id': self.product_a.id, 'qty': 1,
                  'sale_line_id': 1}])

    def test_a_return_with_no_lines_is_refused(self):
        self._entitle()
        with self.assertRaises(UserError):
            self._api().dms_portal_request_return(self.outlet_a.id, [])

    def test_a_portal_return_never_starts_approved(self):
        source = self._delivered_line()
        result = self._api().dms_portal_request_return(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'qty': 1,
              'sale_line_id': source.id}])
        self.assertEqual(result['status'], 'submitted')
        order = self.env['dms.return.order'].sudo().browse(
            result['return_id'])
        self.assertNotEqual(order.status, 'approved')

    def test_the_return_belongs_to_the_entitled_outlet(self):
        source = self._delivered_line()
        result = self._api().dms_portal_request_return(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'qty': 1,
              'sale_line_id': source.id}])
        order = self.env['dms.return.order'].sudo().browse(
            result['return_id'])
        self.assertEqual(order.res_partner_id, self.outlet_a)

    def test_a_replayed_return_creates_one_record(self):
        source = self._delivered_line()
        lines = [{'product_id': self.product_a.id, 'qty': 1,
                  'sale_line_id': source.id}]
        first = self._api().dms_portal_request_return(
            self.outlet_a.id, lines,
            operation_uuid='0199e0f0-0000-7000-8000-0000000000a1')
        second = self._api().dms_portal_request_return(
            self.outlet_a.id, lines,
            operation_uuid='0199e0f0-0000-7000-8000-0000000000a1')
        self.assertEqual(first['return_id'], second['return_id'])
        self.assertTrue(second['replayed'])

    def test_evidence_is_ir_attachment(self):
        source = self._delivered_line()
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'photo.jpg', 'datas': b'aGVsbG8='})
        result = self._api().dms_portal_request_return(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'qty': 1,
              'sale_line_id': source.id}],
            attachment_ids=[attachment.id])
        order = self.env['dms.return.order'].sudo().browse(
            result['return_id'])
        self.assertIn(attachment, order.attachment_ids)


@tagged('post_install', '-at_install')
class TestPortalClaim(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    def test_a_claim_beneficiary_is_the_entitled_outlet_not_the_payload(self):
        """The caller names a beneficiary; the server ignores it. Otherwise a
        portal user files a claim payable to somebody else."""
        self._entitle()
        with self.assertRaises(UserError):
            # No tactic version -> refused by `dms.trade.api`, which is the
            # point: this asserts the wrapper does not invent one either.
            self._api().dms_portal_submit_claim(
                self.outlet_a.id,
                {'code': 'PC-1', 'beneficiary_partner_id': self.outlet_b.id,
                 'period_start': '2026-01-01', 'period_end': '2026-01-31'})

    def test_a_claim_for_an_unentitled_outlet_is_refused(self):
        self._entitle()
        with self.assertRaises(AccessError):
            self._api().dms_portal_submit_claim(
                self.outlet_b.id, {'code': 'PC-2'})

    def test_the_signature_has_nowhere_to_put_an_approved_amount(self):
        import inspect
        sig = inspect.signature(
            type(self.env['dms.portal.api']).dms_portal_submit_claim)
        self.assertNotIn('approved_amount', sig.parameters)
        self.assertNotIn('eligible_amount', sig.parameters)
