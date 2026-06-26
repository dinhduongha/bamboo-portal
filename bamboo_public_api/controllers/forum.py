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
