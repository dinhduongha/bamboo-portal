from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query

from odoo.addons.fastapi.dependencies import odoo_env
from odoo.api import Environment

from odoo.addons.bamboo_public_api.controllers.common import cover_image_url, page_meta

from ..schemas.envelope import ResponseEnvelope
from ..schemas.public import BlogOut, PostCardOut, PostDetailOut

blog_router = APIRouter(tags=["Blog"])


def _post_card(post) -> PostCardOut:
    return PostCardOut(
        id=post.id,
        name=post.name,
        subtitle=post.subtitle or "",
        teaser=post.teaser or "",
        blog_id=post.blog_id.id,
        blog_name=post.blog_id.name or "",
        author=post.author_id.name if post.author_id else "",
        post_date=post.post_date.isoformat() if post.post_date else None,
        cover_url=cover_image_url(post.cover_properties),
    )


@blog_router.get("/blogs", response_model=ResponseEnvelope[List[BlogOut]])
async def list_blogs(env: Annotated[Environment, Depends(odoo_env)]):
    Blog = env["blog.blog"].sudo()
    Post = env["blog.post"].sudo()
    blogs = Blog.search([], order="name")
    data = [
        BlogOut(
            id=b.id,
            name=b.name,
            subtitle=b.subtitle or "",
            post_count=Post.search_count([("blog_id", "=", b.id), ("website_published", "=", True)]),
        )
        for b in blogs
    ]
    return ResponseEnvelope(data=data, meta={"total": len(data)})


@blog_router.get("/blogs/{blog_id}/posts", response_model=ResponseEnvelope[List[PostCardOut]])
async def list_blog_posts(
    blog_id: int,
    env: Annotated[Environment, Depends(odoo_env)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    Post = env["blog.post"].sudo()
    domain = [("blog_id", "=", blog_id), ("website_published", "=", True)]
    total = Post.search_count(domain)
    posts = Post.search(domain, limit=limit, offset=(page - 1) * limit, order="post_date desc")
    return ResponseEnvelope(data=[_post_card(p) for p in posts], meta=page_meta(total, limit, page))


@blog_router.get("/posts/{post_id}", response_model=ResponseEnvelope[PostDetailOut])
async def get_post(post_id: int, env: Annotated[Environment, Depends(odoo_env)]):
    post = env["blog.post"].sudo().browse(post_id)
    if not post.exists() or not post.website_published:
        raise HTTPException(status_code=404, detail="Post not found")
    detail = PostDetailOut(
        **_post_card(post).model_dump(),
        content=post.content or "",
        website_url=post.website_url or "",
    )
    return ResponseEnvelope(data=detail)
