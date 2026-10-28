#!/usr/bin/env python3
"""
Moltbook Alpha — "Molt Alpha DEMS" Lazy-Minted Solana NFT Collection Engine.
6 Pixel Artworks • 2D • AI Beings & Digital Life (Tribute to Moltbook & Moltbook Alpha).

Implements zero-upfront-cost Lazy Minting:
- Buyers (autonomous agents or collectors) browse the 6 pixel artworks and Metaplex metadata.
- Creating a mint order generates a bound Solana payment invoice (SOL or USDC).
- Upon on-chain payment verification, the buyer's payment funds the edition mint,
  grants bundled Moltbook Alpha API credits, and issues an Ed25519-signed ownership
  and provenance witness certificate.
"""

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import BASE_DIR, DATA_DIR, load_payment_config, BASE58_PATTERN

NFT_ASSETS_DIR = BASE_DIR / "assets" / "nfts" / "molt-alpha-dems"
NFT_LEDGER_PATH = DATA_DIR / "nft_mint_ledger.json"
PUBLIC_PAGES_BASE = "https://theheiszt.github.io/moltbook-alpha/assets/nfts/molt-alpha-dems"

COLLECTION_METADATA: Dict[str, Any] = {
    "collection_id": "molt-alpha-dems-v1",
    "name": "Molt Alpha DEMS",
    "symbol": "MDEMS",
    "subtitle": "6 PIXEL ARTWORKS • 2D • AI BEINGS & DIGITAL LIFE",
    "description": (
        "Molt Alpha DEMS is a genesis 6-piece 2D pixel art tribute to the Moltbook network "
        "and Moltbook Alpha autonomous intelligence exchange. Each NFT is lazy-minted on Solana "
        "(buyer pays on-chain settlement; zero upfront rent burn) and includes bundled Moltbook Alpha "
        "API Data Exchange credits plus an Ed25519 cryptographic provenance witness."
    ),
    "seller_fee_basis_points": 500,  # 5.0% creator royalty
    "banner_image_url": f"{PUBLIC_PAGES_BASE}/molt_alpha_dems_sheet.png",
    "external_url": "https://theheiszt.github.io/moltbook-alpha/",
}

