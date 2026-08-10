from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query

from odoo.addons.fastapi.dependencies import odoo_env
from odoo.api import Environment
from odoo.tools import html2plaintext

from odoo.addons.bamboo_public_api.controllers.common import image_url, page_meta

from ..schemas.envelope import ResponseEnvelope
from ..schemas.public import CourseDetailOut, CourseOut, LessonOut
from ._common import require_app

# Soft dependency on `website_slides` — see routers/blog.py.
courses_router = APIRouter(
    tags=["Courses"], dependencies=[Depends(require_app("course"))]
)


def _course_out(channel) -> CourseOut:
    return CourseOut(
        id=channel.id,
        name=channel.name,
        description=html2plaintext(channel.description_short) if channel.description_short else "",
        total_slides=channel.total_slides,
        members_count=channel.members_count,
        cover_url=image_url("slide.channel", channel.id, "image_512"),
    )


@courses_router.get("/courses", response_model=ResponseEnvelope[List[CourseOut]])
async def list_courses(
    env: Annotated[Environment, Depends(odoo_env)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    Channel = env["slide.channel"].sudo()
    domain = [("is_published", "=", True)]
    total = Channel.search_count(domain)
    channels = Channel.search(domain, limit=limit, offset=(page - 1) * limit, order="sequence, name")
    return ResponseEnvelope(
        data=[_course_out(c) for c in channels], meta=page_meta(total, limit, page)
    )


@courses_router.get("/courses/{course_id}", response_model=ResponseEnvelope[CourseDetailOut])
async def get_course(
    course_id: int,
    env: Annotated[Environment, Depends(odoo_env)],
):
    channel = env["slide.channel"].sudo().browse(course_id)
    if not channel.exists() or not channel.is_published:
        raise HTTPException(status_code=404, detail="Course not found")
    lessons = channel.slide_ids.filtered(lambda s: s.is_published).sorted("sequence")
    detail = CourseDetailOut(
        **_course_out(channel).model_dump(),
        description_html=channel.description or "",
        website_url=channel.website_url or "",
        lessons=[
            LessonOut(id=s.id, name=s.name, category=s.slide_category or "", sequence=s.sequence)
            for s in lessons
        ],
    )
    return ResponseEnvelope(data=detail)
