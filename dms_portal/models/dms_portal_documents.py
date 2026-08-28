from odoo import api, models


class DmsPortalDocuments(models.AbstractModel):
    """Read-only views of what already exists elsewhere.

    Plan 11 section 3 forbids a debt balance outside Accounting, and
    `dms_outlet_credit.current_debt` is already `store=False` for that reason.
    This reads; it never writes a number about money.
    """
    _inherit = 'dms.portal.api'

    #: Everything a portal caller may ask for, and the model behind it. An
    #: allow-list rather than a `getattr`, so a model added to `dms` later is
    #: not portal-visible by accident.
    _DOCUMENT_KINDS = {
        'order': ('sale.order', 'partner_id'),
        'delivery': ('stock.picking', 'partner_id'),
        'invoice': ('account.move', 'partner_id'),
        'payment': ('account.payment', 'partner_id'),
    }

    @api.model
    def dms_portal_documents(self, kind, outlet_id=None):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_documents
           POST /json/2/dms.portal.api/dms_portal_documents
        """
        if kind not in self._DOCUMENT_KINDS:
            raise ValueError(f'Unknown document kind: {kind!r}')
        outlet = self._dms_portal_outlet(outlet_id)
        model, partner_field = self._DOCUMENT_KINDS[kind]
        domain = [(partner_field, '=', outlet.id)]
        if kind == 'order':
            domain.append(('dms_flow_type', '=', 'dsr'))
        if kind == 'invoice':
            domain += [('move_type', 'in', ('out_invoice', 'out_refund')),
                       ('state', '=', 'posted')]
        records = self.env[model].sudo().search(domain, order='id desc',
                                                limit=200)
        return [self._dms_portal_document_row(kind, rec) for rec in records]

    @api.model
    def _dms_portal_document_row(self, kind, rec):
        """Built field by field, never by subtraction.

        Section 8 forbids internal notes and margins reaching the portal. A
        row assembled from `rec.read()` minus a blocklist lets the next field
        somebody adds through by default.
        """
        row = {'id': rec.id, 'name': rec.display_name}
        if kind == 'order':
            row.update({'state': rec.dms_approval_state,
                        'amount_total': rec.amount_total,
                        'date_order': str(rec.date_order or '')})
        elif kind == 'delivery':
            row.update({'state': rec.state,
                        'scheduled_date': str(rec.scheduled_date or '')})
        elif kind == 'invoice':
            row.update({'amount_total': rec.amount_total,
                        'amount_residual': rec.amount_residual,
                        'invoice_date_due': str(rec.invoice_date_due or '')})
        elif kind == 'payment':
            row.update({'amount': rec.amount, 'state': rec.state,
                        'payment_date': str(rec.date or '')})
        return row

    @api.model
    def dms_portal_debt(self, outlet_id=None):
        """Open receivable, summed from Accounting.

        Not read from `dms.outlet.credit`: plan 11 section 3 says open debt is
        computed from Accounting per Distributor and company context, and the
        column that used to hold it drifted from the invoices precisely
        because two places held the same number.
        """
        outlet = self._dms_portal_outlet(outlet_id)
        invoices = self.env['account.move'].sudo().search([
            ('partner_id', '=', outlet.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', '!=', 'paid'),
        ])
        return {
            'outlet_id': outlet.id,
            'open_amount': sum(invoices.mapped('amount_residual')),
            'invoice_count': len(invoices),
        }
