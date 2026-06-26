# -*- coding: utf-8 -*-
"""Shop (website_sale) public read endpoints — products + categories.

Read-only and anonymous: only `website_published` products are exposed, via
sudo() (portal/public ir.model.access on product.template is minimal on a generic
Odoo, so sudo + an explicit published filter is the safe path). Binary images are
returned as `/web/image/...` URLs, never inlined.
"""
from odoo import http
from odoo.http import request

from .common import API_ROOT, err, image_url, ok, page_meta, page_params, requires_app


def _currency_name():
    return request.env.company.currency_id.name


def _product_card(tmpl):
    """Compact product for list views."""
    return {
        'id': tmpl.id,
        'name': tmpl.name,
        'list_price': tmpl.list_price,
        'currency': _currency_name(),
        'description_sale': tmpl.description_sale or '',
        'category_ids': tmpl.public_categ_ids.ids,
        'image_url': image_url('product.template', tmpl.id),
    }


def _product_detail(tmpl):
    """Full product: variants + their attribute values."""
    data = _product_card(tmpl)
    data['description'] = tmpl.description_ecommerce or tmpl.description_sale or ''
    data['variants'] = [{
        'id': v.id,
        'name': v.display_name,
        'price': v.lst_price,
        'default_code': v.default_code or '',
        'image_url': image_url('product.product', v.id),
        'attributes': [{
            'attribute': ptav.attribute_id.name,
            'value': ptav.name,
        } for ptav in v.product_template_attribute_value_ids],
    } for v in tmpl.product_variant_ids]
    return data


class BambooPublicShop(http.Controller):

    @http.route(API_ROOT + '/shop/categories', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('shop')
    def categories(self, **kw):
        cats = request.env['product.public.category'].sudo().search([])
        data = [{
            'id': c.id,
            'name': c.name,
            'parent_id': c.parent_id.id or None,
        } for c in cats]
        return ok(data=data, meta={'total': len(data)})

    @http.route(API_ROOT + '/shop/products', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('shop')
    def products(self, **kw):
        domain = [('website_published', '=', True)]
        category = request.params.get('category')
        if category:
            try:
                domain.append(('public_categ_ids', 'child_of', int(category)))
            except (TypeError, ValueError):
                return err('Invalid category', 400)
        search = request.params.get('search')
        if search:
            domain.append(('name', 'ilike', search))

        Product = request.env['product.template'].sudo()
        limit, offset, page = page_params()
        total = Product.search_count(domain)
        products = Product.search(domain, limit=limit, offset=offset, order='name')
        return ok(
            data=[_product_card(p) for p in products],
            meta=page_meta(total, limit, page),
        )

    @http.route(API_ROOT + '/shop/products/<int:product_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('shop')
    def product_detail(self, product_id, **kw):
        tmpl = request.env['product.template'].sudo().browse(product_id)
        if not tmpl.exists() or not tmpl.website_published:
            return err('Product not found', 404)
        return ok(data=_product_detail(tmpl))
