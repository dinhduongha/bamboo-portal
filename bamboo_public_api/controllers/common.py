# -*- coding: utf-8 -*-
"""Shared helpers for the Bamboo public API controllers.

Every endpoint returns the {success, data, error, meta} envelope (same shape as
addons-tsc/tsc_crm_portal/controllers/api.py). CORS is handled globally by
bamboo_cors, so controllers here NEVER set CORS headers or handle OPTIONS.
"""
import functools
import json

from odoo.http import request

API_ROOT = '/bamboo/public/v1'

# app key -> the Odoo module that must be installed for that app's routes to work.
# Drives GET /meta and the per-route presence guard. website_* are soft deps.
APP_MODULES = {
    'shop': 'website_sale',
    'event': 'website_event',
    'blog': 'website_blog',
    'forum': 'website_forum',
    'job': 'website_hr_recruitment',
    'contact': 'website_crm',
    'payment': 'payment',
}


def _resp(payload, status=200):
    return request.make_response(
        json.dumps(payload, default=str),
        headers=[('Content-Type', 'application/json')],
        status=status,
    )


def ok(data=None, meta=None, status=200):
    return _resp({'success': True, 'data': data, 'error': None, 'meta': meta or {}}, status)


def err(message, status=400):
    return _resp({'success': False, 'data': None, 'error': message, 'meta': {}}, status)


def module_installed(name):
    """True if an Odoo module is installed (used to soft-guard per-app routes)."""
    return bool(request.env['ir.module.module'].sudo().search_count([
        ('name', '=', name),
        ('state', '=', 'installed'),
    ]))


def available_apps():
    """Map of app key -> bool(installed) for GET /meta and UI tab gating."""
    return {app: module_installed(mod) for app, mod in APP_MODULES.items()}


def requires_app(app):
    """Decorator: 404 the route (clear envelope) when the app's module is absent,
    so the addon stays installable on any Odoo and missing apps degrade cleanly."""
    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not module_installed(APP_MODULES[app]):
                return err("App '%s' is not available on this server" % app, 404)
            return func(*args, **kwargs)
        return wrapper
    return deco


def page_params(default_limit=20, max_limit=100):
    """Read page/limit from the query string → (limit, offset, page)."""
    try:
        page = max(int(request.params.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(request.params.get('limit', default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    limit = max(1, min(limit, max_limit))
    return limit, (page - 1) * limit, page


def page_meta(total, limit, page):
    return {
        'page': page,
        'limit': limit,
        'total': total,
        'pages': -(-total // limit) if limit else 0,
    }


def image_url(model, rec_id, field='image_512'):
    """Public image ref (binary stays out of JSON; the browser fetches /web/image)."""
    return '/web/image/%s/%s/%s' % (model, rec_id, field)
