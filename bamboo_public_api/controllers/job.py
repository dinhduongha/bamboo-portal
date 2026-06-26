# -*- coding: utf-8 -*-
"""Job (website_hr_recruitment) public endpoints — list, detail, public apply.

Read is anonymous (published jobs only). Apply is public (auth='public'): it
creates an `hr.applicant` for the job and attaches an optional CV. Cover letter
goes to the applicant's chatter (no description field on hr.applicant in 19).
"""
import base64

from odoo import http
from odoo.http import request

from .common import API_ROOT, err, ok, page_meta, page_params, read_body, requires_app


def _job_card(job):
    return {
        'id': job.id,
        'name': job.name,
        'department': job.department_id.name if job.department_id else '',
        'location': job.address_id.city or (job.address_id.display_name if job.address_id else ''),
        'no_of_recruitment': job.no_of_recruitment,
    }


def _job_detail(job):
    data = _job_card(job)
    data['description'] = job.description or ''
    data['job_details'] = job.job_details or ''
    data['website_url'] = job.website_url or ''
    return data


class BambooPublicJob(http.Controller):

    @http.route(API_ROOT + '/jobs', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('job')
    def jobs(self, **kw):
        domain = [('website_published', '=', True)]
        Job = request.env['hr.job'].sudo()
        limit, offset, page = page_params()
        total = Job.search_count(domain)
        jobs = Job.search(domain, limit=limit, offset=offset, order='name')
        return ok(data=[_job_card(j) for j in jobs], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/jobs/<int:job_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('job')
    def job_detail(self, job_id, **kw):
        job = request.env['hr.job'].sudo().browse(job_id)
        if not job.exists() or not job.website_published:
            return err('Job not found', 404)
        return ok(data=_job_detail(job))

    @http.route(API_ROOT + '/jobs/<int:job_id>/apply', type='http', auth='public', methods=['POST'], csrf=False)
    @requires_app('job')
    def job_apply(self, job_id, **kw):
        job = request.env['hr.job'].sudo().browse(job_id)
        if not job.exists() or not job.website_published:
            return err('Job not found', 404)
        body = read_body()
        name = (body.get('name') or '').strip()
        email = (body.get('email') or '').strip()
        if not name or not email:
            return err('Name and email are required', 422)

        applicant = request.env['hr.applicant'].sudo().create({
            'partner_name': name,
            'email_from': email,
            'partner_phone': body.get('phone') or '',
            'job_id': job.id,
            'department_id': job.department_id.id or False,
        })
        cover = body.get('cover_letter') or body.get('message')
        if cover:
            applicant.message_post(body=cover)

        # Optional CV upload (multipart field `file`).
        upload = request.httprequest.files.get('file')
        if upload:
            request.env['ir.attachment'].sudo().create({
                'name': upload.filename,
                'datas': base64.b64encode(upload.read()),
                'res_model': 'hr.applicant',
                'res_id': applicant.id,
            })
        return ok(data={'applicant_id': applicant.id}, status=201)
