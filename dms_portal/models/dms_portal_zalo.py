from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class SaleOrderOutOfCycle(models.Model):
    _inherit = 'sale.order'

    #: CR-21. An out-of-cycle order is real; the visit is not -- nobody was in
    #: the shop, nothing was audited, no evidence was taken. Letting it create
    #: a visit inflates Coverage % and every KPI built on it for work no one
    #: did, and it inflates FASTEST at exactly the outlets that need a
    #: salesman least.
    dms_out_of_cycle = fields.Boolean(
        string='Out-of-cycle order', readonly=True, copy=False, index=True,
        help='Placed by the shop between scheduled visits. Volume is still '
             'credited to the responsible salesman, and reported separately '
             'from volume that came out of a visit.')
    dms_order_channel = fields.Selection([
        ('portal', 'Portal'),
        ('zalo', 'Zalo Mini App'),
    ], readonly=True, copy=False, index=True)


class DmsOrderApiPortalFields(models.AbstractModel):
    """Two more fields the portal may set at CREATE time.

    `_SUBMIT_FIELDS` is an allow-list, so `dms_out_of_cycle` and
    `dms_order_channel` cannot arrive through it by accident -- and they must
    arrive at create, because an order awaiting approval refuses writes
    ("dang cho duyet, khong sua duoc don"). Marking it afterwards is not an
    option, and widening the list in `dms` is not either: `dms` cannot name
    fields that only exist when this addon is installed.

    Both are server-set in `dms_portal_submit_out_of_cycle`. Adding them here
    does NOT let a client set them: the client's `vals` still passes through
    the same filter, and a client claiming its order was out-of-cycle only
    mislabels its own row -- it changes no gate and no money.
    """
    _inherit = 'dms.order.api'

    _SUBMIT_FIELDS = frozenset({
        'dms_outlet_visit_id', 'client_order_ref', 'note',
        'preferred_delivery_time_slot', 'delivery_priority',
        'dms_out_of_cycle', 'dms_order_channel',
    })


class DmsPortalZalo(models.AbstractModel):
    """The Zalo Mini App half of self-service.

    Master section 2.10, plan 16 section 5.2: shop owners in Vietnam largely
    do not register for, or use, a web portal on a phone. The Mini App is the
    channel they actually use -- scan at the counter, no install.

    Identity is NOT re-implemented here. `dms.channel.identity` in
    `dms_omnichannel` owns the token exchange, the ambiguity rules and the
    exception states, because plan 18 section 7 says so and because the Zalo
    rules and the TikTok rules are the same rules.
    """
    _inherit = 'dms.portal.api'

    @api.model
    def dms_portal_zalo_link(self, channel_account_id, external_user_id,
                             phone_from_channel=None):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_zalo_link
           POST /json/2/dms.portal.api/dms_portal_zalo_link

        Called by the adapter that has ALREADY exchanged the Zalo token for a
        number server-side. The parameter is named for where the value came
        from; one called `phone` would invite the number the client typed,
        and section 5.2 constraint 1 says a client-declared number is never
        trusted.

        Creates a link request and an entitlement request. Neither grants:
        constraint 2 is that a matching phone number opens a request, and
        read access to orders and debt waits for approval. A phone number is
        semi-public information -- evidence somebody knows the shop's number,
        not that they own the shop.
        """
        identity = self.env['dms.channel.identity'].sudo(
            ).dms_resolve_from_token(
                channel_account_id, external_user_id,
                phone_from_channel=phone_from_channel)
        entitlement = self.env['dms.portal.entitlement'].browse()
        if identity.state == 'requested' and identity.partner_id:
            entitlement = self.env['dms.portal.entitlement'].sudo().search([
                ('user_id', '=', self.env.uid),
                ('partner_id', '=', identity.partner_id.id),
            ], limit=1) or self.env['dms.portal.entitlement'].sudo().create({
                'user_id': self.env.uid,
                'partner_id': identity.partner_id.id,
                'company_id': identity.partner_id.company_id.id
                or self.env.company.id,
                'scope': 'outlet',
                'source': 'zalo',
            })
        return {
            'identity_id': identity.id,
            'identity_state': identity.state,
            'entitlement_id': entitlement.id if entitlement else False,
            'entitlement_state': entitlement.state if entitlement else False,
            'can_order': False,
        }

    @api.model
    def dms_portal_submit_out_of_cycle(self, outlet_id, lines, vals=None,
                                       operation_uuid=None,
                                       accept_price_change=False):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_submit_out_of_cycle
           POST /json/2/dms.portal.api/dms_portal_submit_out_of_cycle

        The same order path as `dms_portal_submit` -- credit gate, assortment
        gate, price confirmation, idempotency -- plus a mark, and explicitly
        WITHOUT a visit.

        `dms_outlet_visit_id` is stripped from `vals` rather than merely left
        unset: a client that sends one would otherwise attach the order to a
        visit and put the Coverage inflation back by hand.
        """
        clean = {k: v for k, v in (vals or {}).items()
                 if k != 'dms_outlet_visit_id'}
        # Set at CREATE, not after: the order goes straight to `submitted`
        # and a submitted order refuses writes.
        clean['dms_out_of_cycle'] = True
        clean['dms_order_channel'] = 'zalo'
        return self.dms_portal_submit(
            outlet_id, lines, vals=clean, operation_uuid=operation_uuid,
            accept_price_change=accept_price_change)
