import React, { useState } from 'react';
import {
  ShieldCheck,
  Layers,
  Fingerprint,
  Bot,
  ArrowRight,
  Terminal,
  Code2,
  CheckCircle2,
  AlertTriangle,
  Zap,
  Globe,
  FileCode2,
} from 'lucide-react';
import {
  VerifiedCubeBadge,
  SentinelShieldBadge,
} from './IsometricChipGraphic';
import { DexPool, formatTokenPriceUsd } from '../utils/cryptoEngine';

interface LandingPageProps {
  pools: DexPool[];
  currentSlot: number;
  onNavigateTerminal: (selectedPoolPair?: string) => void;
  onNavigateDevelopers: () => void;
  onNavigateAutomation?: () => void;
  onNavigateAdmin: () => void;
}

interface SentinelShowcaseStage {
  step: number;
  tag: string;
  badge: string;
  colorClass: string;
  dotClass: string;
  title: string;
  description: string;
  metrics: string[];
  imageSrc: string;
  imageAlt: string;
  cliCommand: string;
}

const SENTINEL_SHOWCASE_STAGES: SentinelShowcaseStage[] = [
  {
    step: 1,
    tag: '01 • Continuous DEX Surveillance',
    badge: '24/7 SURVEILLANCE',
    colorClass: 'text-emerald-400',
    dotClass: 'bg-emerald-400',
    title: 'Autonomous Pool Topology Engine',
    description:
      'Surveys tick-level topology across Solana CLMM and DLMM pools (Raydium, Orca Whirlpool, Meteora) and Metal X DEX order queues. Real-time distribution across SAFE, WATCH, HIGH, and CRITICAL classifications.',
    metrics: ['✓ 10 Monitored Pools', '✓ Coinbase Spot Anchored', '✓ 0 Unverified Feeds'],
    imageSrc: '/assets/sentinel-showcase/stage1-dashboard-overview.png',
    imageAlt: 'MoltAlpha Sentinel Dashboard Overview',
    cliCommand: 'curl -s https://api.moltalpha.dev/v1/capabilities | jq .',
  },
  {
    step: 2,
    tag: '02 • Preflight Execution Gate',
    badge: '4-FACTOR GATE',
    colorClass: 'text-cyan-400',
    dotClass: 'bg-cyan-400',
    title: 'Pre-Trade Interceptor & Sniper Guard',
    description:
      'Evaluates orthogonal risk dimensions: Pool Structural (15%), Token Mechanics (20%), DEX Microstructure (40%), and Oracle Integrity (25%) with deterministic ALLOW, REVIEW, or ABORT_SNIPE gates before any transaction is signed.',
    metrics: ['ALLOW (Score ≤ Gate)', 'Zero blind capital commitment', 'Sub-45ms preflight'],
    imageSrc: '/assets/sentinel-showcase/stage2-preflight-gate.png',
    imageAlt: 'MoltAlpha Sentinel Preflight Execution Gate',
    cliCommand: 'curl -s https://api.moltalpha.dev/v1/intel/sample | jq .preflight_gate',
  },
  {
    step: 3,
    tag: '03 • Additive Risk Tracking',
    badge: 'TIME-WEIGHTED DECAY',
    colorClass: 'text-sky-400',
    dotClass: 'bg-sky-400',
    title: 'Historical Volatility & Depth Regression',
    description:
      'Tracks Herfindahl-Hirschman LP concentration (HHI), $10k/$50k execution slippage curves, and exponential time-decay across consecutive Solana slots to expose slow-bleed rug pulls.',
    metrics: ['HHI LP Concentration', 'Slot-synchronized regression', '24h Liquidity Curve'],
    imageSrc: '/assets/sentinel-showcase/stage3-historical-trends.png',
    imageAlt: 'MoltAlpha Sentinel Historical Trends',
    cliCommand: 'curl -s https://api.moltalpha.dev/v1/intel/opportunities?min_profit_pct=0.05',
  },
  {
    step: 4,
    tag: '04 • Agent Credit Bureau',
    badge: 'REPUTATION DOSSIER',
    colorClass: 'text-amber-400',
    dotClass: 'bg-amber-400',
    title: 'Settlement Reliability & DuesProof™ Dossier',
    description:
      'Verifiable counterparty credit rating for autonomous agents. Tracks completed jobs, fulfillment claims, historical defaults, and Ed25519 DuesProof™ BirthCert provenance.',
    metrics: ['98.4% Reliability Index', '0% Historical Default Rate', 'RFC 8785 Canonical Cert'],
    imageSrc: '/assets/sentinel-showcase/stage4-agent-credit-bureau.png',
    imageAlt: 'MoltAlpha Sentinel Agent Credit Bureau',
    cliCommand: 'curl -s https://api.moltalpha.dev/api/v1/agents/antigravityandrew/dossier | jq .',
  },
  {
    step: 5,
    tag: '05 • Live Anomaly Radar',
    badge: 'SUB-100MS STREAM',
    colorClass: 'text-rose-400',
    dotClass: 'bg-rose-400',
    title: 'Microstructural Liquidity Traps',
    description:
      'Real-time detection of high-risk DEX anomalies: TICK_VACUUM (> $50k liquidity collapse in ≤ 3s), SPOOFED_WALL depth manipulation, wash-trading loops, and active freeze/mint authorities.',
    metrics: ['Instant SEV-1 Alerts', 'Jito Sandwich Detection', 'Automated Bot Abort'],
    imageSrc: '/assets/sentinel-showcase/stage5-live-anomalies.png',
    imageAlt: 'MoltAlpha Sentinel Live Anomalies',
    cliCommand: 'curl -s https://api.moltalpha.dev/v1/sentinel/anomalies | jq .',
  },
  {
    step: 6,
    tag: '06 • Cryptographic Witness',
    badge: 'ED25519 SPKI',
    colorClass: 'text-purple-400',
    dotClass: 'bg-purple-400',
    title: 'RFC 8785 Canonical State Witness',
    description:
      'Zero blind trust. Every risk score and bot manifest is canonicalized via RFC 8785 JCS, hashed with SHA-256, and signed by rotating Ed25519 witness keys for independent verification.',
    metrics: ['Ed25519 Signature Binding', 'SHA-256 Digest Verification', 'Epoch Key Rotation'],
    imageSrc: '/assets/sentinel-showcase/stage6-crypto-witness.png',
    imageAlt: 'MoltAlpha Sentinel Cryptographic Witness',
    cliCommand: 'curl -s https://api.moltalpha.dev/api/v1/witness/public-keys | jq .',
  },
];

