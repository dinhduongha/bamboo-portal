"""Contact form — public submit → `crm.lead` (guarded on `website_crm`)."""

from fastapi import APIRouter, Depends, HTTPException

from ..schemas.envelope import ResponseEnvelope
from ..schemas.site import ContactIn, LeadOut
from ._common import PublicEnv, require_app

contact_router = APIRouter(
    tags=["Contact"], dependencies=[Depends(require_app("contact"))]
)


@contact_router.post(
    "/contact", response_model=ResponseEnvelope[LeadOut], status_code=201
)
async def contact(body: ContactIn, env: PublicEnv):
    name = (body.name or "").strip()
    email = (body.email or "").strip()
    if not name or not email:
        raise HTTPException(status_code=422, detail="Name and email are required")

    subject = (body.subject or "").strip() or ("Website contact: %s" % name)
    lead = (
        env["crm.lead"]
        .sudo()
        .create(
            {
                "name": subject,
                "contact_name": name,
                "email_from": email,
                "phone": body.phone or "",
                "description": (body.message or "").strip(),
                "type": "lead",
            }
        )
    )
    return ResponseEnvelope(data=LeadOut(lead_id=lead.id))