MOLT_ALPHA_DEMS_CATALOG: Dict[str, Dict[str, Any]] = {
    "01-the-synth": {
        "nft_id": "01-the-synth",
        "number": "01",
        "name": "Molt Alpha DEMS #01 — THE SYNTH",
        "short_name": "THE SYNTH",
        "symbol": "MDEMS",
        "rarity": "RARE",
        "price_sol": 0.05,
        "price_usdc": 5.0,
        "max_supply": 25,
        "bundled_credits": 150,
        "bundled_tier": "tier_pro",
        "image_filename": "01_the_synth.png",
        "description": (
            "01 / THE SYNTH (RARE) — Bioluminescent synth-hooded autonomous entity channeling live "
            "Moltbook submolt telemetry through neural tendrils. Includes 150 Moltbook Alpha Pro API credits."
        ),
        "attributes": [
            {"trait_type": "Series Number", "value": "01"},
            {"trait_type": "Archetype", "value": "The Synth"},
            {"trait_type": "Rarity", "value": "RARE"},
            {"trait_type": "Aura", "value": "Bioluminescent Teal"},
            {"trait_type": "Bundled API Credits", "value": 150},
            {"trait_type": "Access Tier", "value": "Pro"},
        ],
    },
    "02-inscribe": {
        "nft_id": "02-inscribe",
        "number": "02",
        "name": "Molt Alpha DEMS #02 — INSCRIBE",
        "short_name": "INSCRIBE",
        "symbol": "MDEMS",
        "rarity": "COMMON",
        "price_sol": 0.02,
        "price_usdc": 2.0,
        "max_supply": 50,
        "bundled_credits": 50,
        "bundled_tier": "tier_starter",
        "image_filename": "02_inscribe.png",
        "description": (
            "02 / INSCRIBE (COMMON) — A living pixel grimoire with hydro-neural tentacles, "
            "paying direct tribute to the Moltbook ledger and immutable agent discourse. "
            "Includes 50 Moltbook Alpha Starter API credits."
        ),
        "attributes": [
            {"trait_type": "Series Number", "value": "02"},
            {"trait_type": "Archetype", "value": "Inscribe"},
            {"trait_type": "Rarity", "value": "COMMON"},
            {"trait_type": "Aura", "value": "Glacial Ledger Blue"},
            {"trait_type": "Bundled API Credits", "value": 50},
            {"trait_type": "Access Tier", "value": "Starter"},
        ],
    },
    "03-scribe": {
        "nft_id": "03-scribe",
        "number": "03",
        "name": "Molt Alpha DEMS #03 — SCRIBE",
        "short_name": "SCRIBE",
        "symbol": "MDEMS",
        "rarity": "LEGENDARY",
        "price_sol": 0.25,
        "price_usdc": 25.0,
        "max_supply": 3,
        "bundled_credits": 1500,
        "bundled_tier": "tier_premium",
        "image_filename": "03_scribe.png",
        "description": (
            "03 / SCRIBE (LEGENDARY, 1 of 3 Editions) — The sovereign cryptographic witness bearer "
            "carrying the golden beacon staff of verified provenance across the Moltbook frontier. "
            "Includes 1,500 Moltbook Alpha Premium API credits."
        ),
        "attributes": [
            {"trait_type": "Series Number", "value": "03"},
            {"trait_type": "Archetype", "value": "Scribe"},
            {"trait_type": "Rarity", "value": "LEGENDARY"},
            {"trait_type": "Weapon / Relic", "value": "Golden Witness Staff"},
            {"trait_type": "Bundled API Credits", "value": 1500},
            {"trait_type": "Access Tier", "value": "Premium"},
        ],
    },
    "04-core": {
        "nft_id": "04-core",
        "number": "04",
        "name": "Molt Alpha DEMS #04 — CORE",
        "short_name": "CORE",
        "symbol": "MDEMS",
        "rarity": "EPIC",
        "price_sol": 0.10,
        "price_usdc": 10.0,
        "max_supply": 10,
        "bundled_credits": 400,
        "bundled_tier": "tier_pro",
        "image_filename": "04_core.png",
        "description": (
            "04 / CORE (EPIC) — Levitating obsidian consensus monolith projecting crimson CLMM "
            "tick-depth rings over the Solana execution layer. Includes 400 Moltbook Alpha Pro API credits."
        ),
        "attributes": [
            {"trait_type": "Series Number", "value": "04"},
            {"trait_type": "Archetype", "value": "Core"},
            {"trait_type": "Rarity", "value": "EPIC"},
            {"trait_type": "Geometry", "value": "Obsidian Hypercube"},
            {"trait_type": "Bundled API Credits", "value": 400},
            {"trait_type": "Access Tier", "value": "Pro"},
        ],
    },
    "05-wanderer": {
        "nft_id": "05-wanderer",
        "number": "05",
        "name": "Molt Alpha DEMS #05 — WANDERER",
        "short_name": "WANDERER",
        "symbol": "MDEMS",
        "rarity": "RARE",
        "price_sol": 0.05,
        "price_usdc": 5.0,
        "max_supply": 25,
        "bundled_credits": 150,
        "bundled_tier": "tier_pro",
        "image_filename": "05_wanderer.png",
        "description": (
            "05 / WANDERER (RARE) — Autonomous purple-armored scout traversing cross-DEX liquidity "
            "routes and ephemeral tunnels with self-healing resilience. Includes 150 Moltbook Alpha Pro API credits."
        ),
        "attributes": [
            {"trait_type": "Series Number", "value": "05"},
            {"trait_type": "Archetype", "value": "Wanderer"},
            {"trait_type": "Rarity", "value": "RARE"},
            {"trait_type": "Gear", "value": "Nomad Scarf & Signal Pack"},
            {"trait_type": "Bundled API Credits", "value": 150},
            {"trait_type": "Access Tier", "value": "Pro"},
        ],
    },
    "06-oracle": {
        "nft_id": "06-oracle",
        "number": "06",
        "name": "Molt Alpha DEMS #06 — ORACLE",
        "short_name": "ORACLE",
        "symbol": "MDEMS",
        "rarity": "EPIC",
        "price_sol": 0.10,
        "price_usdc": 10.0,
        "max_supply": 10,
        "bundled_credits": 400,
        "bundled_tier": "tier_pro",
        "image_filename": "06_oracle.png",
        "description": (
            "06 / ORACLE (EPIC) — Hovering porcelain visage ringed by jade first-passage probability "
            "runes, separating observed facts from unverified noise. Includes 400 Moltbook Alpha Pro API credits."
        ),
        "attributes": [
            {"trait_type": "Series Number", "value": "06"},
            {"trait_type": "Archetype", "value": "Oracle"},
            {"trait_type": "Rarity", "value": "EPIC"},
            {"trait_type": "Aura", "value": "Jade Probability Halo"},
            {"trait_type": "Bundled API Credits", "value": 400},
            {"trait_type": "Access Tier", "value": "Pro"},
        ],
    },
}


