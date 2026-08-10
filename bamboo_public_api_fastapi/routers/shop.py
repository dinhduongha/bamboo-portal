"""Shop (website_sale) — categories + published products.

Read-only and anonymous, like the controller: only `website_published` products,
read through `sudo()` because a generic Odoo gives the public user almost no
`ir.model.access` on `product.template`. The serializers are the controller's own
(`_product_card` / `_product_detail`) so the two modes cannot drift.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from odoo.addons.bamboo_public_api.controllers.shop import (
    _product_card,
    _product_detail,
)

from ..schemas.envelope import ResponseEnvelope
from ..schemas.shop import CategoryOut, ProductCardOut, ProductDetailOut
from ._common import Paging, PublicEnv, meta_page, require_app

shop_router = APIRouter(tags=["Shop"], dependencies=[Depends(require_app("shop"))])


@shop_router.get("/shop/categories", response_model=ResponseEnvelope[List[CategoryOut]])
async def categories(env: PublicEnv):
    cats = env["product.public.category"].sudo().search([])
    data = [
        CategoryOut(id=c.id, name=c.name, parent_id=c.parent_id.id or None) for c in cats
    ]
    return ResponseEnvelope(data=data, meta={"total": len(data)})


@shop_router.get("/shop/products", response_model=ResponseEnvelope[List[ProductCardOut]])
async def products(
    env: PublicEnv,
    paging: Paging,
    category: Annotated[Optional[int], Query(description="public category id")] = None,
    search: Annotated[Optional[str], Query()] = None,
):
    """Published products, paginated. `category` matches the whole subtree.

    Divergence from the controller: a non-numeric `category` is rejected by
    FastAPI with 422 instead of the controller's hand-rolled 400.
    """
    domain = [("website_published", "=", True)]
    if category is not None:
        domain.append(("public_categ_ids", "child_of", category))
    if search:
        domain.append(("name", "ilike", search))

    Product = env["product.template"].sudo()
    total = Product.search_count(domain)
    records = Product.search(
        domain, limit=paging.limit, offset=paging.offset, order="name"
    )
    return ResponseEnvelope(
        data=[_product_card(p) for p in records], meta=meta_page(total, paging)
    )


@shop_router.get(
    "/shop/products/{product_id}", response_model=ResponseEnvelope[ProductDetailOut]
)
async def product_detail(product_id: int, env: PublicEnv):
    tmpl = env["product.template"].sudo().browse(product_id)
    if not tmpl.exists() or not tmpl.website_published:
        raise HTTPException(status_code=404, detail="Product not found")
    return ResponseEnvelope(data=_product_detail(tmpl))
