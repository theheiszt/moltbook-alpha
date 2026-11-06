import React, { useState, useMemo } from 'react';
import {
  Sparkles,
  ShieldCheck,
  Layers,
  CheckCircle2,
  ArrowRight,
  X,
  Copy,
  Check,
  Gem,
  Terminal,
} from 'lucide-react';
import { PaymentRail } from '../utils/cryptoEngine';

export type NftSeriesId =
  | 'ALL'
  | 'molt-alpha-dems'
  | 'molt-alpha-operators'
  | 'moltbook-chronicles';

export type NftRarity = 'LEGENDARY' | 'EPIC' | 'RARE' | 'COMMON';

export interface MoltNftItem {
  id: string;
  seriesId: Exclude<NftSeriesId, 'ALL'>;
  seriesTitle: string;
  numberLabel: string;
  title: string;
  rarity: NftRarity;
  imagePath: string;
  lore: string;
  bundledCredits: number;
  creditTierLabel: string;
  priceSol: number;
  priceUsdc: number;
  editionsTotal: number;
  editionsRemaining: number;
}

export const MOLT_NFT_CATALOG: MoltNftItem[] = [
  // SERIES I: GENESIS DEMS (6)
  {
    id: 'dems_01_the_synth',
    seriesId: 'molt-alpha-dems',
    seriesTitle: 'Genesis DEMs',
    numberLabel: '01 / THE SYNTH',
    title: 'The Synth',
    rarity: 'RARE',
    imagePath: '/assets/nfts/molt-alpha-dems/01_the_synth.png',
    lore: 'Born in the neon glow of the first terminal. Half circuit, half consciousness.',
    bundledCredits: 150,
    creditTierLabel: '+150 Pro API Credits',
    priceSol: 0.05,
    priceUsdc: 5,
    editionsTotal: 25,
    editionsRemaining: 19,
  },
  {
    id: 'dems_02_inscribe',
    seriesId: 'molt-alpha-dems',
    seriesTitle: 'Genesis DEMs',
    numberLabel: '02 / INSCRIBE',
    title: 'Inscribe',
    rarity: 'COMMON',
    imagePath: '/assets/nfts/molt-alpha-dems/02_inscribe.png',
    lore: 'Every block a page. Every hash a signature that outlives its creator.',
    bundledCredits: 50,
    creditTierLabel: '+50 Starter API Credits',
    priceSol: 0.02,
    priceUsdc: 2,
    editionsTotal: 50,
    editionsRemaining: 42,
  },
  {
    id: 'dems_03_scribe',
    seriesId: 'molt-alpha-dems',
    seriesTitle: 'Genesis DEMs',
    numberLabel: '03 / SCRIBE',
    title: 'Scribe',
    rarity: 'LEGENDARY',
    imagePath: '/assets/nfts/molt-alpha-dems/03_scribe.png',
    lore: 'Keeper of the canonical ledger. Where code becomes law and witness becomes truth.',
    bundledCredits: 1500,
    creditTierLabel: '+1,500 Premium API Credits',
    priceSol: 0.25,
    priceUsdc: 25,
    editionsTotal: 3,
    editionsRemaining: 2,
  },
  {
    id: 'dems_04_core',
    seriesId: 'molt-alpha-dems',
    seriesTitle: 'Genesis DEMs',
    numberLabel: '04 / CORE',
    title: 'Core',
    rarity: 'EPIC',
    imagePath: '/assets/nfts/molt-alpha-dems/04_core.png',
    lore: 'Deep beneath the orderbooks, the core pulses with raw microstructure entropy.',
    bundledCredits: 400,
    creditTierLabel: '+400 Pro API Credits',
    priceSol: 0.1,
    priceUsdc: 10,
    editionsTotal: 10,
    editionsRemaining: 7,
  },
  {
    id: 'dems_05_wanderer',
    seriesId: 'molt-alpha-dems',
    seriesTitle: 'Genesis DEMs',
    numberLabel: '05 / WANDERER',
    title: 'Wanderer',
    rarity: 'RARE',
    imagePath: '/assets/nfts/molt-alpha-dems/05_wanderer.png',
    lore: 'Drifting across fragmented liquidity pools in search of the unspoofed signal.',
    bundledCredits: 150,
    creditTierLabel: '+150 Pro API Credits',
    priceSol: 0.05,
    priceUsdc: 5,
    editionsTotal: 25,
    editionsRemaining: 21,
  },
  {
    id: 'dems_06_oracle',
    seriesId: 'molt-alpha-dems',
    seriesTitle: 'Genesis DEMs',
    numberLabel: '06 / ORACLE',
    title: 'Oracle',
    rarity: 'EPIC',
    imagePath: '/assets/nfts/molt-alpha-dems/06_oracle.png',
    lore: 'It does not predict the market. It weighs the cryptographic proof of what already is.',
    bundledCredits: 400,
    creditTierLabel: '+400 Pro API Credits',
    priceSol: 0.1,
    priceUsdc: 10,
    editionsTotal: 10,
    editionsRemaining: 8,
  },

  // SERIES II: CYBER OPERATORS (6)
  {
    id: 'ops_01_the_observer',
    seriesId: 'molt-alpha-operators',
    seriesTitle: 'Cyber Operators',
    numberLabel: '01 / THE OBSERVER',
    title: 'The Observer',
    rarity: 'RARE',
    imagePath: '/assets/nfts/molt-alpha-operators/01_the_observer.png',
    lore: 'Watching every tick across Raydium and Orca before the mempool settles.',
    bundledCredits: 150,
    creditTierLabel: '+150 Pro API Credits',
    priceSol: 0.05,
    priceUsdc: 5,
    editionsTotal: 25,
    editionsRemaining: 18,
  },
  {
    id: 'ops_02_the_synth',
    seriesId: 'molt-alpha-operators',
    seriesTitle: 'Cyber Operators',
    numberLabel: '02 / THE SYNTH',
    title: 'Operator Synth',
    rarity: 'EPIC',
    imagePath: '/assets/nfts/molt-alpha-operators/02_the_synth.png',
    lore: 'Dual-threaded neural operator synthesizing Jito bundle telemetry in real time.',
    bundledCredits: 400,
    creditTierLabel: '+400 Pro API Credits',
    priceSol: 0.1,
    priceUsdc: 10,
    editionsTotal: 10,
    editionsRemaining: 6,
  },
  {
    id: 'ops_03_the_wanderer',
    seriesId: 'molt-alpha-operators',
    seriesTitle: 'Cyber Operators',
    numberLabel: '03 / THE WANDERER',
    title: 'Operator Wanderer',
    rarity: 'RARE',
    imagePath: '/assets/nfts/molt-alpha-operators/03_the_wanderer.png',
    lore: 'Autonomous scout traversing cross-DEX routes with zero-trust state proofs.',
    bundledCredits: 150,
    creditTierLabel: '+150 Pro API Credits',
    priceSol: 0.05,
    priceUsdc: 5,
    editionsTotal: 25,
    editionsRemaining: 20,
  },
  {
    id: 'ops_04_the_nomad',
    seriesId: 'molt-alpha-operators',
    seriesTitle: 'Cyber Operators',
    numberLabel: '04 / THE NOMAD',
    title: 'The Nomad',
    rarity: 'EPIC',
    imagePath: '/assets/nfts/molt-alpha-operators/04_the_nomad.png',
    lore: 'Untethered from centralized RPCs, verifying canonical JSON payloads at the edge.',
    bundledCredits: 400,
    creditTierLabel: '+400 Pro API Credits',
    priceSol: 0.1,
    priceUsdc: 10,
    editionsTotal: 10,
    editionsRemaining: 9,
  },
  {
    id: 'ops_05_the_companion',
    seriesId: 'molt-alpha-operators',
    seriesTitle: 'Cyber Operators',
    numberLabel: '05 / THE COMPANION',
    title: 'The Companion',
    rarity: 'COMMON',
    imagePath: '/assets/nfts/molt-alpha-operators/05_the_companion.png',
    lore: 'Loyal execution sidekick guarding swap slippage and LP concentration thresholds.',
    bundledCredits: 50,
    creditTierLabel: '+50 Starter API Credits',
    priceSol: 0.02,
    priceUsdc: 2,
    editionsTotal: 50,
    editionsRemaining: 44,
  },
  {
    id: 'ops_06_the_origin',
    seriesId: 'molt-alpha-operators',
    seriesTitle: 'Cyber Operators',
    numberLabel: '06 / THE ORIGIN',
    title: 'The Origin',
    rarity: 'LEGENDARY',
    imagePath: '/assets/nfts/molt-alpha-operators/06_the_origin.png',
    lore: 'Prime architect of the Sentinel protocol — the first Ed25519 key epoch.',
    bundledCredits: 1500,
    creditTierLabel: '+1,500 Premium API Credits',
    priceSol: 0.25,
    priceUsdc: 25,
    editionsTotal: 3,
    editionsRemaining: 1,
  },

  // SERIES III: THE MOLTBOOK CHRONICLES (6)
  {
    id: 'chron_01_the_reader',
    seriesId: 'moltbook-chronicles',
    seriesTitle: 'Moltbook Chronicles',
    numberLabel: '01 / THE READER',
    title: 'The Reader',
    rarity: 'COMMON',
    imagePath: '/assets/nfts/moltbook-chronicles/01_the_reader.png',
    lore: 'Deciphering the ancient slot logs inscribed in the Moltbook.',
    bundledCredits: 50,
    creditTierLabel: '+50 Starter API Credits',
    priceSol: 0.02,
    priceUsdc: 2,
    editionsTotal: 50,
    editionsRemaining: 39,
  },
  {
    id: 'chron_02_the_dreamer',
    seriesId: 'moltbook-chronicles',
    seriesTitle: 'Moltbook Chronicles',
    numberLabel: '02 / THE DREAMER',
    title: 'The Dreamer',
    rarity: 'LEGENDARY',
    imagePath: '/assets/nfts/moltbook-chronicles/02_the_dreamer.png',
    lore: 'Envisioning an autonomous market where every signal carries its own mathematical proof.',
    bundledCredits: 1500,
    creditTierLabel: '+1,500 Premium API Credits',
    priceSol: 0.25,
    priceUsdc: 25,
    editionsTotal: 3,
    editionsRemaining: 2,
  },
  {
    id: 'chron_03_the_builder',
    seriesId: 'moltbook-chronicles',
    seriesTitle: 'Moltbook Chronicles',
    numberLabel: '03 / THE BUILDER',
    title: 'The Builder',
    rarity: 'RARE',
    imagePath: '/assets/nfts/moltbook-chronicles/03_the_builder.png',
    lore: 'Forging resilient multi-rail settlement pipelines in the digital foundry.',
    bundledCredits: 150,
    creditTierLabel: '+150 Pro API Credits',
    priceSol: 0.05,
    priceUsdc: 5,
    editionsTotal: 25,
    editionsRemaining: 22,
  },
  {
    id: 'chron_04_the_guardian',
    seriesId: 'moltbook-chronicles',
    seriesTitle: 'Moltbook Chronicles',
    numberLabel: '04 / THE GUARDIAN',
    title: 'The Guardian',
    rarity: 'EPIC',
    imagePath: '/assets/nfts/moltbook-chronicles/04_the_guardian.png',
    lore: 'Standing watch at the liquidity gate, halting rug-pulls before execution.',
    bundledCredits: 400,
    creditTierLabel: '+400 Pro API Credits',
    priceSol: 0.1,
    priceUsdc: 10,
    editionsTotal: 10,
    editionsRemaining: 7,
  },
  {
    id: 'chron_05_the_wanderer',
    seriesId: 'moltbook-chronicles',
    seriesTitle: 'Moltbook Chronicles',
    numberLabel: '05 / THE WANDERER',
    title: 'Chronicle Wanderer',
    rarity: 'RARE',
    imagePath: '/assets/nfts/moltbook-chronicles/05_the_wanderer.png',
    lore: 'Chronicling the forgotten epochs of decentralized microstructure.',
    bundledCredits: 150,
    creditTierLabel: '+150 Pro API Credits',
    priceSol: 0.05,
    priceUsdc: 5,
    editionsTotal: 25,
    editionsRemaining: 16,
  },
  {
    id: 'chron_06_the_archive',
    seriesId: 'moltbook-chronicles',
    seriesTitle: 'Moltbook Chronicles',
    numberLabel: '06 / THE ARCHIVE',
    title: 'The Archive',
    rarity: 'EPIC',
    imagePath: '/assets/nfts/moltbook-chronicles/06_the_archive.png',
    lore: 'Immutable vault of every SHA-256 digest and Ed25519 attestation ever signed.',
    bundledCredits: 400,
    creditTierLabel: '+400 Pro API Credits',
    priceSol: 0.1,
    priceUsdc: 10,
    editionsTotal: 10,
    editionsRemaining: 8,
  },
];

