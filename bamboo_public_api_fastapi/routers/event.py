"""Event (website_event) — published events, detail with tickets, registration."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from odoo.addons.bamboo_public_api.controllers.event import _event_card, _event_detail

from ..schemas.envelope import ResponseEnvelope
from ..schemas.site import (
    EventCardOut,
    EventDetailOut,
    RegistrationIn,
    RegistrationOut,
)
from ._common import AuthEnv, Paging, PublicEnv, meta_page, require_app

event_router = APIRouter(tags=["Event"], dependencies=[Depends(require_app("event"))])


def _published(env, event_id: int):
    ev = env["event.event"].sudo().browse(event_id)
    if not ev.exists() or not ev.website_published:
        raise HTTPException(status_code=404, detail="Event not found")
    return ev


@event_router.get("/events", response_model=ResponseEnvelope[List[EventCardOut]])
async def events(env: PublicEnv, paging: Paging):
    domain = [("website_published", "=", True)]
    Event = env["event.event"].sudo()
    total = Event.search_count(domain)
    records = Event.search(
        domain, limit=paging.limit, offset=paging.offset, order="date_begin desc"
    )
    return ResponseEnvelope(
        data=[_event_card(e) for e in records], meta=meta_page(total, paging)
    )


@event_router.get(
    "/events/{event_id}", response_model=ResponseEnvelope[EventDetailOut]
)
async def event_detail(event_id: int, env: PublicEnv):
    return ResponseEnvelope(data=_event_detail(_published(env, event_id)))


@event_router.post(
    "/events/{event_id}/register",
    response_model=ResponseEnvelope[RegistrationOut],
    status_code=201,
)
async def event_register(event_id: int, body: RegistrationIn, env: AuthEnv):
    ev = _published(env, event_id)
    partner = env.user.partner_id
    vals = {
        "event_id": ev.id,
        "partner_id": partner.id,
        "name": (body.name or "").strip() or partner.name,
        "email": (body.email or "").strip() or partner.email or "",
        "phone": body.phone or partner.phone or "",
    }
    if body.ticket_id:
        ticket = ev.event_ticket_ids.filtered(lambda t: t.id == body.ticket_id)
        if not ticket:
            raise HTTPException(status_code=422, detail="Invalid ticket")
        vals["event_ticket_id"] = ticket.id
    try:
        reg = env["event.registration"].sudo().create(vals)
    except Exception as exc:  # noqa: BLE001 — surfaced to the attendee verbatim
        raise HTTPException(
            status_code=400, detail="Could not register: %s" % exc
        ) from exc
    return ResponseEnvelope(
        data=RegistrationOut(registration_id=reg.id, state=reg.state)
    )
