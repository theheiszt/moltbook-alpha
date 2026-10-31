"""
Moltbook Alpha — Molt Alpha DEMS NFT Collection Routes.
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app_state import (
    storage,
    witness_manager,
    load_payment_config,
    get_client_ip,
)
from payment_verifier import SolanaPaymentVerifier, VerificationError, RPCError

router = APIRouter(prefix="/v1/nfts", tags=["NFTs"])


def create_nfts_router() -> APIRouter:
    return router


class CreateNftOrderInput(BaseModel):
    nft_id: str
    buyer_wallet: str
    asset: str = "SOL"


class ClaimNftOrderInput(BaseModel):
    order_id: str
    transaction_signature: str


@router.get("/catalog")
def get_nfts_catalog():
    """
    Returns the complete Molt Alpha DEMS 6-piece pixel art NFT collection catalog,
    including rarities, traits, SOL/USDC prices, remaining edition supply, and bundled API credit grants.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    return col.list_catalog()


@router.get("/assets/{filename}")
def get_nft_asset_image(filename: str):
    """
    Serves the 2x Nearest-Neighbor upscaled PNG pixel artwork files for Molt Alpha DEMS.
    """
    from nft_collection import NFT_ASSETS_DIR

    clean_name = Path(filename).name
    target = NFT_ASSETS_DIR / clean_name
    if not target.is_file() or target.suffix.lower() not in (".png", ".json"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NFT asset '{clean_name}' not found.",
        )
    media = "image/png" if target.suffix.lower() == ".png" else "application/json"
    return FileResponse(target, media_type=media)


@router.get("/metadata/{nft_id}.json")
def get_nft_metaplex_metadata(nft_id: str, edition: Optional[int] = None):
    """
    Returns Metaplex Token Metadata standard JSON for wallet and marketplace indexing.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    try:
        return col.build_metaplex_metadata(nft_id, edition_number=edition)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post("/order", status_code=status.HTTP_201_CREATED)
def create_nft_lazy_mint_order(payload: CreateNftOrderInput, request: Request):
    """
    Creates a bound Lazy-Mint Order for one of the 6 Molt Alpha DEMS pixel artworks.
    Zero upfront rent is spent by the seller; the buyer pays the bound invoice on Solana
    to mint their edition and receive bundled Moltbook Alpha API credits.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    try:
        order = col.create_lazy_mint_order(
            nft_id=payload.nft_id,
            buyer_wallet=payload.buyer_wallet,
            asset=payload.asset,
            storage=storage,
        )
        storage.log_audit_event(
            "nft_order_created",
            f"Created lazy-mint order {order['order_id']} for {order['nft_id']} ({order['buyer_wallet']})",
            ip_address=get_client_ip(request),
        )
        return order
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/claim")
def claim_nft_lazy_mint_order(payload: ClaimNftOrderInput, request: Request):
    """
    Verifies on-chain Solana payment for a Lazy-Mint NFT Order, assigns the sequential
    edition number (#1..max_supply), mints the bundled Moltbook Alpha API key + credit lot,
    and returns an Ed25519-signed ownership & provenance witness certificate.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    ledger = col._load_ledger()
    order = ledger.get("orders", {}).get(payload.order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NFT order '{payload.order_id}' not found.",
        )

    if order.get("status") == "MINTED":
        return order["mint_receipt"]

    cfg = load_payment_config()
    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 3600),
        require_consensus=False,
    )
    try:
        verified = verifier.verify_payment(
            payload.transaction_signature.strip(),
            requested_tier=order["bundled_tier"],
            expected_payer=order["buyer_wallet"],
            expected_reference=order["memo_reference"],
        )
    except (VerificationError, RPCError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"On-chain payment verification failed for NFT order '{payload.order_id}': {e!s}",
        ) from e

    try:
        receipt = col.claim_lazy_mint_order(
            order_id=payload.order_id,
            tx_signature=verified.tx_signature,
            verified_payment=verified,
            storage=storage,
            witness_manager=witness_manager,
        )
        storage.log_audit_event(
            "nft_edition_minted",
            f"Minted {receipt['nft_name']} to {receipt['owner_wallet']} via tx {verified.tx_signature[:16]}...",
            ip_address=get_client_ip(request),
        )
        return receipt
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
