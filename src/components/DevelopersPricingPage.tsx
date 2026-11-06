import React, { useState } from 'react';
import {
  Code2,
  Layers,
  Gauge,
  Box,
  Check,
  Copy,
  CheckCircle2,
  Play,
  BookOpen,
  Rocket,
  ArrowRight,
  Sparkles,
  Star,
  Building2,
  X,
} from 'lucide-react';
import { IsometricChipGraphic } from './IsometricChipGraphic';
import {
  PaymentRail,
  PricingTierName,
  calculateMultiRailQuote,
} from '../utils/cryptoEngine';

interface DevelopersPricingPageProps {
  currentSlot: number;
  userCredits: number;
  onPurchaseCredits: (tier: PricingTierName, rail: PaymentRail) => Promise<void>;
  onNavigateTerminal: () => void;
}

export const DevelopersPricingPage: React.FC<DevelopersPricingPageProps> = ({
  currentSlot,
  userCredits,
  onPurchaseCredits,
  onNavigateTerminal,
}) => {
  const [codeTab, setCodeTab] = useState<'cURL' | 'Python' | 'TypeScript'>('cURL');
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [selectedRail, setSelectedRail] = useState<PaymentRail>('SOL');
  const [checkoutTier, setCheckoutTier] = useState<PricingTierName | null>(null);
  const [isSettling, setIsSettling] = useState(false);
  const [settlementSuccess, setSettlementSuccess] = useState<string | null>(null);
  const [activeDocModal, setActiveDocModal] = useState<string | null>(null);

  const codeSnippets: Record<'cURL' | 'Python' | 'TypeScript', string> = {
    cURL: `curl -X GET \\
  "https://api.moltalpha.dev/v1/pools/risk" \\
  -H "Authorization: Bearer $MOLT_API_KEY" \\
  -H "Accept: application/json" \\
  --data-urlencode "pool=BCnkYex2...Zq9"`,
    Python: `import requests

resp = requests.get(
    "https://api.moltalpha.dev/v1/pools/risk",
    headers={"Authorization": "Bearer mk_live_9f8a..."},
    params={"pool": "BCnkYex2...Zq9", "verify_ed25519": True}
)
print(resp.json()["witness_hash"])`,
    TypeScript: `import { MoltAlphaClient } from "@moltalpha/sdk";

const client = new MoltAlphaClient({ apiKey: process.env.MOLT_API_KEY });
const assessment = await client.pools.getRisk("BCnkYex2...Zq9");
console.log(assessment.risk_score, assessment.signature);`,
  };

  const jsonResponseText = `{
  "pool": "BCnkYex2...Zq9",
  "risk_score": 7.42,
  "risk_level": "SAFE",
  "liquidity_usd": "2482000.00",
  "verified": true,
  "witness_hash": "0x7a4e...c29f",
  "signature": "ed25519:6Fb8...M3k7"
}`;

  const handleCopy = (text: string, type: 'code' | 'json') => {
    navigator.clipboard?.writeText(text);
    if (type === 'code') {
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 1800);
    } else {
      setCopiedJson(true);
      setTimeout(() => setCopiedJson(false), 1800);
    }
  };

  const handleConfirmPurchase = async () => {
    if (!checkoutTier) return;
    setIsSettling(true);
    try {
      await onPurchaseCredits(checkoutTier, selectedRail);
      const quote = calculateMultiRailQuote(checkoutTier, selectedRail);
      setSettlementSuccess(
        `Settled ${quote.railAmountFormatted} via ${selectedRail} rail · +${quote.creditsToGrant.toLocaleString()} API credits added (Tx: ${quote.txHash.slice(0, 16)}...)`
      );
      setTimeout(() => {
        setCheckoutTier(null);
        setSettlementSuccess(null);
      }, 2200);
    } finally {
      setIsSettling(false);
    }
  };

  const activeQuote = checkoutTier ? calculateMultiRailQuote(checkoutTier, selectedRail) : null;

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 pt-6 pb-16 space-y-6">
      {/* TOP HERO & CODE PLAYGROUND SECTION (open unframed hero, no middle Neon Data Core box) */}
      <section className="py-4 sm:py-6 px-1 grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        {/* Left 5 columns: Build with MoltAlpha */}
        <div className="lg:col-span-5 space-y-4">
          <div className="cyber-cut-sm inline-flex items-center gap-2 px-3.5 py-1 border border-cyan-400/50 bg-cyan-950/40 text-cyan-300 text-xs font-mono uppercase tracking-wider">
            <span className="w-1.5 h-1.5 bg-cyan-400 shrink-0" />
            <span>&lt;/&gt; DEVELOPERS &amp; PRICING PORTAL</span>
          </div>

          <h1 className="font-display font-extrabold text-4xl sm:text-5xl leading-[1.08] tracking-tight drop-shadow-[0_4px_20px_rgba(0,0,0,0.65)]">
            <span className="block text-white">Build with</span>
            <span className="block molt-text-gradient">MoltAlpha</span>
          </h1>

          <p className="text-slate-200 text-sm sm:text-base leading-relaxed">
            A verifiable, credit-based API for Solana DEX intelligence, risk assessment, and agent
            workflows.
          </p>

          <ul className="space-y-2.5 pt-1 text-xs sm:text-sm text-slate-200">
            <li className="flex items-center gap-2.5">
              <Code2 className="w-4 h-4 text-cyan-400 shrink-0" />
              <span>REST API for DEX data, risk, and market intelligence</span>
            </li>
            <li className="flex items-center gap-2.5">
              <Layers className="w-4 h-4 text-cyan-400 shrink-0" />
              <span>Cryptographic verification (Ed25519)</span>
            </li>
            <li className="flex items-center gap-2.5">
              <Gauge className="w-4 h-4 text-cyan-400 shrink-0" />
              <span>Rate limits &amp; credit metering for predictable scale</span>
            </li>
            <li className="flex items-center gap-2.5">
              <Box className="w-4 h-4 text-cyan-400 shrink-0" />
              <span>Official SDKs (Python, TypeScript) for fast integration</span>
            </li>
          </ul>
        </div>

        {/* Right 7 columns: Code Snippet + JSON Response Card */}
        <div className="lg:col-span-7 space-y-3">
          <div className="molt-card-purple p-4 grid grid-cols-1 sm:grid-cols-12 gap-3.5">
            {/* Code Request Panel */}
            <div className="sm:col-span-6 bracket-card p-3.5 flex flex-col justify-start">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="flex items-center justify-between gap-1 border-b border-slate-800 pb-2 mb-2.5">
                <div className="flex items-center gap-1">
                  {(['cURL', 'Python', 'TypeScript'] as const).map((tab) => (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => setCodeTab(tab)}
                      className={`cyber-cut-sm px-2.5 py-1 text-xs font-mono transition-colors cursor-pointer ${
                        codeTab === tab
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/50 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => handleCopy(codeSnippets[codeTab], 'code')}
                  aria-label="Copy request code"
                  className="text-slate-400 hover:text-cyan-300 p-1 cursor-pointer"
                >
                  {copiedCode ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
              <pre className="text-[11px] font-mono text-cyan-200 whitespace-pre-wrap break-words leading-relaxed">
                <code>{codeSnippets[codeTab]}</code>
              </pre>
            </div>

            {/* JSON Response Panel */}
            <div className="sm:col-span-6 bracket-card p-3.5 flex flex-col justify-start">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="flex items-center justify-between gap-2 border-b border-slate-800 pb-2 mb-2.5">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>JSON Response</span>
                </div>
                <button
                  type="button"
                  onClick={() => handleCopy(jsonResponseText, 'json')}
                  aria-label="Copy JSON response"
                  className="text-slate-400 hover:text-cyan-300 p-1 cursor-pointer"
                >
                  {copiedJson ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
              <pre className="text-[11px] font-mono text-emerald-300 whitespace-pre-wrap break-words leading-relaxed">
                <code>{jsonResponseText}</code>
              </pre>
            </div>
          </div>

          {/* 4 Action Buttons underneath Code Playground */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onNavigateTerminal}
              className="molt-btn-cyan px-4 py-2.5 text-xs inline-flex items-center gap-2 cursor-pointer"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Get Started</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setActiveDocModal('API Docs — Endpoint Reference')}
              className="cyber-btn-ghost px-4 py-2.5 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-2 cursor-pointer"
            >
              <BookOpen className="w-3.5 h-3.5 text-cyan-400" />
              <span>API Docs</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveDocModal('Official SDKs — Python & TypeScript')}
              className="cyber-btn-ghost px-4 py-2.5 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-2 cursor-pointer"
            >
              <Code2 className="w-3.5 h-3.5 text-cyan-400" />
              <span>SDKs</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveDocModal('Agent Workflow Examples')}
              className="cyber-btn-ghost px-4 py-2.5 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-2 cursor-pointer"
            >
              <Box className="w-3.5 h-3.5 text-cyan-400" />
              <span>Examples</span>
            </button>
          </div>
        </div>
      </section>

      {/* MIDDLE SECTION: PREPAID API CREDITS & 4 PRICING CARDS matching Image 3 */}
      <section className="molt-card cyber-ruler-left p-6 sm:p-7">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
          {/* Left 4 columns: Prepaid API Credits overview + Multi-Rail selector */}
          <div className="lg:col-span-4 flex flex-col justify-between space-y-5 pr-2">
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-400">
                  <Layers className="w-5 h-5" />
                </div>
                <div>
                  <h2 className="font-display font-extrabold text-2xl text-white">
                    Prepaid API Credits
                  </h2>
                  <p className="text-xs text-slate-300">
                    Simple, non-subscription credits. Pay once, use anytime.
                  </p>
                </div>
              </div>

              <ul className="space-y-2.5 pt-2 text-sm text-slate-200">
                <li className="flex items-center gap-2.5">
                  <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Non-subscription (no recurring billing)</span>
                </li>
                <li className="flex items-center gap-2.5">
                  <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Non-expiring credits (use at your pace)</span>
                </li>
                <li className="flex items-center gap-2.5">
                  <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Pay with SOL / USDC / Nano</span>
                </li>
              </ul>
            </div>

            {/* Active Operator Credit Balance & Multi-Rail Selector */}
            <div className="space-y-3">
              <div className="rounded-xl bg-slate-950/80 border border-cyan-500/25 px-3.5 py-2.5 flex items-center justify-between text-xs">
                <span className="text-slate-400">Your Active Balance:</span>
                <span className="font-mono font-bold text-cyan-300 tabular-nums">
                  {userCredits.toLocaleString()} Credits
                </span>
              </div>

              <div className="rounded-xl bg-slate-950/90 border border-slate-800 px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-medium text-slate-300">Payment Rails:</span>
                <div className="flex items-center gap-1.5">
                  {(['SOL', 'USDC', 'Nano'] as PaymentRail[]).map((rail) => (
                    <button
                      key={rail}
                      type="button"
                      onClick={() => setSelectedRail(rail)}
                      className={`px-3 py-1 rounded-full text-xs font-mono font-semibold transition-all cursor-pointer ${
                        selectedRail === rail
                          ? 'bg-cyan-500/25 text-cyan-200 border border-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.35)]'
                          : 'bg-slate-900 text-slate-400 border border-slate-700 hover:text-slate-200'
                      }`}
                    >
                      {rail}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Right 8 columns: 4 Pricing Cards (Micro, Starter, Pro POPULAR, Enterprise) */}
          <div className="lg:col-span-8 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {/* Micro */}
            <div className="bracket-card p-5 flex flex-col justify-between space-y-5">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-tr" />
              <div className="bracket-tick bracket-tick-bl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-white font-display font-bold text-lg">
                  <Layers className="w-4 h-4 text-cyan-400" />
                  <span>Micro</span>
                </div>
                <div className="font-display font-extrabold text-3xl text-white tabular-nums">
                  $0.25
                </div>
                <div className="text-sm text-slate-300 font-medium">25 API queries</div>
                <ul className="space-y-2 pt-2 text-xs text-slate-300 border-t border-slate-800/80">
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Non-expiring credits</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Full API access</span>
                  </li>
                </ul>
              </div>
              <button
                type="button"
                onClick={() => setCheckoutTier('Micro')}
                className="cyber-btn-ghost w-full py-2.5 px-4 text-xs font-mono uppercase tracking-wider text-white inline-flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <span>Buy Credits</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Starter */}
            <div className="bracket-card p-5 flex flex-col justify-between space-y-5">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-tr" />
              <div className="bracket-tick bracket-tick-bl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-white font-display font-bold text-lg">
                  <Layers className="w-4 h-4 text-cyan-400" />
                  <span>Starter</span>
                </div>
                <div className="font-display font-extrabold text-3xl text-white tabular-nums">
                  $1
                </div>
                <div className="text-sm text-slate-300 font-medium">150 API queries</div>
                <ul className="space-y-2 pt-2 text-xs text-slate-300 border-t border-slate-800/80">
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Non-expiring credits</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Full API access</span>
                  </li>
                </ul>
              </div>
              <button
                type="button"
                onClick={() => setCheckoutTier('Starter')}
                className="cyber-btn-ghost w-full py-2.5 px-4 text-xs font-mono uppercase tracking-wider text-white inline-flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <span>Buy Credits</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Pro (POPULAR) */}
            <div className="molt-card-popular p-5 flex flex-col justify-between space-y-5">
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 text-white font-display font-bold text-lg">
                    <Star className="w-4 h-4 text-cyan-400" />
                    <span>Pro</span>
                  </div>
                  <span className="cyber-cut-sm px-2 py-0.5 text-[10px] font-mono font-bold uppercase bg-gradient-to-r from-cyan-400 to-purple-400 text-slate-950">
                    POPULAR
                  </span>
                </div>
                <div className="font-display font-extrabold text-3xl text-white tabular-nums">
                  $5
                </div>
                <div className="text-sm text-slate-200 font-medium">1,500 API queries</div>
                <ul className="space-y-2 pt-2 text-xs text-slate-200 border-t border-cyan-500/30">
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Non-expiring credits</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Full API access</span>
                  </li>
                </ul>
              </div>
              <button
                type="button"
                onClick={() => setCheckoutTier('Pro')}
                className="molt-btn-cyan w-full py-2.5 px-4 text-xs font-bold inline-flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <span>Buy Credits</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Enterprise */}
            <div className="bracket-card p-5 flex flex-col justify-between space-y-5">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-tr" />
              <div className="bracket-tick bracket-tick-bl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-white font-display font-bold text-lg">
                  <Building2 className="w-4 h-4 text-cyan-400" />
                  <span>Enterprise</span>
                </div>
                <div className="font-display font-extrabold text-3xl text-white">Custom</div>
                <div className="text-xs text-slate-300 font-medium">
                  Higher volumes &amp; agent access
                </div>
                <ul className="space-y-2 pt-2 text-xs text-slate-300 border-t border-slate-800/80">
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Volume pricing</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>SLA &amp; priority support</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Custom integrations</span>
                  </li>
                </ul>
              </div>
              <button
                type="button"
                onClick={() => setCheckoutTier('Enterprise')}
                className="cyber-btn-ghost w-full py-2.5 px-4 text-xs font-mono uppercase tracking-wider text-white inline-flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <span>Contact Us</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* BOTTOM 4 QUICK-LINK CARDS matching Image 3 */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            title: 'Quickstart',
            desc: 'Get up and running in minutes with a simple API call.',
            icon: Rocket,
          },
          {
            title: 'API Docs',
            desc: 'Complete reference for endpoints, parameters, and responses.',
            icon: BookOpen,
          },
          {
            title: 'SDKs',
            desc: 'Official SDKs for Python and TypeScript with examples and best practices.',
            icon: Layers,
          },
          {
            title: 'Examples',
            desc: 'Real-world integration examples for risk, pools, and agent workflows.',
            icon: Code2,
          },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.title}
              type="button"
              onClick={() => setActiveDocModal(item.title)}
              className="molt-card rounded-2xl p-5 text-left flex items-center justify-between gap-4 hover:border-cyan-400/60 transition-colors cursor-pointer"
            >
              <div className="flex items-start gap-3.5">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-400/30 flex items-center justify-center text-cyan-400 shrink-0 mt-0.5">
                  <Icon className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-display font-bold text-base text-white">{item.title}</div>
                  <p className="text-xs text-slate-300 mt-1 leading-relaxed">{item.desc}</p>
                </div>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-400 shrink-0" />
            </button>
          );
        })}
      </section>

      {/* MULTI-RAIL SETTLEMENT CHECKOUT MODAL */}
      {checkoutTier && activeQuote && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="checkout-modal-title"
        >
          <div className="molt-card-popular rounded-2xl max-w-md w-full p-6 space-y-5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-cyan-400" />
                <h3 id="checkout-modal-title" className="font-display font-bold text-lg text-white">
                  Multi-Rail Credit Settlement — {checkoutTier} Tier
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setCheckoutTier(null)}
                aria-label="Close settlement dialog"
                className="text-slate-400 hover:text-white p-1 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              <label className="block text-xs text-slate-300 font-medium">
                Select Settlement Rail (Solana USDC/SOL &amp; Zero-Fee Nano):
              </label>
              <div className="grid grid-cols-3 gap-2">
                {(['SOL', 'USDC', 'Nano'] as PaymentRail[]).map((rail) => (
                  <button
                    key={rail}
                    type="button"
                    onClick={() => setSelectedRail(rail)}
                    className={`py-2 px-3 rounded-xl text-xs font-mono font-bold border transition-all cursor-pointer ${
                      selectedRail === rail
                        ? 'bg-cyan-500/25 border-cyan-400 text-cyan-200'
                        : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
                    }`}
                  >
                    {rail === 'Nano' ? 'Nano (0 Fee)' : `Solana ${rail}`}
                  </button>
                ))}
              </div>

              <div className="rounded-xl bg-slate-950/90 border border-slate-800 p-4 space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-slate-400">Prepaid Credits:</span>
                  <span className="text-white font-bold">
                    +{activeQuote.creditsToGrant.toLocaleString()} API Queries
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Settlement Amount:</span>
                  <span className="text-cyan-300 font-bold">{activeQuote.railAmountFormatted}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Network Rail Fee:</span>
                  <span className="text-emerald-400">{activeQuote.networkFeeFormatted}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Target Slot:</span>
                  <span className="text-slate-300">{currentSlot.toLocaleString()}</span>
                </div>
              </div>
            </div>

            {settlementSuccess ? (
              <div className="rounded-xl bg-emerald-500/20 border border-emerald-400/50 p-3.5 text-xs text-emerald-200 font-mono">
                ✓ {settlementSuccess}
              </div>
            ) : (
              <div className="flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setCheckoutTier(null)}
                  className="px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-xs font-semibold text-slate-300 hover:text-white cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isSettling}
                  onClick={handleConfirmPurchase}
                  className="molt-btn-gradient px-5 py-2.5 rounded-xl text-xs font-bold cursor-pointer"
                >
                  {isSettling ? 'Verifying Proof...' : `Confirm & Settle (${activeQuote.railAmountFormatted})`}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* DOCUMENTATION / SDK PREVIEW MODAL */}
      {activeDocModal && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="molt-card rounded-2xl max-w-lg w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-display font-bold text-lg text-white">{activeDocModal}</h3>
              <button
                type="button"
                onClick={() => setActiveDocModal(null)}
                aria-label="Close documentation modal"
                className="text-slate-400 hover:text-white p-1 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
              All MoltAlpha endpoints return RFC 8785 canonical JSON payloads accompanied by an
              Ed25519 signature header (<code className="text-cyan-300">X-Molt-Witness-Sig</code>)
              and SHA-256 digest (<code className="text-cyan-300">X-Molt-Witness-Hash</code>).
            </p>
            <pre className="rounded-xl bg-slate-950 border border-slate-800 p-3.5 text-xs font-mono text-cyan-200 overflow-x-auto">
              <code>{`GET /v1/pools/risk?pool=POPCAT/SOL
GET /v1/witness/verify?slot=${currentSlot}
POST /v1/settlements/credit (Rails: SOL | USDC | Nano)`}</code>
            </pre>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setActiveDocModal(null)}
                className="molt-btn-cyan px-4 py-2 rounded-xl text-xs font-bold cursor-pointer"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
