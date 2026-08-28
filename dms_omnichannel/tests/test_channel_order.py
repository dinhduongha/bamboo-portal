"""Plan 18A ticket B18-05 (the mapping half) — external orders.

Section 4: the key is `(channel_account, external_order_id)`. Section 13:
"Same external ID in two channel accounts does not collide" and "duplicate/
out-of-order event safe".
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_channel_account import ChannelCase


@tagged('post_install', '-at_install')
class TestChannelOrderMapping(ChannelCase):

    def setUp(self):
        super().setUp()
        self.Order = self.env['dms.channel.order']
        self.account.action_activate()
        self.other_account = self.env['dms.channel.account'].create({
            'name': 'CH TikTok', 'channel': 'tiktok',
            'external_account_id': 'shop-9',
            'secret_ref': self.SECRET_KEY,
            'can_receive_orders': True})
        self.other_account.action_activate()

    def test_the_same_external_id_on_two_accounts_does_not_collide(self):
        """A global unique key rejects a legitimate TikTok order because a
        Zalo order happens to share its number. `dms.eb2b.order` in core
        carries exactly that key today; section 11 lists fixing it as
        migration work."""
        first = self.Order.dms_record_external_order(
            self.account.id, 'EXT-1', {'lines': []})
        second = self.Order.dms_record_external_order(
            self.other_account.id, 'EXT-1', {'lines': []})
        self.assertNotEqual(first, second)

    def test_a_redelivered_webhook_records_one_order(self):
        payload = {'lines': [{'sku': 'A', 'qty': 2}]}
        first = self.Order.dms_record_external_order(
            self.account.id, 'EXT-2', payload)
        second = self.Order.dms_record_external_order(
            self.account.id, 'EXT-2', payload)
        self.assertEqual(first, second)

    def test_the_checksum_ignores_key_order(self):
        """A re-serialised identical payload is the same event, not an
        amendment. Without sorting, every redelivery through a different JSON
        encoder looks like a change."""
        a = self.Order._dms_checksum({'x': 1, 'y': 2})
        b = self.Order._dms_checksum({'y': 2, 'x': 1})
        self.assertEqual(a, b)

    def test_an_account_that_cannot_receive_orders_is_refused(self):
        notify_only = self.env['dms.channel.account'].create({
            'name': 'CH Notify', 'channel': 'facebook',
            'external_account_id': 'page-1',
            'secret_ref': self.SECRET_KEY,
            'can_receive_orders': False})
        notify_only.action_activate()
        with self.assertRaises(UserError):
            self.Order.dms_record_external_order(
                notify_only.id, 'EXT-3', {'lines': []})

    def test_conversion_without_an_approved_link_is_refused(self):
        """Section 5.2 constraint 2, at the point it would cost money: a
        matched phone number is not an approved link, and an order converted
        on one bills a shop that never ordered."""
        order = self.Order.dms_record_external_order(
            self.account.id, 'EXT-4', {'lines': []})
        with self.assertRaises(UserError):
            order.dms_convert([])

    def test_the_unique_key_is_in_postgres(self):
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_channel_order'::regclass
               AND contype = 'u'
        """)
        self.assertTrue(self.env.cr.fetchall())

    def test_conversion_goes_through_the_dsr_service(self):
        """Not `sale.order.create`. `dms.eb2b.order` has its own route and
        therefore neither the credit check nor the assortment check -- the
        debt sub-plan 08 recorded, and the one thing this model exists not to
        repeat."""
        import inspect
        source = inspect.getsource(type(self.Order).dms_convert)
        self.assertIn('dms.order.api', source)
        self.assertNotIn("env['sale.order'].create", source)
