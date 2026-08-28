"""Plan 16C Task 1 — reading money without owning a copy of it.

Plan 11 section 3: "Collection custom chi giu field-operation lifecycle/
evidence/collector/handover, KHONG giu debt balance" and "Open debt/overdue
tinh tu Accounting theo Distributor/company context." The column that used to
hold the balance drifted from the invoices precisely because two places held
the same number, and nobody could say which was right.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestPortalDocuments(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    def setUp(self):
        super().setUp()
        # A company with no sale journal cannot post an invoice --
        # "No journal could be found in company ... for any of those types:
        # sale". `dms/tests/test_collection_payment.py` provides one the same
        # way; a fresh `res.company` in a test does not get a chart of
        # accounts on its own.
        Account = self.env['account.account'].sudo()
        self.income_account = Account.create({
            'name': 'PT Income', 'code': 'PT4000',
            'account_type': 'income', 'company_ids': [(6, 0, [self.dist.id])]})
        self.receivable_account = Account.create({
            'name': 'PT Receivable', 'code': 'PT1310',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [(6, 0, [self.dist.id])]})
        self.sale_journal = self.env['account.journal'].sudo().create({
            'name': 'PT Sales', 'code': 'PTSA', 'type': 'sale',
            'company_id': self.dist.id,
            'default_account_id': self.income_account.id})
        # A brand-new `res.company` in a test has no chart of accounts, so
        # neither the journal nor the partner can resolve an account and the
        # move dies on `account_move_line_check_accountable_required_fields`.
        # Two accounts and a journal are the smallest fixture that lets a real
        # invoice post; loading a full chart template here would be slower and
        # would test Odoo's localisation rather than this code.
        self.outlet_a.with_company(
            self.dist).property_account_receivable_id = self.receivable_account

    def _invoice(self, amount=500.0, post=True):
        """A real customer invoice at the Distributor.

        At the Distributor, not the parent: the receivable belongs to the
        company that served the Outlet, which is the same rule
        `_check_dms_dsr_company` enforces on the order.
        """
        move = self.env['account.move'].sudo().with_company(
            self.dist).create({
                'move_type': 'out_invoice',
                'partner_id': self.outlet_a.id,
                'company_id': self.dist.id,
                'invoice_line_ids': [(0, 0, {
                    'product_id': self.product_a.id,
                    'quantity': 1,
                    'price_unit': amount,
                    'tax_ids': [(6, 0, [])],
                })],
            })
        if post:
            move.action_post()
        return move

    def test_documents_of_an_unentitled_outlet_are_refused(self):
        self._entitle()
        with self.assertRaises(AccessError):
            self._api().dms_portal_documents('invoice',
                                             outlet_id=self.outlet_b.id)

    def test_an_unknown_kind_is_refused_not_guessed(self):
        self._entitle()
        with self.assertRaises(ValueError):
            self._api().dms_portal_documents('res.users')

    def test_debt_is_read_from_accounting(self):
        self._entitle()
        self._invoice(amount=500.0)
        debt = self._api().dms_portal_debt(self.outlet_a.id)
        self.assertEqual(debt['open_amount'], 500.0)
        self.assertEqual(debt['invoice_count'], 1)

    def test_debt_does_not_come_from_the_dms_credit_row(self):
        """Writing a number onto `dms.outlet.credit` must not move the debt.
        If it does, there are two answers again."""
        self._entitle()
        self._invoice(amount=500.0)
        before = self._api().dms_portal_debt(self.outlet_a.id)['open_amount']
        self.env['dms.outlet.credit'].sudo().search([
            ('res_partner_id', '=', self.outlet_a.id)]).write(
                {'credit_limit': 42.0})
        self.outlet_a.invalidate_recordset()
        after = self._api().dms_portal_debt(self.outlet_a.id)['open_amount']
        self.assertEqual(before, after)

    def test_a_draft_invoice_is_not_shown(self):
        self._entitle()
        self._invoice(amount=500.0, post=False)
        self.assertEqual(
            self._api().dms_portal_documents('invoice', self.outlet_a.id), [])

    def test_an_invoice_row_never_carries_internal_fields(self):
        self._entitle()
        self._invoice()
        rows = self._api().dms_portal_documents('invoice', self.outlet_a.id)
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn('narration', row)
            self.assertNotIn('message_ids', row)

    def test_orders_listed_are_only_this_outlets(self):
        self._entitle()
        self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1}])
        other = self.env['sale.order'].sudo().create({
            'partner_id': self.outlet_b.id, 'dms_flow_type': False})
        rows = self._api().dms_portal_documents('order', self.outlet_a.id)
        self.assertNotIn(other.id, [row['id'] for row in rows])
