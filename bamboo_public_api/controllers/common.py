# -*- coding: utf-8 -*-
"""Shared helpers for the Bamboo public API controllers.

Every endpoint returns the {success, data, error, meta} envelope (same shape as
addons-tsc/tsc_crm_portal/controllers/api.py). CORS is handled globally by
bamboo_cors, so controllers here NEVER set CORS headers or handle OPTIONS.
"""
import functools
import json
import os

from odoo import release
from odoo.http import request
from odoo.tools import config as odoo_config

API_ROOT = '/bamboo/public/v1'
# Root the optional FastAPI implementation mounts under (v19 only, bridge module
# bamboo_public_api_fastapi). Distinct from API_ROOT so it never collides with the
# controller routes — the toggle just decides which one the client calls.
FASTAPI_ROOT = '/bamboo/fastapi/v1'

# app key -> the Odoo module that must be installed for that app's routes to work.
# Drives GET /meta and the per-route presence guard. website_* are soft deps.
APP_MODULES = {
    'shop': 'website_sale',
    'event': 'website_event',
    'blog': 'website_blog',
    'forum': 'website_forum',
    'job': 'website_hr_recruitment',
    'contact': 'website_crm',
    'course': 'website_slides',
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


def _config(key, default=None):
    """Resolve a setting: odoo.conf → ir.config_parameter → env var → default.
    (Same resolver shape as abp_auth/laoid_auth.) The env tier reads KEY uppercased."""
    value = odoo_config.get(key)
    if value not in (None, ''):
        return value
    try:
        if request and request.env:
            param = request.env['ir.config_parameter'].sudo().get_param(key)
            if param not in (None, ''):
                return param
    except Exception:
        pass
    env_value = os.environ.get(key.upper())
    if env_value not in (None, ''):
        return env_value
    return default


def fastapi_mode_active():
    """True when the API should be served by FastAPI instead of the controllers.
    Requires: config `bamboo_public_api_mode == 'fastapi'` AND Odoo >= 19 AND the
    `fastapi` module installed. Defaults to controller mode (fail-safe)."""
    if release.version_info[0] < 19:
        return False
    if _config('bamboo_public_api_mode', 'controller') != 'fastapi':
        return False
    return module_installed('fastapi')


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


def read_body():
    """Parse a POST body as dict — JSON when the content-type says so, else the
    form params. Public POST endpoints (contact, job apply) accept either."""
    ctype = request.httprequest.content_type or ''
    if 'application/json' in ctype:
        try:
            return json.loads(request.httprequest.get_data() or b'{}')
        except (ValueError, TypeError):
            return {}
    return dict(request.params)


def cover_image_url(cover_properties):
    """Extract the `background-image: url('…')` from a record's `cover_properties`
    JSON (event.event / blog.post covers). Returns the relative path or ''."""
    if not cover_properties:
        return ''
    try:
        bg = json.loads(cover_properties).get('background-image', '')
    except (ValueError, TypeError):
        return ''
    # bg looks like: url('/website_blog/static/src/img/cover_7.jpg')
    start = bg.find("url(")
    if start == -1:
        return ''
    inner = bg[start + 4:bg.find(")", start)].strip("'\" ")
    return inner
