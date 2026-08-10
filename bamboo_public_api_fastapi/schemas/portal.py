"""Portal (My Account) + payment payloads — mirrors of the controllers' builders."""

import datetime as dt
from typing import List, Optional, Union

from pydantic import BaseModel


# --- payment ---------------------------------------------------------------
class ProviderOut(BaseModel):
    id: int
    name: str
    code: str
    state: str
    image_url: str = ""
    demo: bool = False


class TransactionOut(BaseModel):
    reference: str
    state: str
    amount: float
    currency: str
    provider_code: str
    demo: bool = False


class TransactionPayloadOut(TransactionOut):
    redirect_form_html: str = ""


class TransactionIn(BaseModel):
    provider_id: Optional[int] = None
    kind: str = "order"
    ref_id: Optional[int] = None


class DemoOutcomeIn(BaseModel):
    reference: str
    outcome: str = "done"


class PayIn(BaseModel):
    provider_id: Optional[int] = None


# --- orders / subscriptions ------------------------------------------------
class OrderCardOut(BaseModel):
    id: int
    name: str
    date: Optional[Union[dt.datetime, dt.date]] = None
    state: str
    amount_total: float
    amount_untaxed: float
    amount_tax: float
    currency: str
    invoice_status: Optional[str] = None


class OrderLineOut(BaseModel):
    id: int
    name: str = ""
    product_id: Optional[int] = None
    qty: float
    price_unit: float
    price_subtotal: float


class PartnerRefOut(BaseModel):
    id: int
    name: Optional[str] = None


class OrderDetailOut(OrderCardOut):
    lines: List[OrderLineOut] = []
    partner: PartnerRefOut


class ReorderOut(BaseModel):
    cart_token: Optional[str] = None
    order_id: int


# --- invoices --------------------------------------------------------------
class InvoiceCardOut(BaseModel):
    id: int
    name: Optional[str] = None
    date: Optional[dt.date] = None
    due_date: Optional[dt.date] = None
    state: str
    payment_state: Optional[str] = None
    amount_total: float
    amount_residual: float
    currency: str
    move_type: str


class InvoiceLineOut(BaseModel):
    id: int
    name: Optional[str] = None
    qty: float
    price_unit: float
    price_subtotal: float


class InvoiceDetailOut(InvoiceCardOut):
    lines: List[InvoiceLineOut] = []


# --- profile / addresses ---------------------------------------------------
class PartnerOut(BaseModel):
    id: int
    name: Optional[str] = None
    email: str = ""
    phone: str = ""
    street: str = ""
    street2: str = ""
    city: str = ""
    zip: str = ""
    country_code: str = ""
    country_id: Union[int, bool] = False
    type: str


class PartnerIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    country_code: Optional[str] = None
    type: Optional[str] = None


class DeletedOut(BaseModel):
    deleted: int
