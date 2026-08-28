"""Plan 18C ticket B18-08 — retention and the right to erasure.

Section 8: "Data minimization, deletion/export request, media retention and
channel terms."
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_channel_account import ChannelCase


@tagged('post_install', '-at_install')
class TestChannelRetention(ChannelCase):

    def test_every_channel_model_has_a_retention_policy(self):
        """A model with no policy is a table that grows forever, and nobody
        notices until it is the reason a restore takes six hours."""
        Policy = self.env['dms.retention.policy']
        for model in ('dms.channel.conversation', 'dms.channel.identity',
                      'dms.channel.order'):
            self.assertTrue(
                Policy.search([('model_name', '=', model)]),
                f'no retention policy for {model}')

    def test_every_policy_names_its_legal_basis(self):
        """A retention table without one is a list of numbers nobody can
        defend when asked."""
        policies = self.env['dms.retention.policy'].search([
            ('data_class', 'like', 'channel-')])
        self.assertTrue(policies)
        for policy in policies:
            self.assertTrue((policy.legal_basis or '').strip(),
                            f'{policy.data_class} has no legal basis')

    def test_the_date_field_actually_exists_on_the_model(self):
        """The cron skips a policy whose date column was renamed, and logs it.
        A skipped policy is a table that is not being purged while the table
        of policies says it is."""
        for policy in self.env['dms.retention.policy'].search([
                ('data_class', 'like', 'channel-')]):
            model = self.env.get(policy.model_name)
            self.assertIsNotNone(model, policy.model_name)
            self.assertIn(policy.date_field, model._fields,
                          f'{policy.data_class} points at a column that is '
                          f'not on {policy.model_name}')

    def test_the_order_policy_outlives_the_conversation_policy(self):
        """A staging row deleted before the invoice it reconciles leaves the
        invoice unexplained; a support conversation has no such duty."""
        Policy = self.env['dms.retention.policy']
        order = Policy.search([('data_class', '=', 'channel-order')], limit=1)
        conversation = Policy.search(
            [('data_class', '=', 'channel-conversation')], limit=1)
        self.assertGreater(order.retention_days, conversation.retention_days)


@tagged('post_install', '-at_install')
class TestChannelErasure(ChannelCase):

    def setUp(self):
        super().setUp()
        self.account.action_activate()
        self.shop = self.env['res.partner'].create({
            'name': 'ER Shop', 'customer_rank': 1, 'phone': '0977000111'})
        self.identity = self.env['dms.channel.identity'].dms_resolve_from_token(
            self.account.id, 'zalo-erase-1',
            phone_from_channel='0977000111')

    def test_erasure_removes_the_phone_number(self):
        self.identity.dms_erase_pii(reason='customer asked')
        self.assertFalse(self.identity.phone_from_channel)

    def test_erasure_keeps_the_row_as_evidence(self):
        """Deleting the row resolves the tension between erasure and audit in
        the wrong direction: the link record answers the only question an
        incident asks — who could see what."""
        identity_id = self.identity.id
        self.identity.dms_erase_pii(reason='customer asked')
        self.assertTrue(
            self.env['dms.channel.identity'].browse(identity_id).exists())
        self.assertEqual(self.identity.state, 'revoked')

    def test_erasure_needs_a_reason(self):
        with self.assertRaises(UserError):
            self.identity.dms_erase_pii(reason='')

    def test_erasure_withdraws_consent(self):
        self.identity.consent = True
        self.identity.dms_erase_pii(reason='customer asked')
        self.assertFalse(self.identity.consent)

    def test_what_remains_identifies_nobody_on_its_own(self):
        self.identity.dms_erase_pii(reason='customer asked')
        remaining = self.identity.read()[0]
        self.assertNotIn('0977000111', str(remaining))
