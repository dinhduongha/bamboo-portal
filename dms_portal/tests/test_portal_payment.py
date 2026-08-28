"""Plan 16C Tasks 4 and 5 — paying, without inventing a second ledger.

Section 8: "Payment callback signature; order idempotency." Section 11:
"payment callback dedup". Plan 09 section 5.1: scanning a QR is not
settlement.
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .test_portal_documents import TestPortalDocuments


class PortalPaymentCase(TestPortalDocuments):
    """Reuses the accounting fixture: a journal and two accounts, which is
    the smallest thing that lets a real invoice post in a fresh company."""

    def setUp(self):
        super().setUp()
        self.env.company.write({
            'dms_vietqr_bank_bin': '970418',
            'dms_vietqr_account_number': '0011000123456',
            'dms_vietqr_account_name': 'PT DIST',
        })
        self.dist.write({
            'dms_vietqr_bank_bin': '970418',
            'dms_vietqr_account_number': '0011000123456',
            'dms_vietqr_account_name': 'PT DIST',
        })


@tagged('post_install', '-at_install')
class TestPortalPaymentOffline(PortalPaymentCase):

    def _order(self):
        self._entitle()
        result = self._api().dms_portal_submit(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 1}])
        self.assertTrue(result['order_id'], result.get('errors'))
        return self.env['sale.order'].sudo().browse(result['order_id'])

    def test_qr_for_another_partners_order_is_refused(self):
        self._entitle()
        stray = self.env['sale.order'].sudo().create({
            'partner_id': self.outlet_b.id})
        with self.assertRaises(AccessError):
            self._api().dms_portal_payment_qr(stray.id)

    def test_scanning_is_not_settlement(self):
        """The screen showing a QR is exactly where somebody assumes the
        money arrived. Sub-plan 09 left this debt named: a "paid" flag the
        seller presses is a receivable deleted with a button — and on the
        portal the presser is the debtor."""
        order = self._order()
        result = self._api().dms_portal_payment_qr(order.id)
        self.assertFalse(result['settled'])
        self.assertIn('bank confirmation', result['note'])

    def test_the_portal_cannot_mark_an_invoice_paid(self):
        self._entitle()
        invoice = self._invoice(amount=500.0)
        self.assertNotEqual(invoice.payment_state, 'paid')
        with self.assertRaises(AccessError):
            invoice.with_user(self.buyer).write({'payment_state': 'paid'})

    def test_the_qr_payload_is_produced_by_dms_not_rebuilt_here(self):
        order = self._order()
        through_portal = self._api().dms_portal_payment_qr(order.id)['payload']
        direct = order.dms_vietqr_payload()
        self.assertEqual(through_portal, direct)


@tagged('post_install', '-at_install')
class TestPortalPaymentOnline(PortalPaymentCase):

    def _provider(self):
        """A provider record with code `none`.

        Core `payment` ships exactly one code -- "No Provider Set" -- and
        every real provider is a separate module. This addon deliberately
        depends on the FRAMEWORK and not on any of them: core Odoo has no
        Vietnamese provider (no VNPay, no MoMo), so naming one here would
        pick the merchant account for whoever deploys this. The parts under
        test -- entitlement, the amount coming from the invoice, a disabled
        provider being refused -- are framework behaviour and are the same
        whichever module is installed later.
        """
        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'none')], limit=1)
        self.assertTrue(provider, 'no payment.provider record at all')
        provider.write({'state': 'test'})
        if not provider.payment_method_ids:
            # Core `payment` ships no method records either -- every one
            # comes from a provider module. Create the minimum the framework
            # needs, rather than depending on a provider to get it.
            method = self.env['payment.method'].sudo().create({
                'name': 'PT Method', 'code': 'pt_method'})
            provider.write({'payment_method_ids': [(4, method.id)]})
        return provider

    def test_a_provider_with_no_payment_method_says_so(self):
        self._entitle()
        invoice = self._invoice(amount=500.0)
        bare = self.env['payment.provider'].sudo().search(
            [('code', '=', 'none')], limit=1).copy({
                'name': 'PT Bare', 'state': 'test'})
        bare.write({'payment_method_ids': [(5, 0, 0)]})
        with self.assertRaises(UserError):
            self._api().dms_portal_payment_start(invoice.id, bare.id)

    def test_a_transaction_for_another_partners_invoice_is_refused(self):
        self._entitle()
        provider = self._provider()
        stray = self.env['account.move'].sudo().with_company(
            self.dist).create({
                'move_type': 'out_invoice',
                'partner_id': self.outlet_b.id,
                'company_id': self.dist.id,
                'invoice_line_ids': [(0, 0, {
                    'product_id': self.product_a.id, 'quantity': 1,
                    'price_unit': 10.0, 'tax_ids': [(6, 0, [])]})],
            })
        with self.assertRaises(AccessError):
            self._api().dms_portal_payment_start(stray.id, provider.id)

    def test_a_draft_invoice_cannot_be_paid(self):
        self._entitle()
        invoice = self._invoice(amount=500.0, post=False)
        with self.assertRaises(UserError):
            self._api().dms_portal_payment_start(
                invoice.id, self._provider().id)

    def test_the_amount_comes_from_the_invoice_not_the_caller(self):
        """A transaction that trusts a client-supplied amount is an invoice
        the payer prices themselves. The signature has nowhere to put one."""
        import inspect
        sig = inspect.signature(
            type(self.env['dms.portal.api']).dms_portal_payment_start)
        self.assertNotIn('amount', sig.parameters)

        self._entitle()
        invoice = self._invoice(amount=500.0)
        result = self._api().dms_portal_payment_start(
            invoice.id, self._provider().id)
        self.assertEqual(result['amount'], invoice.amount_residual)

    def test_a_disabled_provider_is_refused(self):
        self._entitle()
        invoice = self._invoice(amount=500.0)
        provider = self._provider()
        provider.write({'state': 'disabled'})
        with self.assertRaises(UserError):
            self._api().dms_portal_payment_start(invoice.id, provider.id)