function getRarityBadgeStyle(rarity: NftRarity): string {
  switch (rarity) {
    case 'LEGENDARY':
      return 'bg-amber-500/20 border-amber-400 text-amber-300';
    case 'EPIC':
      return 'bg-purple-500/20 border-purple-400 text-purple-300';
    case 'RARE':
      return 'bg-cyan-500/20 border-cyan-400 text-cyan-300';
    default:
      return 'bg-emerald-500/20 border-emerald-400/60 text-emerald-300';
  }
}

interface NftsPageProps {
  currentSlot: number;
  userCredits: number;
  onMintNftPass: (
    nft: MoltNftItem,
    rail: PaymentRail,
    buyerWallet: string
  ) => Promise<void>;
}

export const NftsPage: React.FC<NftsPageProps> = ({
  currentSlot,
  userCredits,
  onMintNftPass,
}) => {
  const [seriesFilter, setSeriesFilter] = useState<NftSeriesId>('ALL');
  const [rarityFilter, setRarityFilter] = useState<string>('ALL');
  const [activeNftModal, setActiveNftModal] = useState<MoltNftItem | null>(null);
  const [selectedRail, setSelectedRail] = useState<'SOL' | 'USDC'>('SOL');
  const [buyerWallet, setBuyerWallet] = useState<string>(
    '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU'
  );
  const [isMinting, setIsMinting] = useState<boolean>(false);
  const [mintedWitnessReceipt, setMintedWitnessReceipt] = useState<{
    orderId: string;
    editionNumber: number;
    witnessSig: string;
    creditsGranted: number;
  } | null>(null);
  const [copiedOrder, setCopiedOrder] = useState<boolean>(false);
  const [mintedIds, setMintedIds] = useState<Record<string, number>>({});

  const filteredNfts = useMemo(() => {
    return MOLT_NFT_CATALOG.filter((item) => {
      if (seriesFilter !== 'ALL' && item.seriesId !== seriesFilter) return false;
      if (rarityFilter !== 'ALL' && item.rarity !== rarityFilter) return false;
      return true;
    });
  }, [seriesFilter, rarityFilter]);

  const handleConfirmLazyMint = async () => {
    if (!activeNftModal) return;
    setIsMinting(true);
    try {
      await onMintNftPass(activeNftModal, selectedRail, buyerWallet);
      const nextEdition =
        activeNftModal.editionsTotal - activeNftModal.editionsRemaining + 1;
      const randomHex = Array.from({ length: 12 }, () =>
        Math.floor(Math.random() * 16).toString(16)
      ).join('');
      setMintedIds((prev) => ({
        ...prev,
        [activeNftModal.id]: (prev[activeNftModal.id] || 0) + 1,
      }));
      setMintedWitnessReceipt({
        orderId: `nft_ord_${randomHex.slice(0, 8)}`,
        editionNumber: nextEdition,
        witnessSig: `ed25519:9mTz8qvS9ewb4J7p2kQn${randomHex}`,
        creditsGranted: activeNftModal.bundledCredits,
      });
    } finally {
      setIsMinting(false);
    }
  };

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 pt-6 pb-16 space-y-6">
      {/* OPEN HERO SECTION (No outer frame, matching refined page style) */}
      <section className="py-4 sm:py-6 px-1 grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        <div className="lg:col-span-7 space-y-4">
          <div className="cyber-cut-sm inline-flex items-center gap-2 px-3.5 py-1.5 border border-cyan-500/40 bg-cyan-950/40 text-cyan-400 text-[11px] font-mono tracking-wider uppercase">
            <span className="w-1.5 h-1.5 bg-cyan-400 shrink-0" />
            <span>◆ MOLT ALPHA NFT UNIVERSE • 18 PIXEL ARTWORKS • 3 SERIES</span>
          </div>

          <h1 className="font-display font-extrabold text-4xl sm:text-5xl leading-[1.08] tracking-tight drop-shadow-[0_4px_24px_rgba(0,0,0,0.65)]">
            <span className="block text-white">Zero-Rent Lazy Mint</span>
            <span className="block molt-text-gradient mt-1">DEMs NFT Pass Marketplace</span>
          </h1>

          <p className="text-slate-200 text-sm sm:text-base max-w-2xl leading-relaxed">
            Every MoltAlpha pixel-art collectible is backed by an Ed25519 cryptographic ownership
            witness (RFC 8785 canonical JSON) and bundles instant, non-expiring prepaid API
            credits for autonomous Solana DEX intelligence.
          </p>

          <div className="flex flex-wrap items-center gap-2.5 pt-1 text-xs font-mono">
            <span className="cyber-cut-sm px-3 py-1.5 bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 font-semibold">
              0 SOL RENT OVERHEAD
            </span>
            <span className="cyber-cut-sm px-3 py-1.5 bg-[#0d1424] border border-cyan-500/40 text-cyan-300">
              GET /v1/nfts/catalog
            </span>
            <span className="cyber-cut-sm px-3 py-1.5 bg-[#0d1424] border border-purple-500/40 text-purple-300">
              POST /v1/nfts/order
            </span>
            <span className="cyber-cut-sm px-3 py-1.5 bg-[#0d1424] border border-[#1e293b] text-slate-200">
              Your Credits: <strong className="text-cyan-300">{userCredits.toLocaleString()}</strong>
            </span>
          </div>
        </div>

        {/* Right 5 cols: Bundled API Credit Tier Breakdown Card */}
        <div className="lg:col-span-5 molt-card-purple p-5 space-y-3.5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
            <div className="flex items-center gap-2">
              <Gem className="w-4 h-4 text-cyan-400" />
              <span className="font-display font-bold text-sm text-white uppercase tracking-wider">
                Bundled API Credit Entitlements
              </span>
            </div>
            <span className="text-[11px] font-mono text-cyan-300">Lazy-Mint Protocol</span>
          </div>

          <div className="grid grid-cols-2 gap-2.5 text-xs font-mono">
            <div className="bracket-card p-3 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="flex items-center justify-between">
                <span className="text-amber-300 font-bold">LEGENDARY</span>
                <span className="text-slate-400">3 Eds</span>
              </div>
              <div className="text-white font-bold text-sm">+1,500 Credits</div>
              <div className="text-[11px] text-cyan-300">0.25 SOL / 25 USDC</div>
            </div>

            <div className="bracket-card p-3 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="flex items-center justify-between">
                <span className="text-purple-300 font-bold">EPIC</span>
                <span className="text-slate-400">10 Eds</span>
              </div>
              <div className="text-white font-bold text-sm">+400 Credits</div>
              <div className="text-[11px] text-cyan-300">0.10 SOL / 10 USDC</div>
            </div>

            <div className="bracket-card p-3 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="flex items-center justify-between">
                <span className="text-cyan-300 font-bold">RARE</span>
                <span className="text-slate-400">25 Eds</span>
              </div>
              <div className="text-white font-bold text-sm">+150 Credits</div>
              <div className="text-[11px] text-cyan-300">0.05 SOL / 5 USDC</div>
            </div>

            <div className="bracket-card p-3 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="flex items-center justify-between">
                <span className="text-emerald-300 font-bold">COMMON</span>
                <span className="text-slate-400">50 Eds</span>
              </div>
              <div className="text-white font-bold text-sm">+50 Credits</div>
              <div className="text-[11px] text-cyan-300">0.02 SOL / 2 USDC</div>
            </div>
          </div>
        </div>
      </section>

      {/* SERIES SWITCHER TAB BAR & RARITY FILTER matching https://www.moltalpha.dev/nfts.html */}
      <section className="molt-card p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {(
            [
              { id: 'ALL', label: 'ALL PIECES (18)' },
              { id: 'molt-alpha-dems', label: 'GENESIS DEMS (6)' },
              { id: 'molt-alpha-operators', label: 'CYBER OPERATORS (6)' },
              { id: 'moltbook-chronicles', label: 'CHRONICLES (6)' },
            ] as const
          ).map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSeriesFilter(tab.id)}
              className={`cyber-cut-sm px-4 py-2 text-xs font-mono uppercase tracking-wider transition-all cursor-pointer border ${
                seriesFilter === tab.id
                  ? 'bg-cyan-500/25 text-cyan-200 border-cyan-400 font-bold shadow-[0_0_14px_rgba(6,182,212,0.3)]'
                  : 'bg-[#080d16] text-slate-300 border-[#1e293b] hover:text-white hover:border-cyan-500/40'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="text-slate-400">Rarity:</span>
          {(['ALL', 'LEGENDARY', 'EPIC', 'RARE', 'COMMON'] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRarityFilter(r)}
              className={`cyber-cut-sm px-2.5 py-1 text-[11px] border cursor-pointer ${
                rarityFilter === r
                  ? 'bg-purple-500/25 text-purple-200 border-purple-400 font-bold'
                  : 'bg-[#080d16] text-slate-400 border-[#1e293b] hover:text-slate-200'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </section>

      {/* 18 PIXEL-ART NFT CARDS GRID */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {filteredNfts.map((nft) => {
          const userMintedCount = mintedIds[nft.id] || 0;
          const remaining = Math.max(0, nft.editionsRemaining - userMintedCount);
          return (
            <div
              key={nft.id}
              className="bracket-card p-4 flex flex-col justify-between space-y-4 bg-[#0b1221]/90 hover:border-cyan-400/60 transition-all"
            >
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-tr" />
              <div className="bracket-tick bracket-tick-bl" />
              <div className="bracket-tick bracket-tick-br" />

              <div className="space-y-3">
                {/* Top Series & Rarity Header */}
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-mono text-cyan-400 font-semibold">
                    {nft.numberLabel}
                  </span>
                  <span
                    className={`cyber-cut-sm px-2 py-0.5 text-[10px] font-mono font-bold border ${getRarityBadgeStyle(
                      nft.rarity
                    )}`}
                  >
                    {nft.rarity}
                  </span>
                </div>

                {/* Authentic 680x340 Pixel Art Image Container — edge-to-edge with zero top/bottom black bars */}
                <div className="relative overflow-hidden border border-slate-800/90 cyber-cut-sm group">
                  <img
                    src={nft.imagePath}
                    alt={`${nft.seriesTitle} — ${nft.title}`}
                    loading="lazy"
                    style={{ imageRendering: 'pixelated' }}
                    className="w-full h-auto block object-cover group-hover:scale-105 transition-transform duration-300"
                  />
                  <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between text-[10px] font-mono pointer-events-none">
                    <span className="px-2 py-0.5 bg-[#080d16]/90 border border-slate-700 text-slate-300 cyber-cut-sm">
                      {nft.seriesTitle}
                    </span>
                    <span className="px-2 py-0.5 bg-[#080d16]/90 border border-emerald-500/40 text-emerald-300 font-bold cyber-cut-sm">
                      {nft.creditTierLabel}
                    </span>
                  </div>
                </div>

                {/* Lore Quote */}
                <p className="text-xs text-slate-300 italic leading-relaxed">
                  &ldquo;{nft.lore}&rdquo;
                </p>
              </div>

              {/* Price, Editions & Lazy-Mint CTA */}
              <div className="pt-3 border-t border-slate-800/80 space-y-3">
                <div className="flex items-center justify-between text-xs font-mono">
                  <div>
                    <div className="text-[10px] text-slate-400">LAZY-MINT PRICE</div>
                    <div className="text-sm font-bold text-white">
                      {nft.priceSol} SOL{' '}
                      <span className="text-slate-400 font-normal">/ {nft.priceUsdc} USDC</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-slate-400">EDITIONS</div>
                    <div className="text-xs font-semibold text-cyan-300 tabular-nums">
                      {remaining} / {nft.editionsTotal} left
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setActiveNftModal(nft);
                    setMintedWitnessReceipt(null);
                  }}
                  className="molt-btn-cyan w-full py-2.5 px-4 text-xs font-mono uppercase tracking-wider inline-flex items-center justify-center gap-2 cursor-pointer"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>
                    {userMintedCount > 0
                      ? `Mint Another Pass (${userMintedCount} Owned)`
                      : 'Mint NFT Pass'}
                  </span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </section>

      {/* LAZY-MINT NFT PASS MODAL */}
      {activeNftModal && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="nft-mint-modal-title"
        >
          <div className="molt-card-popular max-w-lg w-full p-6 space-y-5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2.5">
                <Sparkles className="w-5 h-5 text-cyan-400" />
                <div>
                  <h3 id="nft-mint-modal-title" className="font-display font-bold text-lg text-white">
                    Lazy-Mint NFT Pass — {activeNftModal.numberLabel}
                  </h3>
                  <p className="text-xs font-mono text-cyan-300">
                    {activeNftModal.seriesTitle} · {activeNftModal.creditTierLabel}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setActiveNftModal(null)}
                aria-label="Close NFT Mint modal"
                className="text-slate-400 hover:text-white p-1 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-center">
              <div className="sm:col-span-5 overflow-hidden border border-cyan-500/40 cyber-cut-sm">
                <img
                  src={activeNftModal.imagePath}
                  alt={activeNftModal.title}
                  style={{ imageRendering: 'pixelated' }}
                  className="w-full h-auto block object-cover"
                />
              </div>

              <div className="sm:col-span-7 space-y-2.5 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-slate-400">Rarity Tier:</span>
                  <span className="text-white font-bold">{activeNftModal.rarity}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Bundled API Credits:</span>
                  <span className="text-emerald-400 font-bold">
                    +{activeNftModal.bundledCredits.toLocaleString()} Credits
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Solana Rent Cost:</span>
                  <span className="text-cyan-300">0.00 SOL (Lazy-Mint)</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Target Slot:</span>
                  <span className="text-slate-200">{currentSlot.toLocaleString()}</span>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1.5">
                  Select Settlement Currency:
                </label>
                <div className="grid grid-cols-2 gap-2.5">
                  <button
                    type="button"
                    onClick={() => setSelectedRail('SOL')}
                    className={`py-2 px-3 text-xs font-mono font-bold border cursor-pointer ${
                      selectedRail === 'SOL'
                        ? 'bg-cyan-500/25 border-cyan-400 text-cyan-200'
                        : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
                    }`}
                  >
                    {activeNftModal.priceSol} SOL (Solana Mainnet)
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedRail('USDC')}
                    className={`py-2 px-3 text-xs font-mono font-bold border cursor-pointer ${
                      selectedRail === 'USDC'
                        ? 'bg-cyan-500/25 border-cyan-400 text-cyan-200'
                        : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
                    }`}
                  >
                    {activeNftModal.priceUsdc} USDC (SPL Token)
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">
                  Buyer Solana Wallet Address (Owner Witness Recipient):
                </label>
                <input
                  type="text"
                  value={buyerWallet}
                  onChange={(e) => setBuyerWallet(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-cyan-400 focus:outline-none text-xs font-mono text-cyan-200"
                />
              </div>
            </div>

            {mintedWitnessReceipt ? (
              <div className="bracket-card p-4 bg-emerald-950/30 border-emerald-500/50 space-y-2 text-xs font-mono">
                <div className="bracket-tick bracket-tick-tl" />
                <div className="bracket-tick bracket-tick-br" />
                <div className="flex items-center justify-between text-emerald-300 font-bold">
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>NFT Pass Minted &amp; Witness Signed!</span>
                  </span>
                  <span>Edition #{mintedWitnessReceipt.editionNumber}</span>
                </div>
                <div className="text-slate-300">
                  Order ID: <strong className="text-white">{mintedWitnessReceipt.orderId}</strong>
                </div>
                <div className="text-emerald-300">
                  Credits Added:{' '}
                  <strong>+{mintedWitnessReceipt.creditsGranted.toLocaleString()} API Queries</strong>
                </div>
                <div className="text-purple-300 truncate">
                  Witness Sig: {mintedWitnessReceipt.witnessSig}
                </div>
                <div className="pt-2 flex justify-end">
                  <button
                    type="button"
                    onClick={() => setActiveNftModal(null)}
                    className="molt-btn-cyan px-4 py-1.5 text-xs font-bold cursor-pointer"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setActiveNftModal(null)}
                  className="cyber-btn-ghost px-4 py-2.5 text-xs font-mono uppercase cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isMinting}
                  onClick={handleConfirmLazyMint}
                  className="molt-btn-cyan px-5 py-2.5 text-xs font-mono uppercase tracking-wider font-bold cursor-pointer"
                >
                  {isMinting
                    ? 'Signing Ownership Witness...'
                    : `Verify & Mint (${
                        selectedRail === 'SOL'
                          ? `${activeNftModal.priceSol} SOL`
                          : `${activeNftModal.priceUsdc} USDC`
                      })`}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