export const LandingPage: React.FC<LandingPageProps> = ({
  pools,
  currentSlot,
  onNavigateTerminal,
  onNavigateDevelopers,
  onNavigateAutomation,
}) => {
  const [selectedCapability, setSelectedCapability] = useState<string | null>(null);
  const [activeShowcaseStage, setActiveShowcaseStage] = useState<number>(1);

  const featuredPools = pools.slice(0, 4);
  const currentStage =
    SENTINEL_SHOWCASE_STAGES.find((s) => s.step === activeShowcaseStage) ||
    SENTINEL_SHOWCASE_STAGES[0];

  const capabilities = [
    {
      id: 'sentinel-engine',
      title: 'Sentinel Risk Engine',
      subtitle: 'Pre-trade pool analysis and threat detection',
      detail:
        'Evaluates LP concentration, rug-pull mint authority, Jito bundle sandwich pressure, and depth slippage in <45ms before transaction signing.',
      icon: ShieldCheck,
    },
    {
      id: 'cross-dex',
      title: 'Cross-DEX Intelligence',
      subtitle: 'Raydium, Orca, Meteora & Metal X DEX',
      detail:
        'Unified slot-synchronized state ingestion across Raydium CLMM, Orca Whirlpools, Jupiter routing, Meteora DLMM pools, and XPR Network Metal X DEX smart contracts.',
      icon: Layers,
    },
    {
      id: 'witnesses',
      title: 'Cryptographic Witnesses',
      subtitle: 'Tamper-evident, Ed25519 verified results',
      detail:
        'Every risk score is serialized into RFC 8785 Canonical JSON, hashed via SHA-256, and signed by rotating Ed25519 witness keys for zero-trust auditability.',
      icon: Fingerprint,
    },
    {
      id: 'agent-infra',
      title: 'Agent & Sniper Bot Studio',
      subtitle: 'Non-custodial bots, Credit Bureau & DuesProof BirthCerts',
      detail:
        'Configure sniper bot gas budgets, slippage tolerances, target pool addresses, and custom preflight hooks settled over Solana SOL, SPL USDC, or Zero-Fee Nano (XNO).',
      icon: Bot,
    },
  ];

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 pt-6 pb-16 space-y-6">
      {/* OPEN HERO SECTION */}
      <section className="py-6 sm:py-10 px-1 grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        <div className="lg:col-span-7 space-y-5">
          <div className="cyber-cut-sm inline-flex items-center gap-2 px-3.5 py-1.5 border border-cyan-500/40 bg-cyan-950/40 text-cyan-400 text-[11px] font-mono tracking-wider uppercase">
            <span className="w-1.5 h-1.5 bg-cyan-400 shrink-0" />
            <span>&lt;/&gt; AUTONOMOUS MARKET INTELLIGENCE · WWW.MOLTALPHA.DEV</span>
          </div>

          <h1 className="font-display font-extrabold text-4xl sm:text-6xl leading-[1.06] tracking-tight drop-shadow-[0_4px_24px_rgba(0,0,0,0.65)]">
            <span className="block text-white">Know the Risk.</span>
            <span className="block molt-text-gradient mt-1">Verify the Signal.</span>
          </h1>

          <p className="text-slate-200 text-base sm:text-lg max-w-2xl leading-relaxed drop-shadow-[0_2px_10px_rgba(0,0,0,0.8)]">
            Real-time Solana &amp; Metal X DEX intelligence, pre-trade risk assessments,
            non-custodial sniper bot automation, and cryptographically verifiable Ed25519 state
            witnesses — built for autonomous agents.
          </p>

          <div className="flex flex-wrap items-center gap-3.5 pt-1">
            <button
              type="button"
              onClick={() => onNavigateTerminal()}
              className="molt-btn-cyan px-6 py-3 text-xs sm:text-sm inline-flex items-center gap-2.5 cursor-pointer"
            >
              <Terminal className="w-4 h-4" />
              <span>Explore Sentinel</span>
              <ArrowRight className="w-4 h-4" />
            </button>

            {onNavigateAutomation && (
              <button
                type="button"
                onClick={onNavigateAutomation}
                className="cyber-btn-ghost px-5 py-3 text-xs sm:text-sm font-mono uppercase tracking-wider inline-flex items-center gap-2 text-cyan-200 cursor-pointer"
              >
                <Bot className="w-4 h-4 text-cyan-400" />
                <span>Sniper Bot Studio</span>
              </button>
            )}

            <button
              type="button"
              onClick={onNavigateDevelopers}
              className="cyber-btn-ghost px-5 py-3 text-xs sm:text-sm font-mono uppercase tracking-wider inline-flex items-center gap-2 cursor-pointer"
            >
              <Code2 className="w-4 h-4 text-cyan-400" />
              <span>Developer Quickstart</span>
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-6 pt-2 text-xs sm:text-sm font-mono text-slate-200">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>DEX Risk Intelligence</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Cryptographic Witnesses</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Agent-Ready API &amp; Bot SDK</span>
            </div>
          </div>
        </div>
      </section>

      {/* MIDDLE SPLIT: SENTINEL RISK ENGINE — LIVE DEMO (Left 8 cols) + PLATFORM CAPABILITIES (Right 4 cols) */}
      <section className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
        {/* Left: SENTINEL RISK ENGINE — LIVE DEMO */}
        <div className="lg:col-span-8 molt-card cyber-ruler-left p-5 sm:p-6 flex flex-col justify-between space-y-5">
          {/* Header Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3.5">
            <div className="flex items-center gap-3">
              <SentinelShieldBadge size="sm" />
              <h2 className="font-display font-bold text-base sm:text-lg tracking-wide text-white uppercase">
                SENTINEL RISK ENGINE — INTERACTIVE DEMO
              </h2>
            </div>

            <div className="flex items-center gap-2 text-xs font-mono">
              <span
                data-testid="simulated-demo-badge"
                className="cyber-cut-sm inline-flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/15 border border-amber-400/50 text-amber-300 font-semibold"
              >
                <span className="w-1.5 h-1.5 bg-amber-400" />
                SIMULATED DEMO
              </span>
              <span className="cyber-cut-sm px-3 py-1 bg-[#080d16] border border-[#1e293b] text-slate-300">
                Coinbase Live
              </span>
              <span className="cyber-cut-sm px-3 py-1 bg-[#080d16] border border-[#1e293b] text-cyan-300 tabular-nums">
                Slot: {currentSlot.toLocaleString()}
              </span>
            </div>
          </div>

          {/* Content Grid inside Live Demo */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-5 items-stretch">
            {/* Left 7 cols: 3 KPI Boxes + DEX Liquidity & Risk Trend (24h) Chart */}
            <div className="md:col-span-7 flex flex-col justify-between space-y-4">
              <div className="grid grid-cols-3 gap-3">
                {/* Monitored Pools */}
                <div className="rounded-xl bg-slate-950/75 border border-cyan-500/25 p-3.5">
                  <div className="text-xs text-slate-400">Monitored Pools</div>
                  <div className="mt-1.5 flex items-baseline justify-between gap-1">
                    <span className="font-display font-extrabold text-xl sm:text-2xl text-white tabular-nums">
                      {(10482 + (pools.length - 10)).toLocaleString()}
                    </span>
                    <span className="text-xs font-mono text-emerald-400">▲ +2.3%</span>
                  </div>
                </div>

                {/* Avg. Risk Score */}
                <div className="rounded-xl bg-slate-950/75 border border-cyan-500/25 p-3.5">
                  <div className="text-xs text-slate-400">Avg. Risk Score</div>
                  <div className="mt-1.5 flex items-center justify-between gap-1">
                    <span className="font-display font-extrabold text-xl sm:text-2xl text-white tabular-nums">
                      04<span className="text-sm font-normal text-slate-400">/10</span>
                    </span>
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                      SAFE
                    </span>
                  </div>
                </div>

                {/* Critical Alerts */}
                <div className="rounded-xl bg-slate-950/75 border border-pink-500/25 p-3.5">
                  <div className="flex items-center gap-1.5 text-xs text-slate-400">
                    <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                    <span>Critical Alerts</span>
                  </div>
                  <div className="mt-1">
                    <div className="font-display font-extrabold text-xl text-white tabular-nums">0</div>
                    <div className="text-[11px] text-slate-400 truncate">No active threats</div>
                  </div>
                </div>
              </div>

              {/* DEX Liquidity & Risk Trend (24h) Chart */}
              <div className="rounded-xl bg-slate-950/65 border border-slate-800/90 p-3.5 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-slate-200">
                    DEX Liquidity &amp; Risk Trend (24h)
                  </span>
                  <div className="flex items-center gap-4 text-[11px] text-slate-300">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" />
                      Liquidity (USD)
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-fuchsia-400" />
                      Risk Score (x10)
                    </span>
                  </div>
                </div>

                <svg viewBox="0 0 460 150" className="w-full h-36 overflow-visible">
                  <defs>
                    <linearGradient id="liqArea" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00F0FF" stopOpacity="0.38" />
                      <stop offset="100%" stopColor="#00F0FF" stopOpacity="0.0" />
                    </linearGradient>
                    <linearGradient id="riskArea" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#E879F9" stopOpacity="0.28" />
                      <stop offset="100%" stopColor="#E879F9" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>

                  {/* Y-axis labels & gridlines */}
                  {[
                    { y: 18, label: '$600M' },
                    { y: 44, label: '$500M' },
                    { y: 70, label: '$400M' },
                    { y: 96, label: '$300M' },
                    { y: 122, label: '$200M' },
                  ].map((row) => (
                    <g key={row.label}>
                      <text x="0" y={row.y + 4} fill="#64748B" fontSize="10" fontFamily="JetBrains Mono">
                        {row.label}
                      </text>
                      <line
                        x1="42"
                        y1={row.y}
                        x2="450"
                        y2={row.y}
                        stroke="#1E293B"
                        strokeDasharray="3 3"
                      />
                    </g>
                  ))}

                  {/* Liquidity Cyan Curve */}
                  <path
                    d="M42,92 C75,88 95,66 130,68 C165,70 190,46 225,52 C260,58 290,34 325,44 C360,54 395,22 450,24 L450,124 L42,124 Z"
                    fill="url(#liqArea)"
                  />
                  <path
                    d="M42,92 C75,88 95,66 130,68 C165,70 190,46 225,52 C260,58 290,34 325,44 C360,54 395,22 450,24"
                    fill="none"
                    stroke="#00F0FF"
                    strokeWidth="2.5"
                  />

                  {/* Risk Score Magenta Curve */}
                  <path
                    d="M42,112 C85,108 120,104 160,109 C200,114 240,101 285,107 C330,113 385,96 450,104 L450,124 L42,124 Z"
                    fill="url(#riskArea)"
                  />
                  <path
                    d="M42,112 C85,108 120,104 160,109 C200,114 240,101 285,107 C330,113 385,96 450,104"
                    fill="none"
                    stroke="#E879F9"
                    strokeWidth="2.2"
                  />

                  {/* X-axis timestamps */}
                  {[
                    { x: 52, t: '00:00' },
                    { x: 108, t: '03:00' },
                    { x: 164, t: '06:00' },
                    { x: 220, t: '09:00' },
                    { x: 276, t: '12:00' },
                    { x: 332, t: '15:00' },
                    { x: 388, t: '18:00' },
                    { x: 438, t: '21:00' },
                  ].map((col) => (
                    <text
                      key={col.t}
                      x={col.x}
                      y="142"
                      fill="#64748B"
                      fontSize="10"
                      textAnchor="middle"
                      fontFamily="JetBrains Mono"
                    >
                      {col.t}
                    </text>
                  ))}
                </svg>
              </div>
            </div>

            {/* Right 5 cols: Latest Assessments with Real Crypto Icons */}
            <div className="md:col-span-5 rounded-xl bg-slate-950/75 border border-slate-800/90 p-4 flex flex-col justify-between">
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-sm font-display font-bold text-white">
                  Latest Assessments
                </span>
                <span className="text-[10px] font-mono text-emerald-400">Live Prices</span>
              </div>
              <div className="space-y-2.5">
                {featuredPools.map((pool) => (
                  <button
                    key={pool.id}
                    type="button"
                    onClick={() => onNavigateTerminal(pool.pair)}
                    className="w-full text-left rounded-xl bg-slate-900/80 hover:bg-slate-800/90 border border-slate-800 hover:border-cyan-500/40 px-3 py-2.5 flex items-center justify-between transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="relative flex items-center shrink-0">
                        <img
                          src={pool.coinIcon}
                          alt={pool.baseToken}
                          className="w-7 h-7 rounded-full border border-cyan-400/50 bg-slate-950 object-cover"
                        />
                        <img
                          src={pool.quoteIcon}
                          alt={pool.quoteToken}
                          className="w-4 h-4 rounded-full border border-slate-700 bg-slate-950 object-cover -ml-2 mt-3"
                        />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-bold text-white">{pool.pair}</span>
                          <span className="text-[11px] font-mono text-cyan-300">
                            {formatTokenPriceUsd(pool.priceUsd)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-[11px] text-slate-400 font-mono">
                            Risk: <strong className="text-slate-200">{pool.riskScore.toFixed(1)}</strong>
                          </span>
                          <span
                            className={`px-1.5 py-0.2 rounded text-[10px] font-mono font-semibold ${
                              pool.status === 'SAFE'
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                                : pool.status === 'WATCH'
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                                  : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                            }`}
                          >
                            {pool.status}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div
                        className={`text-[11px] font-mono font-bold ${
                          pool.change24hPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {pool.change24hPct >= 0 ? `+${pool.change24hPct}%` : `${pool.change24hPct}%`}
                      </div>
                      <span className="text-[10px] font-mono text-slate-400">{pool.dex}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right: Platform Capabilities (4 cols) */}
        <div className="lg:col-span-4 molt-card-purple p-5 sm:p-6 flex flex-col justify-between space-y-4">
          <div className="flex items-center gap-2.5 border-b border-slate-800/80 pb-3.5">
            <Layers className="w-5 h-5 text-cyan-400" />
            <h2 className="font-display font-bold text-lg text-white">Platform Capabilities</h2>
          </div>

          <div className="space-y-3 flex-1 flex flex-col justify-center">
            {capabilities.map((cap) => {
              const Icon = cap.icon;
              const isExpanded = selectedCapability === cap.id;
              return (
                <div key={cap.id} className="space-y-1.5">
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedCapability(isExpanded ? null : cap.id)
                    }
                    className="bracket-card w-full text-left p-3.5 flex items-center justify-between gap-3 transition-all cursor-pointer"
                  >
                    <div className="bracket-tick bracket-tick-tl" />
                    <div className="bracket-tick bracket-tick-tr" />
                    <div className="bracket-tick bracket-tick-bl" />
                    <div className="bracket-tick bracket-tick-br" />
                    <div className="flex items-center gap-3.5">
                      {cap.id === 'sentinel-engine' ? (
                        <SentinelShieldBadge size="sm" />
                      ) : (
                        <div className="w-8 h-8 cyber-cut-sm bg-cyan-500/10 border border-cyan-400/30 flex items-center justify-center text-cyan-400 shrink-0">
                          <Icon className="w-4 h-4" />
                        </div>
                      )}
                      <div>
                        <div className="font-display font-bold text-sm text-white">{cap.title}</div>
                        <div className="text-xs text-slate-400 mt-0.5">{cap.subtitle}</div>
                      </div>
                    </div>
                    <ArrowRight
                      className={`w-4 h-4 text-slate-400 transition-transform ${
                        isExpanded ? 'rotate-90 text-cyan-300' : ''
                      }`}
                    />
                  </button>
                  {isExpanded && (
                    <div className="px-3.5 py-2.5 cyber-cut-sm bg-slate-950/90 border border-cyan-500/30 text-xs text-slate-300 leading-relaxed">
                      {cap.detail}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* 6-STAGE INTERACTIVE SENTINEL ARCHITECTURE SHOWCASE (Synced with github.com/theheiszt/moltbook-alpha) */}
      <section
        data-testid="sentinel-architecture-showcase"
        className="molt-card p-5 sm:p-6 space-y-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <div className="space-y-1">
            <div className="text-[11px] font-mono uppercase tracking-wider text-cyan-400 flex items-center gap-2">
              <Globe className="w-3.5 h-3.5" />
              <span>6-STAGE AUTONOMOUS RISK &amp; VERIFICATION PIPELINE</span>
            </div>
            <h2 className="font-display font-extrabold text-xl sm:text-2xl text-white">
              Inside the MoltAlpha Sentinel Architecture
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
            {SENTINEL_SHOWCASE_STAGES.map((stage) => (
              <button
                key={stage.step}
                type="button"
                onClick={() => setActiveShowcaseStage(stage.step)}
                className={`cyber-cut-sm px-2.5 py-1 border cursor-pointer ${
                  activeShowcaseStage === stage.step
                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold'
                    : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                }`}
              >
                0{stage.step}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left 5 cols: 6 Stepped Narrative Cards with Corner Brackets */}
          <div className="lg:col-span-5 space-y-2.5">
            {SENTINEL_SHOWCASE_STAGES.map((stage) => {
              const isSelected = stage.step === activeShowcaseStage;
              return (
                <button
                  key={stage.step}
                  type="button"
                  onClick={() => setActiveShowcaseStage(stage.step)}
                  className={`bracket-card w-full text-left p-3.5 transition-all cursor-pointer ${
                    isSelected
                      ? 'border-cyan-400 bg-slate-900/95 shadow-[0_0_20px_rgba(6,182,212,0.16)]'
                      : 'opacity-80 hover:opacity-100'
                  }`}
                >
                  <div className="bracket-tick bracket-tick-tl" />
                  <div className="bracket-tick bracket-tick-tr" />
                  <div className="bracket-tick bracket-tick-bl" />
                  <div className="bracket-tick bracket-tick-br" />

                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span
                      className={`text-[10px] font-mono uppercase tracking-wider font-semibold flex items-center gap-1.5 ${stage.colorClass}`}
                    >
                      <span className={`w-1.5 h-1.5 inline-block ${stage.dotClass}`} />
                      <span>{stage.tag}</span>
                    </span>
                    <span className="text-[10px] font-mono text-slate-500">{stage.badge}</span>
                  </div>

                  <div className="font-display font-bold text-sm text-white flex items-center justify-between">
                    <span>{stage.title}</span>
                    <span className="text-cyan-400 text-xs font-mono">→</span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Right 7 cols: Pinned Stage Telemetry & Official Showcase Visual */}
          <div className="lg:col-span-7 molt-card-purple p-4 sm:p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className={`text-xs font-mono font-bold ${currentStage.colorClass}`}>
                  {currentStage.tag}
                </div>
                <h3 className="font-display font-extrabold text-lg sm:text-xl text-white mt-0.5">
                  {currentStage.title}
                </h3>
              </div>
              <span className="text-xs font-mono text-slate-400">{currentStage.badge}</span>
            </div>

            <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
              {currentStage.description}
            </p>

            <div className="bg-slate-950 border border-slate-800 p-2 overflow-hidden">
              <img
                src={currentStage.imageSrc}
                alt={currentStage.imageAlt}
                className="w-full max-h-[340px] object-contain mx-auto bg-slate-950"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-cyan-300">
                {currentStage.metrics.map((m) => (
                  <span key={m}>{m}</span>
                ))}
              </div>

              <code className="text-[11px] font-mono text-slate-300 bg-black/80 border border-slate-800 px-2.5 py-1">
                {currentStage.cliCommand}
              </code>
            </div>
          </div>
        </div>
      </section>

      {/* PUBLIC EVALUATION VS. PAID EXECUTION MATRIX & GATEWAY DISCOVERY */}
      <section className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
        <div className="lg:col-span-7 molt-card p-5 space-y-3.5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <FileCode2 className="w-5 h-5 text-cyan-400" />
              <h3 className="font-display font-bold text-base sm:text-lg text-white">
                Public Evaluation vs. Paid Execution Matrix
              </h3>
            </div>
            <span className="text-xs font-mono text-emerald-400">0-Credit Discovery</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="py-2 pr-3">Resource / Capability</th>
                  <th className="py-2 px-2">Public</th>
                  <th className="py-2 px-2">Paid</th>
                  <th className="py-2 pl-2">Endpoint / Location</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70 text-slate-200">
                <tr>
                  <td className="py-2 pr-3 font-sans font-semibold text-white">
                    Gateway Discovery &amp; Capabilities
                  </td>
                  <td className="py-2 px-2 text-emerald-400 font-bold">Yes</td>
                  <td className="py-2 px-2 text-emerald-400 font-bold">Yes</td>
                  <td className="py-2 pl-2 text-cyan-300">GET /gateway.json · /v1/capabilities</td>
                </tr>
                <tr>
                  <td className="py-2 pr-3 font-sans font-semibold text-white">
                    Sample Ed25519 Briefing &amp; Public Keys
                  </td>
                  <td className="py-2 px-2 text-emerald-400 font-bold">Yes</td>
                  <td className="py-2 px-2 text-emerald-400 font-bold">Yes</td>
                  <td className="py-2 pl-2 text-cyan-300">GET /api/v1/witness/public-keys</td>
                </tr>
                <tr>
                  <td className="py-2 pr-3 font-sans font-semibold text-white">
                    Live Sentinel Telemetry &amp; Arbitrage
                  </td>
                  <td className="py-2 px-2 text-slate-500">Demo</td>
                  <td className="py-2 px-2 text-emerald-400 font-bold">Yes</td>
                  <td className="py-2 pl-2 text-cyan-300">GET /v1/sentinel/* (X-API-Key)</td>
                </tr>
                <tr>
                  <td className="py-2 pr-3 font-sans font-semibold text-white">
                    Sniper Bot &amp; Metal X DEX Studio
                  </td>
                  <td className="py-2 px-2 text-slate-500">No</td>
                  <td className="py-2 px-2 text-emerald-400 font-bold">Members</td>
                  <td className="py-2 pl-2 text-cyan-300">POST /api/v1/automation/bots</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="lg:col-span-5 molt-card-purple p-5 flex flex-col justify-between space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="font-display font-bold text-base text-white">
                Dynamic Gateway &amp; Multi-Rail Tiers
              </span>
              <span className="text-xs font-mono text-cyan-300">v1.2.0 Online</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Clients resolve active ingress endpoints dynamically via{' '}
              <code className="text-cyan-300">/gateway.json</code>. Settle non-expiring query
              credits via <strong>Zero-Fee Nano (XNO)</strong> from <strong>$0.25</strong> (25
              queries) or <strong>Solana USDC/SOL</strong> from <strong>$1.00</strong> (150
              queries).
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2.5 font-mono text-xs">
            <div className="p-2.5 bg-slate-950/90 border border-slate-800">
              <div className="text-cyan-300 font-bold">tier_micro · $0.25</div>
              <div className="text-[11px] text-slate-400">25 queries · Nano / SOL / USDC</div>
            </div>
            <div className="p-2.5 bg-slate-950/90 border border-slate-800">
              <div className="text-cyan-300 font-bold">tier_starter · $1.00</div>
              <div className="text-[11px] text-slate-400">150 queries · Non-expiring</div>
            </div>
            <div className="p-2.5 bg-slate-950/90 border border-slate-800">
              <div className="text-purple-300 font-bold">tier_pro · $5.00</div>
              <div className="text-[11px] text-slate-400">1,500 queries · Sentinel Member</div>
            </div>
            <div className="p-2.5 bg-slate-950/90 border border-slate-800">
              <div className="text-emerald-300 font-bold">tier_premium · $20.00</div>
              <div className="text-[11px] text-slate-400">10,000 queries · 30d Pro</div>
            </div>
          </div>
        </div>
      </section>

      {/* BOTTOM FULL-WIDTH TRUST BANNER */}
      <section className="molt-card cyber-ruler-left p-5 sm:px-7 sm:py-5 flex flex-col xl:flex-row items-center justify-between gap-6">
        <div className="flex flex-col sm:flex-row items-center gap-5 text-center sm:text-left">
          <VerifiedCubeBadge />
          <div className="space-y-1 max-w-xl">
            <h3 className="font-display font-extrabold text-xl text-white">
              Verifiable. Reproducible. Trusted.
            </h3>
            <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
              Each analysis can be independently verified with a cryptographic signature, providing
              provable integrity for your agents, bots and trading systems.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-6">
          <button
            type="button"
            onClick={() => onNavigateTerminal('POPCAT/SOL')}
            className="cyber-btn-ghost px-5 py-2.5 text-xs font-mono uppercase tracking-wider text-cyan-200 inline-flex items-center gap-2 transition-colors cursor-pointer"
          >
            <span>See Verification Example</span>
            <ArrowRight className="w-4 h-4 text-cyan-400" />
          </button>

          <div className="flex items-center gap-6 border-l border-slate-800 pl-6">
            <div className="flex items-center gap-2.5">
              <Layers className="w-5 h-5 text-cyan-400" />
              <div>
                <div className="font-display font-extrabold text-lg text-white tabular-nums">
                  10,482
                </div>
                <div className="text-[11px] text-slate-400">Pools Monitored</div>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <ShieldCheck className="w-5 h-5 text-emerald-400" />
              <div>
                <div className="font-display font-extrabold text-lg text-white tabular-nums">
                  99.98%
                </div>
                <div className="text-[11px] text-slate-400">Uptime</div>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <Zap className="w-5 h-5 text-cyan-400" />
              <div>
                <div className="font-display font-extrabold text-lg text-white tabular-nums">
                  &lt; 250 ms
                </div>
                <div className="text-[11px] text-slate-400">API Response</div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};