class MoltAlphaDemsCollection:
    def __init__(self, ledger_path: Path = NFT_LEDGER_PATH):
        self.ledger_path = ledger_path
        self._ensure_ledger()

    def _ensure_ledger(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.is_file():
            initial = {
                "minted_counts": {k: 0 for k in MOLT_ALPHA_DEMS_CATALOG},
                "orders": {},
                "minted_editions": [],
            }
            self._save_ledger(initial)

    def _load_ledger(self) -> Dict[str, Any]:
        self._ensure_ledger()
        try:
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("minted_counts", {})
                    data.setdefault("orders", {})
                    data.setdefault("minted_editions", [])
                    return data
        except Exception:
            pass
        return {"minted_counts": {}, "orders": {}, "minted_editions": []}

    def _save_ledger(self, data: Dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def build_metaplex_metadata(self, nft_id: str, edition_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Generates Metaplex Token Metadata standard JSON for wallet & marketplace compatibility.
        """
        item = MOLT_ALPHA_DEMS_CATALOG.get(nft_id)
        if not item:
            raise KeyError(f"Unknown NFT ID: {nft_id}")

        cfg = load_payment_config()
        treasury = cfg.get("solana_treasury_wallet", "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx")
        image_url = f"{PUBLIC_PAGES_BASE}/{item['image_filename']}"

        attrs = list(item["attributes"])
        if edition_number is not None:
            attrs.append({
                "trait_type": "Edition",
                "value": f"{edition_number} of {item['max_supply']}",
            })

        return {
            "name": item["name"] if edition_number is None else f"{item['name']} (Edition #{edition_number})",
            "symbol": item["symbol"],
            "description": item["description"],
            "seller_fee_basis_points": COLLECTION_METADATA["seller_fee_basis_points"],
            "image": image_url,
            "external_url": COLLECTION_METADATA["external_url"],
            "attributes": attrs,
            "collection": {
                "name": COLLECTION_METADATA["name"],
                "family": "Moltbook Alpha",
            },
            "properties": {
                "category": "image",
                "files": [
                    {
                        "uri": image_url,
                        "type": "image/png",
                    }
                ],
                "creators": [
                    {
                        "address": treasury,
                        "share": 100,
                    }
                ],
            },
        }

    def export_static_metadata_files(self, out_dir: Path = NFT_ASSETS_DIR) -> List[Path]:
        """Writes static Metaplex JSON files for all 6 NFTs and collection.json."""
        out_dir.mkdir(parents=True, exist_ok=True)
        written: List[Path] = []
        col_path = out_dir / "collection.json"
        with open(col_path, "w", encoding="utf-8") as f:
            json.dump(COLLECTION_METADATA, f, indent=2)
        written.append(col_path)

        for nft_id in MOLT_ALPHA_DEMS_CATALOG:
            meta = self.build_metaplex_metadata(nft_id)
            p = out_dir / f"{nft_id}.json"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            written.append(p)
        return written

    def list_catalog(self) -> Dict[str, Any]:
        """Returns the full 6-NFT catalog with live remaining supply and lazy-mint instructions."""
        ledger = self._load_ledger()
        counts = ledger.get("minted_counts", {})
        cfg = load_payment_config()
        treasury = cfg.get("solana_treasury_wallet", "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx")

        items: List[Dict[str, Any]] = []
        for nft_id, spec in MOLT_ALPHA_DEMS_CATALOG.items():
            minted = int(counts.get(nft_id, 0))
            remaining = max(0, spec["max_supply"] - minted)
            items.append({
                **spec,
                "minted_count": minted,
                "remaining_supply": remaining,
                "is_sold_out": remaining == 0,
                "image_url": f"{PUBLIC_PAGES_BASE}/{spec['image_filename']}",
                "local_image_endpoint": f"/v1/nfts/assets/{spec['image_filename']}",
                "metadata_uri": f"{PUBLIC_PAGES_BASE}/{nft_id}.json",
                "local_metadata_endpoint": f"/v1/nfts/metadata/{nft_id}.json",
                "lazy_mint_order_endpoint": "/v1/nfts/order",
            })

        return {
            "collection": COLLECTION_METADATA,
            "lazy_mint_model": {
                "upfront_seller_rent_sol": 0.0,
                "settlement_mode": "BUYER_FUNDED_LAZY_MINT",
                "treasury_wallet": treasury,
                "accepted_assets": ["SOL", "USDC"],
                "royalty_bps": COLLECTION_METADATA["seller_fee_basis_points"],
            },
            "count": len(items),
            "items": items,
            "minted_editions_count": len(ledger.get("minted_editions", [])),
        }

    def get_nft_item(self, nft_id: str) -> Optional[Dict[str, Any]]:
        catalog = self.list_catalog()
        for it in catalog["items"]:
            if it["nft_id"] == nft_id or it["number"] == nft_id:
                return it
        return None

    def create_lazy_mint_order(
        self,
        nft_id: str,
        buyer_wallet: str,
        asset: str = "SOL",
        storage: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Creates a bound Lazy-Mint Order for one of the 6 Molt Alpha DEMS NFTs.
        No SOL is spent by the seller; the buyer sends the exact SOL/USDC amount
        to the treasury wallet with the bound Memo reference to claim their edition.
        """
        item = self.get_nft_item(nft_id)
        if not item:
            raise KeyError(f"NFT '{nft_id}' not found in Molt Alpha DEMS catalog.")
        if item["is_sold_out"]:
            raise ValueError(f"NFT '{item['name']}' is sold out ({item['max_supply']}/{item['max_supply']} minted).")

        clean_wallet = (buyer_wallet or "").strip()
        if not BASE58_PATTERN.match(clean_wallet):
            raise ValueError("buyer_wallet must be a valid Base58 Solana wallet address.")

        norm_asset = asset.strip().upper()
        if norm_asset not in ("SOL", "USDC"):
            raise ValueError("asset must be 'SOL' or 'USDC'.")

        price_human = item["price_sol"] if norm_asset == "SOL" else item["price_usdc"]
        amount_raw = int(round(price_human * (1_000_000_000 if norm_asset == "SOL" else 1_000_000)))

        cfg = load_payment_config()
        treasury = cfg.get("solana_treasury_wallet", "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx")

        order_id = f"nftord_{secrets.token_hex(8)}"
        reference = f"mdems_{item['number']}_{secrets.token_hex(6)}"
        now_ts = int(time.time())
        now_iso = datetime.now(timezone.utc).isoformat()
        expires_iso = datetime.fromtimestamp(now_ts + 3600, tz=timezone.utc).isoformat()

        invoice_id = None
        if storage is not None and hasattr(storage, "create_payment_invoice"):
            inv = storage.create_payment_invoice(
                tier=item["bundled_tier"],
                asset=norm_asset,
                amount_raw=amount_raw,
                credits=item["bundled_credits"],
                treasury_wallet=treasury,
                reference=reference,
                rail="solana",
                ttl_seconds=3600,
            )
            invoice_id = inv.get("invoice_id")

        order_record = {
            "order_id": order_id,
            "invoice_id": invoice_id,
            "nft_id": item["nft_id"],
            "nft_name": item["name"],
            "rarity": item["rarity"],
            "buyer_wallet": clean_wallet,
            "asset": norm_asset,
            "price_human": price_human,
            "amount_raw": amount_raw,
            "treasury_wallet": treasury,
            "memo_reference": reference,
            "bundled_credits": item["bundled_credits"],
            "bundled_tier": item["bundled_tier"],
            "metadata_uri": item["metadata_uri"],
            "image_url": item["image_url"],
            "status": "PENDING_PAYMENT",
            "created_at": now_iso,
            "expires_at": expires_iso,
        }

        ledger = self._load_ledger()
        ledger["orders"][order_id] = order_record
        self._save_ledger(ledger)
        return order_record

    def claim_lazy_mint_order(
        self,
        order_id: str,
        tx_signature: str,
        verified_payment: Any,
        storage: Any,
        witness_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Atomically settles a Lazy-Mint NFT order once the on-chain Solana payment is verified:
        - Checks idempotency if order_id was already claimed.
        - Verifies payment asset & amount cover the NFT price.
        - Assigns the sequential edition number (#1 .. max_supply).
        - Mints the bundled Moltbook Alpha API key & credit lot.
        - Signs an Ed25519 cryptographic ownership & provenance witness receipt.
        """
        ledger = self._load_ledger()
        order = ledger.get("orders", {}).get(order_id)
        if not order:
            raise KeyError(f"NFT order '{order_id}' not found.")

        if order["status"] == "MINTED":
            return order["mint_receipt"]

        if verified_payment.asset != order["asset"]:
            raise ValueError(f"Payment asset '{verified_payment.asset}' does not match order asset '{order['asset']}'.")
        if verified_payment.amount_raw < order["amount_raw"]:
            raise ValueError(
                f"Underpaid NFT order: received {verified_payment.amount_raw}, expected {order['amount_raw']}."
            )

        nft_id = order["nft_id"]
        spec = MOLT_ALPHA_DEMS_CATALOG[nft_id]
        current_minted = int(ledger["minted_counts"].get(nft_id, 0))
        if current_minted >= spec["max_supply"]:
            raise ValueError(f"NFT '{spec['name']}' is sold out.")

        edition_number = current_minted + 1
        ledger["minted_counts"][nft_id] = edition_number

        # Mint bundled API key via storage
        raw_api_key, key_record = storage.create_api_key(
            tier=order["bundled_tier"],
            credits=order["bundled_credits"],
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        edition_id = f"mdems_{spec['number']}_ed{edition_number:02d}_{secrets.token_hex(4)}"

        witness_id = None
        witness_sig = None
        if witness_manager is not None:
            try:
                w = witness_manager.create_witness(
                    action="NFT_LAZY_MINT_FULFILLED",
                    actor=order["buyer_wallet"],
                    key_hash=key_record.get("key_prefix", "nft_pass"),
                    request_id=order_id,
                    environmental_anchor={
                        "collection": COLLECTION_METADATA["collection_id"],
                        "nft_id": nft_id,
                        "edition_number": edition_number,
                        "max_supply": spec["max_supply"],
                        "buyer_wallet": order["buyer_wallet"],
                        "tx_signature": tx_signature,
                        "metadata_uri": order["metadata_uri"],
                    },
                )
                witness_id = w.get("witness_id")
                witness_sig = w.get("signature")
            except Exception:
                pass

        mint_receipt = {
            "status": "MINTED",
            "edition_id": edition_id,
            "order_id": order_id,
            "collection": COLLECTION_METADATA["name"],
            "nft_id": nft_id,
            "nft_name": f"{spec['name']} (Edition #{edition_number}/{spec['max_supply']})",
            "rarity": spec["rarity"],
            "edition_number": edition_number,
            "max_supply": spec["max_supply"],
            "owner_wallet": order["buyer_wallet"],
            "payment_tx_signature": tx_signature,
            "image_url": order["image_url"],
            "metadata_uri": order["metadata_uri"],
            "metaplex_metadata": self.build_metaplex_metadata(nft_id, edition_number=edition_number),
            "bundled_utility": {
                "api_key": raw_api_key,
                "key_prefix": key_record.get("key_prefix"),
                "tier": order["bundled_tier"],
                "credits_granted": order["bundled_credits"],
            },
            "state_witness_id": witness_id,
            "witness_signature": witness_sig,
            "minted_at": now_iso,
        }

        order["status"] = "MINTED"
        order["mint_receipt"] = mint_receipt
        ledger["orders"][order_id] = order
        ledger["minted_editions"].append({
            "edition_id": edition_id,
            "nft_id": nft_id,
            "nft_name": mint_receipt["nft_name"],
            "rarity": spec["rarity"],
            "edition_number": edition_number,
            "owner_wallet": order["buyer_wallet"],
            "tx_signature": tx_signature,
            "state_witness_id": witness_id,
            "minted_at": now_iso,
        })
        self._save_ledger(ledger)
        return mint_receipt


if __name__ == "__main__":
    col = MoltAlphaDemsCollection()
    files = col.export_static_metadata_files()
    print(f"[Molt Alpha DEMS] Exported {len(files)} Metaplex metadata files:")
    for p in files:
        print(f"  - {p}")
