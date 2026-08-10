"""Payment — pay a cart (checkout) or an outstanding invoice online.

The transaction lifecycle lives in the controller module (`start_transaction`,
`_tx_payload`, `_settle_on_done`, `_owns_tx`): it is provider-framework logic, not
transport, so both modes call the same functions.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from odoo.addons.bamboo_public_api.controllers.payment import (
    _enabled_providers,
    _owns_tx,
    _provider_dict,
    _settle_on_done,
    _tx_dict,
    _tx_payload,
    start_transaction,
)

from ..schemas.envelope import ResponseEnvelope
from ..schemas.portal import (
    DemoOutcomeIn,
    ProviderOut,
    TransactionIn,
    TransactionOut,
    TransactionPayloadOut,
)
from ._common import AuthEnv, PublicEnv, require_app

payment_router = APIRouter(
    tags=["Payment"], dependencies=[Depends(require_app("payment"))]
)


@payment_router.get(
    "/payment/providers", response_model=ResponseEnvelope[List[ProviderOut]]
)
async def providers(env: PublicEnv):
    """The payment providers a customer may choose (enabled or test)."""
    return ResponseEnvelope(data=[_provider_dict(p) for p in _enabled_providers()])


@payment_router.post(
    "/payment/transaction",
    response_model=ResponseEnvelope[TransactionPayloadOut],
    status_code=201,
)
async def create_transaction(body: TransactionIn, env: AuthEnv):
    """Start a transaction for the cart (`kind=order`) or an invoice
    (`kind=invoice`, `ref_id=<move id>`)."""
    tx, error = start_transaction(body.provider_id, body.kind or "order", body.ref_id)
    if error:
        raise HTTPException(status_code=error[1], detail=error[0])
    return ResponseEnvelope(data=_tx_payload(tx))


@payment_router.post(
    "/payment/demo", response_model=ResponseEnvelope[TransactionOut]
)
async def demo_process(body: DemoOutcomeIn, env: AuthEnv):
    """Simulate a Demo-provider outcome: `{reference, outcome}` with outcome
    done|cancel|error. The reference is in the body, not the path, because invoice
    references contain slashes."""
    tx = (
        env["payment.transaction"]
        .sudo()
        .search([("reference", "=", body.reference)], limit=1)
    )
    if not _owns_tx(tx) or tx.provider_code != "demo":
        raise HTTPException(status_code=404, detail="Transaction not found")
    outcome = body.outcome or "done"
    if outcome == "done":
        tx.action_demo_set_done()
    elif outcome == "cancel":
        tx.action_demo_set_canceled()
    else:
        tx.action_demo_set_error()
    _settle_on_done(tx)
    return ResponseEnvelope(data=_tx_dict(tx))


@payment_router.get(
    "/payment/status", response_model=ResponseEnvelope[TransactionOut]
)
async def transaction_status(
    env: AuthEnv, reference: Optional[str] = Query(default=None)
):
    """Poll a transaction by `?reference=`, settling a linked order if it just
    finished out-of-band through a redirect provider."""
    tx = (
        env["payment.transaction"]
        .sudo()
        .search([("reference", "=", reference)], limit=1)
    )
    if not _owns_tx(tx):
        raise HTTPException(status_code=404, detail="Transaction not found")
    _settle_on_done(tx)
    return ResponseEnvelope(data=_tx_dict(tx))
