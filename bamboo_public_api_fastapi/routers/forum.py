"""Forum (website_forum) — forums, questions, answers.

Reads are anonymous; asking and answering require a signed-in user and run
`with_user()` rather than `sudo()`, so forum karma rules actually apply.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from odoo.addons.bamboo_public_api.controllers.forum import (
    _question_card,
    _question_detail,
)

from ..schemas.envelope import ResponseEnvelope
from ..schemas.site import (
    AnswerCreatedOut,
    AnswerIn,
    ForumOut,
    QuestionCardOut,
    QuestionCreatedOut,
    QuestionDetailOut,
    QuestionIn,
)
from ._common import AuthEnv, Paging, PublicEnv, meta_page, require_app

forum_router = APIRouter(tags=["Forum"], dependencies=[Depends(require_app("forum"))])

_ACTIVE_QUESTION = [("parent_id", "=", False), ("state", "=", "active")]


@forum_router.get("/forums", response_model=ResponseEnvelope[List[ForumOut]])
async def forums(env: PublicEnv):
    Post = env["forum.post"].sudo()
    records = env["forum.forum"].sudo().search([], order="name")
    data = [
        ForumOut(
            id=f.id,
            name=f.name,
            description=f.description or "",
            question_count=Post.search_count([("forum_id", "=", f.id)] + _ACTIVE_QUESTION),
        )
        for f in records
    ]
    return ResponseEnvelope(data=data, meta={"total": len(data)})


@forum_router.get(
    "/forums/{forum_id}/questions",
    response_model=ResponseEnvelope[List[QuestionCardOut]],
)
async def forum_questions(forum_id: int, env: PublicEnv, paging: Paging):
    domain = [("forum_id", "=", forum_id)] + _ACTIVE_QUESTION
    Post = env["forum.post"].sudo()
    total = Post.search_count(domain)
    posts = Post.search(
        domain, limit=paging.limit, offset=paging.offset, order="create_date desc"
    )
    return ResponseEnvelope(
        data=[_question_card(p) for p in posts], meta=meta_page(total, paging)
    )


@forum_router.get(
    "/questions/{question_id}", response_model=ResponseEnvelope[QuestionDetailOut]
)
async def question_detail(question_id: int, env: PublicEnv):
    post = env["forum.post"].sudo().browse(question_id)
    if not post.exists() or post.parent_id or post.state != "active":
        raise HTTPException(status_code=404, detail="Question not found")
    return ResponseEnvelope(data=_question_detail(post))


@forum_router.post(
    "/forums/{forum_id}/questions",
    response_model=ResponseEnvelope[QuestionCreatedOut],
    status_code=201,
)
async def ask_question(forum_id: int, body: QuestionIn, env: AuthEnv):
    forum = env["forum.forum"].sudo().browse(forum_id)
    if not forum.exists():
        raise HTTPException(status_code=404, detail="Forum not found")
    title = (body.title or body.name or "").strip()
    content = (body.content or "").strip()
    if not title or not content:
        raise HTTPException(status_code=422, detail="Title and content are required")
    try:
        post = env["forum.post"].with_user(env.user).create(
            {"forum_id": forum.id, "name": title, "content": content}
        )
    except Exception as exc:  # noqa: BLE001 — karma refusals belong to the caller
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ResponseEnvelope(data=QuestionCreatedOut(question_id=post.id))


@forum_router.post(
    "/questions/{question_id}/answers",
    response_model=ResponseEnvelope[AnswerCreatedOut],
    status_code=201,
)
async def answer_question(question_id: int, body: AnswerIn, env: AuthEnv):
    question = env["forum.post"].sudo().browse(question_id)
    if not question.exists() or question.parent_id:
        raise HTTPException(status_code=404, detail="Question not found")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="Content is required")
    try:
        answer = env["forum.post"].with_user(env.user).create(
            {
                "forum_id": question.forum_id.id,
                "parent_id": question.id,
                "content": content,
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ResponseEnvelope(data=AnswerCreatedOut(answer_id=answer.id))
