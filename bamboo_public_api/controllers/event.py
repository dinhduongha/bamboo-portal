# -*- coding: utf-8 -*-
"""Event (website_event) public read endpoints — list + detail (with tickets).

Read-only / anonymous: only `website_published` events, via sudo(). Times are
ISO; binary covers are returned as `/web/image` (image_1024) or the cover URL
parsed from `cover_properties`.
"""
from odoo import http
from odoo.http import request

from .common import (
    API_ROOT,
    cover_image_url,
    err,
    image_url,
    ok,
    page_meta,
    page_params,
    requires_app,
)


def _event_card(ev):
    return {
        'id': ev.id,
        'name': ev.name,
        'subtitle': ev.subtitle or '',
        'date_begin': ev.date_begin.isoformat() if ev.date_begin else None,
        'date_end': ev.date_end.isoformat() if ev.date_end else None,
        'organizer': ev.organizer_id.name if ev.organizer_id else '',
        'location': ev.address_id.display_name if ev.address_id else '',
        'event_type': ev.event_type_id.name if ev.event_type_id else '',
        'tags': ev.tag_ids.mapped('name'),
        'seats_available': ev.seats_available if ev.seats_limited else None,
        'image_url': image_url('event.event', ev.id, 'image_1024'),
        'cover_url': cover_image_url(ev.cover_properties),
    }


def _event_detail(ev):
    data = _event_card(ev)
    data['description'] = ev.description or ''
    data['website_url'] = ev.website_url or ''
    data['tickets'] = [{
        'id': tk.id,
        'name': tk.name,
        'price': tk.price,
        'seats_available': tk.seats_available if tk.seats_limited else None,
        'description': tk.description or '',
    } for tk in ev.event_ticket_ids]
    return data


class BambooPublicEvent(http.Controller):

    @http.route(API_ROOT + '/events', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('event')
    def events(self, **kw):
        domain = [('website_published', '=', True)]
        Event = request.env['event.event'].sudo()
        limit, offset, page = page_params()
        total = Event.search_count(domain)
        events = Event.search(domain, limit=limit, offset=offset, order='date_begin desc')
        return ok(data=[_event_card(e) for e in events], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/events/<int:event_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('event')
    def event_detail(self, event_id, **kw):
        ev = request.env['event.event'].sudo().browse(event_id)
        if not ev.exists() or not ev.website_published:
            return err('Event not found', 404)
        return ok(data=_event_detail(ev))

    @http.route(API_ROOT + '/events/<int:event_id>/register', type='http', auth='user', methods=['POST'], csrf=False)
    @requires_app('event')
    def event_register(self, event_id, **kw):
        from .common import read_body
        ev = request.env['event.event'].sudo().browse(event_id)
        if not ev.exists() or not ev.website_published:
            return err('Event not found', 404)
        body = read_body()
        partner = request.env.user.partner_id
        vals = {
            'event_id': ev.id,
            'partner_id': partner.id,
            'name': (body.get('name') or '').strip() or partner.name,
            'email': (body.get('email') or '').strip() or partner.email or '',
            'phone': body.get('phone') or partner.phone or '',
        }
        ticket_id = body.get('ticket_id')
        if ticket_id:
            ticket = ev.event_ticket_ids.filtered(lambda t: t.id == int(ticket_id))
            if not ticket:
                return err('Invalid ticket', 422)
            vals['event_ticket_id'] = ticket.id
        try:
            reg = request.env['event.registration'].sudo().create(vals)
        except Exception as exc:
            return err('Could not register: %s' % exc, 400)
        return ok(data={'registration_id': reg.id, 'state': reg.state}, status=201)
