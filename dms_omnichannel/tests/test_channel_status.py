"""Plan 18B ticket B18-06 — status sync, and the loop it must not enter.

Section 6: "Status sync loop protection using version/source marker."
Section 13: "duplicate/out-of-order event safe" and "outbound retry does not
loop/duplicate".
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_channel_account import ChannelCase


@tagged('post_install', '-at_install')
class TestChannelStatusSync(ChannelCase):

    def setUp(self):
        super().setUp()
        self.account.action_activate()
        self.order = self.env['dms.channel.order'].dms_record_external_order(
            self.account.id, 'EXT-STATUS', {'lines': []})

    def test_an_inbound_status_is_applied(self):
        self.assertTrue(self.order.dms_apply_channel_status('shipped', 1))
        self.assertEqual(self.order.fulfillment_state, 'shipped')
        self.assertEqual(self.order.status_source, 'channel')

    def test_an_out_of_order_status_does_not_move_the_record_backwards(self):
        """A delivered order becoming pending again an hour after the
        customer signed for it is what an unguarded replay looks like."""
        self.order.dms_apply_channel_status('delivered', 5)
        self.assertFalse(self.order.dms_apply_channel_status('pending', 2))
        self.assertEqual(self.order.fulfillment_state, 'delivered')

    def test_a_redelivered_status_is_ignored(self):
        self.order.dms_apply_channel_status('shipped', 3)
        self.assertFalse(self.order.dms_apply_channel_status('shipped', 3))

    def test_our_own_value_coming_back_does_not_start_a_loop(self):
        """Odoo pushes "shipped"; the channel echoes it on its next poll. If
        the echo is written, it bumps the version and triggers another push,
        and the two systems talk to each other forever. No single step is
        wrong, which is why this needs a test rather than care."""
        self.order.dms_push_status('shipped')
        version_after_push = self.order.status_version
        applied = self.order.dms_apply_channel_status(
            'shipped', version_after_push + 1)
        self.assertFalse(applied)
        self.assertEqual(self.order.status_source, 'odoo')
        self.assertEqual(self.order.fulfillment_state, 'shipped')

    def test_a_genuine_change_after_our_push_is_applied(self):
        """The loop guard must not swallow real news. The channel saying
        "cancelled" after we said "shipped" is the customer cancelling."""
        self.order.dms_push_status('shipped')
        applied = self.order.dms_apply_channel_status(
            'cancelled', self.order.status_version + 1)
        self.assertTrue(applied)
        self.assertEqual(self.order.fulfillment_state, 'cancelled')

    def test_pushing_an_unknown_state_is_refused(self):
        with self.assertRaises(UserError):
            self.order.dms_push_status('teleported')

    def test_each_push_advances_the_version(self):
        self.order.dms_push_status('shipped')
        first = self.order.status_version
        self.order.dms_push_status('delivered')
        self.assertGreater(self.order.status_version, first)
