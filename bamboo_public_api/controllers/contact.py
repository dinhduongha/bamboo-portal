# -*- coding: utf-8 -*-
"""Contact form — public submit → crm.lead.

auth='public'. Guarded on `website_crm` (so crm.lead exists). Creates a lead with
the visitor's details + message; sudo (public user can't create leads otherwise).
"""
from odoo import http
from odoo.http import request

from .common import API_ROOT, err, ok, read_body, requires_app


class BambooPublicContact(http.Controller):

    @http.route(API_ROOT + '/contact', type='http', auth='public', methods=['POST'], csrf=False)
    @requires_app('contact')
    def contact(self, **kw):
        body = read_body()
        name = (body.get('name') or '').strip()
        email = (body.get('email') or '').strip()
        message = (body.get('message') or '').strip()
        if not name or not email:
            return err('Name and email are required', 422)

        subject = (body.get('subject') or '').strip() or ('Website contact: %s' % name)
        lead = request.env['crm.lead'].sudo().create({
            'name': subject,
            'contact_name': name,
            'email_from': email,
            'phone': body.get('phone') or '',
            'description': message,
            'type': 'lead',
        })
        return ok(data={'lead_id': lead.id}, status=201)
