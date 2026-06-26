# -*- coding: utf-8 -*-
"""Blog (website_blog) public read endpoints — blogs, a blog's posts, a post.

Read-only / anonymous. `blog.blog` has no publish flag, so all blogs are listed;
`blog.post` is filtered to `website_published`. Cover images come from the post's
`cover_properties` JSON. Post `content` is HTML.
"""
from odoo import http
from odoo.http import request

from .common import (
    API_ROOT,
    cover_image_url,
    err,
    ok,
    page_meta,
    page_params,
    requires_app,
)


def _post_card(post):
    return {
        'id': post.id,
        'name': post.name,
        'subtitle': post.subtitle or '',
        'teaser': post.teaser or '',
        'blog_id': post.blog_id.id,
        'blog_name': post.blog_id.name,
        'author': post.author_id.name if post.author_id else '',
        'post_date': post.post_date.isoformat() if post.post_date else None,
        'cover_url': cover_image_url(post.cover_properties),
    }


def _post_detail(post):
    data = _post_card(post)
    data['content'] = post.content or ''
    data['website_url'] = post.website_url or ''
    return data


class BambooPublicBlog(http.Controller):

    @http.route(API_ROOT + '/blogs', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('blog')
    def blogs(self, **kw):
        Blog = request.env['blog.blog'].sudo()
        blogs = Blog.search([], order='name')
        data = [{
            'id': b.id,
            'name': b.name,
            'subtitle': b.subtitle or '',
            'post_count': request.env['blog.post'].sudo().search_count([
                ('blog_id', '=', b.id), ('website_published', '=', True),
            ]),
        } for b in blogs]
        return ok(data=data, meta={'total': len(data)})

    @http.route(API_ROOT + '/blogs/<int:blog_id>/posts', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('blog')
    def blog_posts(self, blog_id, **kw):
        domain = [('blog_id', '=', blog_id), ('website_published', '=', True)]
        Post = request.env['blog.post'].sudo()
        limit, offset, page = page_params()
        total = Post.search_count(domain)
        posts = Post.search(domain, limit=limit, offset=offset, order='post_date desc')
        return ok(data=[_post_card(p) for p in posts], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/posts/<int:post_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('blog')
    def post_detail(self, post_id, **kw):
        post = request.env['blog.post'].sudo().browse(post_id)
        if not post.exists() or not post.website_published:
            return err('Post not found', 404)
        return ok(data=_post_detail(post))
