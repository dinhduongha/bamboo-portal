# -*- coding: utf-8 -*-
"""Courses (website_slides / eLearning) public read endpoints — courses, a
course's lessons, a lesson.

Read-only / anonymous. `slide.channel` = a course, `slide.slide` = a lesson.
Both are filtered to `is_published`. Course covers come from the channel's
`image_512` (image.mixin). Lesson `html_content` is HTML.
"""
from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext

from .common import (
    API_ROOT,
    err,
    image_url,
    ok,
    page_meta,
    page_params,
    requires_app,
)


def _course_card(channel):
    return {
        'id': channel.id,
        'name': channel.name,
        'description': html2plaintext(channel.description_short) if channel.description_short else '',
        'total_slides': channel.total_slides,
        'members_count': channel.members_count,
        'cover_url': image_url('slide.channel', channel.id, 'image_512'),
    }


def _lesson_item(slide):
    return {
        'id': slide.id,
        'name': slide.name,
        'category': slide.slide_category or '',
        'sequence': slide.sequence,
    }


def _course_detail(channel):
    data = _course_card(channel)
    lessons = channel.slide_ids.filtered(lambda s: s.is_published)
    data['description_html'] = channel.description or ''
    data['website_url'] = channel.website_url or ''
    data['lessons'] = [_lesson_item(s) for s in lessons.sorted('sequence')]
    return data


class BambooPublicCourses(http.Controller):

    @http.route(API_ROOT + '/courses', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('course')
    def courses(self, **kw):
        domain = [('is_published', '=', True)]
        Channel = request.env['slide.channel'].sudo()
        limit, offset, page = page_params()
        total = Channel.search_count(domain)
        channels = Channel.search(domain, limit=limit, offset=offset, order='sequence, name')
        return ok(data=[_course_card(c) for c in channels], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/courses/<int:course_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('course')
    def course_detail(self, course_id, **kw):
        channel = request.env['slide.channel'].sudo().browse(course_id)
        if not channel.exists() or not channel.is_published:
            return err('Course not found', 404)
        return ok(data=_course_detail(channel))
