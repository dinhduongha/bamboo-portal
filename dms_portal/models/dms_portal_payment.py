from odoo import api, models
from odoo.exceptions import AccessError, UserError


class DmsPortalPayment(models.AbstractModel):
    """Two ways to pay, one source of truth about who paid.

    Neither method here marks anything paid. Sub-plan 09 named the debt it
    would otherwise create: *"mot co 'da thu' do nguoi ban bam la mot khoan
    phai thu bi xoa bang mot nut."* On the portal it is worse -- the person
    pressing it is the one who owes the money.
    """
    _inherit = 'dms.portal.api'

    @api.model
    def dms_portal_payment_qr(self, order_id):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_payment_qr
           POST /json/2/dms.portal.api/dms_portal_payment_qr

        Delegates to `sale.order.dms_vietqr_payload`, which has no account
        parameter at all -- not "ignores one if sent", but no place to put
        one. A QR pointing at a personal account is the Distributor's money
        going into somebody's pocket while the shop owner believes they paid
        correctly (plan 09 section 5.1).
        """
        order = self.env['sale.order'].sudo().browse(int(order_id)).exists()
        allowed = self.env.user.dms_allowed_partner_ids()
        if not order or order.partner_id.id not in allowed:
            raise AccessError('No approved entitlement for this order.')
        return {
            'order_id': order.id,
            # No amount parameter. `dms_vietqr_payload` accepts one, and for
            # a salesman taking a part payment at the counter that is right;
            # for the debtor's own screen it is an invoice they price
            # themselves. Partial payment from the portal is a deliberate
            # change, not a default.
            'payload': order.dms_vietqr_payload(),
            # Said out loud, because the screen showing a QR is exactly where
            # somebody will assume the money has arrived.
            'settled': False,
            'note': 'Scanning this does not settle the invoice. Payment is '
                    'recognised on bank confirmation or reconciliation.',
        }

    @api.model
    def dms_portal_payment_start(self, invoice_id, provider_id):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_payment_start
           POST /json/2/dms.portal.api/dms_portal_payment_start

        Builds a `payment.transaction` on Odoo's own payment framework rather
        than on a provider chosen in code. There is no Vietnamese provider in
        core (no VNPay, no MoMo), so committing to one here would mean
        rewriting this the day a different merchant account is signed --
        while the framework's callback, signature and state machine are the
        parts that actually matter.

        The AMOUNT comes from the invoice. A transaction that trusts a
        client-supplied amount is an invoice the payer prices themselves.
        """
        invoice = self.env['account.move'].sudo().browse(
            int(invoice_id)).exists()
        allowed = self.env.user.dms_allowed_partner_ids()
        if not invoice or invoice.partner_id.id not in allowed:
            raise AccessError('No approved entitlement for this invoice.')
        if invoice.move_type not in ('out_invoice', 'out_refund') \
                or invoice.state != 'posted':
            raise UserError('Only a posted customer invoice can be paid.')
        provider = self.env['payment.provider'].sudo().browse(
            int(provider_id)).exists()
        if not provider or provider.state == 'disabled':
            raise UserError('Unknown or disabled payment provider.')
        method = provider.payment_method_ids[:1]
        if not method:
            # Without this the create dies on `null value in column
            # "payment_method_id" violates not-null constraint`, which reads
            # like a bug in this code and is in fact an unconfigured provider.
            raise UserError(
                f'{provider.name} has no payment method enabled. Configure '
                f'one before offering it on the portal.')
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': method.id,
            'partner_id': invoice.partner_id.id,
            'amount': invoice.amount_residual,
            'currency_id': invoice.currency_id.id,
            'invoice_ids': [(6, 0, [invoice.id])],
            'reference': self.env['payment.transaction'].sudo()._compute_reference(
                provider.code, prefix=invoice.name),
        })
        return {'transaction_id': tx.id, 'reference': tx.reference,
                'amount': tx.amount, 'state': tx.state}
