"""Plan 18B ticket B18-04/B18-07 — inbox, consent, and what "delivered" means.

Section 7: "Notification event idempotent; delivery status not interpreted as
business completion." Section 8: consent and opt-out enforced.
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_channel_account import ChannelCase


@tagged('post_install', '-at_install')
class TestChannelInbox(ChannelCase):

    def setUp(self):
        super().setUp()
        self.account.write({'can_send_messages': True})
        self.account.action_activate()
        self.conversation = self.env['dms.channel.conversation'].create({
            'channel_account_id': self.account.id,
            'external_conversation_id': 'conv-1'})
        self.agent = self.env['res.users'].create({
            'name': 'CH Agent', 'login': 'ch-agent@dms.test',
            'group_ids': [(4, self.env.ref('dms.group_dms_sale_admin').id)]})

    def test_a_template_needs_consent(self):
        """Section 8 makes opt-in a precondition, not a preference."""
        self.assertFalse(self.conversation.dms_can_send_template())
        self.conversation.consent = True
        self.assertTrue(self.conversation.dms_can_send_template())

    def test_a_notify_only_account_that_cannot_send_is_refused(self):
        self.conversation.consent = True
        self.account.write({'can_send_messages': False})
        self.assertFalse(self.conversation.dms_can_send_template())

    def test_a_closed_conversation_cannot_be_assigned(self):
        self.conversation.state = 'closed'
        with self.assertRaises(UserError):
            self.conversation.action_assign(self.agent)

    def test_assignment_records_the_human(self):
        self.conversation.action_assign(self.agent)
        self.assertEqual(self.conversation.assigned_user_id, self.agent)
        self.assertEqual(self.conversation.state, 'assigned')

    def test_the_unique_key_is_in_postgres(self):
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_channel_conversation'::regclass
               AND contype = 'u'
        """)
        self.assertTrue(self.env.cr.fetchall())

    def test_sla_empty_means_no_sla_not_any_time(self):
        """A NULL due date that some report reads as "not yet overdue" is the
        same bug as one that reads as "overdue forever". The field's help
        says which; this asserts the default is not silently zero."""
        self.assertFalse(self.conversation.sla_due_at)
