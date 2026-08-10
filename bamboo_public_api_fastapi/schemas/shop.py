"""Shop + cart + checkout payloads — mirrors of the controllers' `_*_dict` builders.

Every model here is the pydantic form of a serializer in
`bamboo_public_api.controllers.{shop,cart,checkout}`; the routers reuse those
functions and validate their output through these, so a drift on either side
fails loudly instead of silently changing the wire format.
"""

from typing import List, Optional

from pydantic import BaseModel


# --- shop ------------------------------------------------------------------
class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None


class ProductCardOut(BaseModel):
    id: int
    name: str
    list_price: float
    currency: str
    description_sale: str = ""
    category_ids: List[int] = []
    image_url: str = ""
    variant_id: int
    variant_count: int = 1


class VariantAttributeOut(BaseModel):
    attribute: str
    value: str


class VariantOut(BaseModel):
    id: int
    name: str
    price: float
    default_code: str = ""
    image_url: str = ""
    attributes: List[VariantAttributeOut] = []


class ProductDetailOut(ProductCardOut):
    description: str = ""
    variants: List[VariantOut] = []


# --- cart ------------------------------------------------------------------
class CartLineOut(BaseModel):
    line_id: int
    product_id: int
    name: str
    qty: float
    price_unit: float
    price_subtotal: float
    image_url: str = ""


class CartOut(BaseModel):
    cart_token: Optional[str] = None
    order_id: int
    state: str
    lines: List[CartLineOut] = []
    amount_untaxed: float = 0.0
    amount_tax: float = 0.0
    amount_total: float = 0.0
    currency: str


class CartAddIn(BaseModel):
    product_id: int
    qty: float = 1.0


class CartQtyIn(BaseModel):
    qty: float


# --- checkout --------------------------------------------------------------
class CheckoutIn(BaseModel):
    street: str = ""
    city: str = ""
    zip: str = ""
    phone: str = ""
    country_code: Optional[str] = None


class CheckoutOut(CartOut):
    name: str
    requires_payment: bool
