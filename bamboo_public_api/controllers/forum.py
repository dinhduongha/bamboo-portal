# -*- coding: utf-8 -*-
"""Forum (website_forum) public read endpoints — forums, questions, a question.

Read-only / anonymous. `forum.forum` has no publish flag (list all). Questions =
`forum.post` with `parent_id = False` and `state = 'active'`; answers are the
question's `child_ids`. Posting/answering is auth (P4), not here.
"""
from odoo import http
from odoo.http import request

from .common import API_ROOT, err, ok, page_meta, page_params, requires_app


def _question_card(post):
    answers = post.child_ids.filtered(lambda p: p.state == 'active')
    return {
        'id': post.id,
        'name': post.name,
        'forum_id': post.forum_id.id,
        'forum_name': post.forum_id.name,
        'author': post.create_uid.name if post.create_uid else '',
        'create_date': post.create_date.isoformat() if post.create_date else None,
        'views': post.views,
        'vote_count': post.vote_count,
        'answer_count': len(answers),
        'tags': post.tag_ids.mapped('name'),
        'has_accepted': any(answers.mapped('is_correct')),
    }


def _question_detail(post):
    data = _question_card(post)
    data['content'] = post.content or ''
    answers = post.child_ids.filtered(lambda p: p.state == 'active')
    # Accepted answer first, then by votes.
    answers = answers.sorted(key=lambda a: (not a.is_correct, -a.vote_count))
    data['answers'] = [{
        'id': a.id,
        'content': a.content or '',
        'author': a.create_uid.name if a.create_uid else '',
        'create_date': a.create_date.isoformat() if a.create_date else None,
        'vote_count': a.vote_count,
        'is_correct': a.is_correct,
    } for a in answers]
    return data


class BambooPublicForum(http.Controller):

    @http.route(API_ROOT + '/forums', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('forum')
    def forums(self, **kw):
        forums = request.env['forum.forum'].sudo().search([], order='name')
        data = [{
            'id': f.id,
            'name': f.name,
            'description': f.description or '',
            'question_count': request.env['forum.post'].sudo().search_count([
                ('forum_id', '=', f.id), ('parent_id', '=', False), ('state', '=', 'active'),
            ]),
        } for f in forums]
        return ok(data=data, meta={'total': len(data)})

    @http.route(API_ROOT + '/forums/<int:forum_id>/questions', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('forum')
    def forum_questions(self, forum_id, **kw):
        domain = [('forum_id', '=', forum_id), ('parent_id', '=', False), ('state', '=', 'active')]
        Post = request.env['forum.post'].sudo()
        limit, offset, page = page_params()
        total = Post.search_count(domain)
        posts = Post.search(domain, limit=limit, offset=offset, order='create_date desc')
        return ok(data=[_question_card(p) for p in posts], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/questions/<int:question_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('forum')
    def question_detail(self, question_id, **kw):
        post = request.env['forum.post'].sudo().browse(question_id)
        if not post.exists() or post.parent_id or post.state != 'active':
            return err('Question not found', 404)
        return ok(data=_question_detail(post))

    @http.route(API_ROOT + '/forums/<int:forum_id>/questions', type='http', auth='user', methods=['POST'], csrf=False)
    @requires_app('forum')
    def ask_question(self, forum_id, **kw):
        from .common import read_body
        forum = request.env['forum.forum'].sudo().browse(forum_id)
        if not forum.exists():
            return err('Forum not found', 404)
        body = read_body()
        title = (body.get('title') or body.get('name') or '').strip()
        content = (body.get('content') or '').strip()
        if not title or not content:
            return err('Title and content are required', 422)
        # Run as the user so forum karma rules apply (don't bypass with sudo).
        try:
            post = request.env['forum.post'].with_user(request.env.user).create({
                'forum_id': forum.id,
                'name': title,
                'content': content,
            })
        except Exception as exc:
            return err(str(exc), 403)
        return ok(data={'question_id': post.id}, status=201)

    @http.route(API_ROOT + '/questions/<int:question_id>/answers', type='http', auth='user', methods=['POST'], csrf=False)
    @requires_app('forum')
    def answer_question(self, question_id, **kw):
        from .common import read_body
        question = request.env['forum.post'].sudo().browse(question_id)
        if not question.exists() or question.parent_id:
            return err('Question not found', 404)
        content = (read_body().get('content') or '').strip()
        if not content:
            return err('Content is required', 422)
        try:
            answer = request.env['forum.post'].with_user(request.env.user).create({
                'forum_id': question.forum_id.id,
                'parent_id': question.id,
                'content': content,
            })
        except Exception as exc:
            return err(str(exc), 403)
        return ok(data={'answer_id': answer.id}, status=201)
