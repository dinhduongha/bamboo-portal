# -*- coding: utf-8 -*-
{
    'name': "Bamboo Public API",
    'summary': "Anonymous JSON API (shop/event/blog/forum/contact/job + portal) "
               "for the Bamboo React public site.",
    'description': """
Publishes a generic, CORS-friendly JSON API the Bamboo React client uses to render
the public/portal surfaces of a standard Odoo website (Shop, Event, Blog, Forum,
Contact, Job) plus a logged-in customer "My Account" area.

All responses use the {success, data, error, meta} envelope. Public reads are
auth='public'; customer self-service is auth='user' (sudo-scoped to the caller's
partner). The website_* modules are SOFT dependencies — each app's routes guard on
module presence at runtime, so this addon installs on any Odoo and only the
installed apps light up (see GET /bamboo/public/v1/meta).
    """,
    'author': "Bamboo",
    'website': "https://github.com/dinhduongha/bamboo-react",
    'category': 'Website',
    'version': '19.0.1.0.0',
    # CORS is handled globally by bamboo_cors (reflects Origin + credentials), so
    # depend on it to guarantee the patch is loaded. website_sale/website_event/…
    # are intentionally NOT hard deps — routes guard on presence at runtime.
    'depends': ['bamboo_cors'],
    'license': 'LGPL-3',
    'data': [],
    'installable': True,
    'application': False,
}
