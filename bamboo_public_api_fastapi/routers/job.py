"""Job (website_hr_recruitment) — published jobs, detail, public apply.

Apply stays `auth='public'` and accepts either a JSON body or a multipart form
with an optional CV, exactly like the controller (which branches on the
content-type in `common.read_body`). The branching is done here rather than with
two FastAPI signatures because a single route cannot declare both a pydantic body
and an `UploadFile`.
"""

import base64
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile

from odoo.addons.bamboo_public_api.controllers.job import _job_card, _job_detail

from ..schemas.envelope import ResponseEnvelope
from ..schemas.site import ApplicantOut, JobCardOut, JobDetailOut
from ._common import Paging, PublicEnv, meta_page, require_app

job_router = APIRouter(tags=["Job"], dependencies=[Depends(require_app("job"))])


def _published(env, job_id: int):
    job = env["hr.job"].sudo().browse(job_id)
    if not job.exists() or not job.website_published:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@job_router.get("/jobs", response_model=ResponseEnvelope[List[JobCardOut]])
async def jobs(env: PublicEnv, paging: Paging):
    domain = [("website_published", "=", True)]
    Job = env["hr.job"].sudo()
    total = Job.search_count(domain)
    records = Job.search(domain, limit=paging.limit, offset=paging.offset, order="name")
    return ResponseEnvelope(
        data=[_job_card(j) for j in records], meta=meta_page(total, paging)
    )


@job_router.get("/jobs/{job_id}", response_model=ResponseEnvelope[JobDetailOut])
async def job_detail(job_id: int, env: PublicEnv):
    return ResponseEnvelope(data=_job_detail(_published(env, job_id)))


@job_router.post(
    "/jobs/{job_id}/apply",
    response_model=ResponseEnvelope[ApplicantOut],
    status_code=201,
)
async def job_apply(job_id: int, request: Request, env: PublicEnv):
    """Body: `{name, email, phone, cover_letter}` as JSON, or the same fields as a
    multipart form with an optional `file` (the CV)."""
    job = _published(env, job_id)
    body, upload = await _read_body(request)

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    if not name or not email:
        raise HTTPException(status_code=422, detail="Name and email are required")

    applicant = (
        env["hr.applicant"]
        .sudo()
        .create(
            {
                "partner_name": name,
                "email_from": email,
                "partner_phone": body.get("phone") or "",
                "job_id": job.id,
                "department_id": job.department_id.id or False,
            }
        )
    )
    cover = body.get("cover_letter") or body.get("message")
    if cover:
        applicant.message_post(body=cover)

    if upload is not None:
        env["ir.attachment"].sudo().create(
            {
                "name": upload.filename,
                "datas": base64.b64encode(await upload.read()),
                "res_model": "hr.applicant",
                "res_id": applicant.id,
            }
        )
    return ResponseEnvelope(data=ApplicantOut(applicant_id=applicant.id))


async def _read_body(request: Request):
    """(fields, cv_upload) from a JSON or multipart body — `common.read_body` + files."""
    ctype = request.headers.get("content-type") or ""
    if "application/json" in ctype:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — an unparseable body is an empty one
            body = {}
        return (body if isinstance(body, dict) else {}), None

    form = await request.form()
    fields: Dict[str, Any] = {}
    upload = None
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if key == "file":
                upload = value
        else:
            fields[key] = value
    return fields, upload
