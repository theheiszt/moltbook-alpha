import React, { useState, useMemo, useEffect } from 'react';
import {
  Play,
  Code2,
  CheckCircle2,
  Layers,
  AlertTriangle,
  ShieldCheck,
  BarChart3,
  Bell,
  Info,
  Search,
  Star,
  Copy,
  Check,
  ExternalLink,
  Lock,
  KeyRound,
  Activity,
  Pause,
  RefreshCw,
  ArrowRight,
  Hash,
  FileCode2,
  PenTool,
  ChevronDown,
  ChevronUp,
  Bot,
  Award,
  Fingerprint,
  FileCheck2,
} from 'lucide-react';
import {
  IsometricChipGraphic,
  SentinelShieldSvg,
} from './IsometricChipGraphic';
import {
  DexPool,
  RiskAlertItem,
  LiveTxFlowPacket,
  WitnessKeyRecord,
  buildWitnessAttestation,
  formatCompactUsd,
  formatTokenPriceUsd,
  getTokenIcon,
  getDexIcon,
  lookupAgentDossier,
  verifyDuesProofBirthCert,
} from '../utils/cryptoEngine';
import {
  validateSafeExternalUri,
  sanitizePlainText,
} from '../services/securityEngine';

interface SentinelTerminalPageProps {
  isAuthenticated: boolean;
  userDisplayName: string;
  onGoogleLogin: () => Promise<void>;
  onOperatorSessionLogin: () => void;
  pools: DexPool[];
  alerts: RiskAlertItem[];
  txPackets: LiveTxFlowPacket[];
  activeWitnessKey: WitnessKeyRecord;
  currentSlot: number;
  selectedPoolPair: string;
  onSelectPoolPair: (pair: string) => void;
  onToggleStarPool: (poolId: string) => void;
  onTriggerSimulatedAlert: () => void;
  onNavigateDevelopers: () => void;
  solPriceUsd?: number;
  marketProviderSummary?: string;
  lastMarketSync?: string;
  isSyncingMarket?: boolean;
  onRefreshMarketTelemetry?: () => void;
}

// Deterministic 16x6 Risk Heatmap grid matching Image 1
const HEATMAP_CELLS: number[][] = [
  [1, 2, 1, 2, 4, 2, 1, 1, 2, 3, 2, 1, 2, 1, 1, 2],
  [2, 1, 3, 2, 8, 9, 4, 2, 1, 2, 4, 3, 1, 2, 2, 1],
  [1, 2, 2, 5, 7, 6, 3, 1, 2, 5, 6, 2, 1, 1, 3, 2],
  [1, 1, 3, 4, 5, 3, 2, 2, 3, 8, 5, 2, 2, 1, 2, 1],
  [2, 2, 1, 2, 3, 2, 1, 1, 2, 4, 3, 1, 1, 2, 1, 1],
  [1, 1, 2, 1, 2, 1, 2, 1, 1, 2, 1, 2, 1, 1, 1, 2],
];

function getHeatmapCellColor(score: number): string {
  if (score >= 9) return 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.7)]';
  if (score >= 7) return 'bg-orange-500';
  if (score >= 5) return 'bg-amber-400';
  if (score >= 3) return 'bg-lime-400';
  return 'bg-emerald-500';
}

export const SentinelTerminalPage: React.FC<SentinelTerminalPageProps> = ({
  isAuthenticated,
  onGoogleLogin,
  onOperatorSessionLogin,
  pools,
  alerts,
  txPackets,
  activeWitnessKey,
  currentSlot,
  selectedPoolPair,
  onSelectPoolPair,
  onToggleStarPool,
  onTriggerSimulatedAlert,
  onNavigateDevelopers,
  solPriceUsd = 185.2,
  marketProviderSummary = 'Coinbase Exchange Live',
  lastMarketSync = 'Live',
  isSyncingMarket = false,
  onRefreshMarketTelemetry,
}) => {
  const [poolTab, setPoolTab] = useState<'ALL' | 'AT_RISK' | 'WATCH' | 'HIGH' | 'CRITICAL'>('ALL');
  const [timeframe, setTimeframe] = useState<'24h' | '7d' | '30d'>('24h');
  const [searchQuery, setSearchQuery] = useState('');
  const [dexFilter, setDexFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [categoryFilter, setCategoryFilter] = useState<string>('ALL');
  const [showTrends, setShowTrends] = useState(true);
  const [expandedPoolPair, setExpandedPoolPair] = useState<string | null>('POPCAT/SOL');
  const [witnessTab, setWitnessTab] = useState<'Verification' | 'Canonical JSON' | 'Signature (Raw)' | 'Details'>('Verification');
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [flowFilter, setFlowFilter] = useState<'ALL' | 'RISK' | 'WITNESS' | 'SETTLEMENT'>('ALL');
  const [isStreamPaused, setIsStreamPaused] = useState(false);
  const [selectedPacketId, setSelectedPacketId] = useState<string | null>(null);
  const [explorerModalOpen, setExplorerModalOpen] = useState(false);

  // Agent Credit Bureau & DuesProof BirthCert Lookup State
  const [agentSearchInput, setAgentSearchInput] = useState<string>('antigravityandrew');
  const [inspectedAgentHandle, setInspectedAgentHandle] = useState<string>('antigravityandrew');
  const [showBirthCertJson, setShowBirthCertJson] = useState<boolean>(false);
  const [birthCertVerificationState, setBirthCertVerificationState] = useState<
    'idle' | 'verified' | 'rejected'
  >('idle');

  useEffect(() => {
    setBirthCertVerificationState('idle');
  }, [inspectedAgentHandle]);

  const agentDossier = useMemo(
    () => lookupAgentDossier(inspectedAgentHandle),
    [inspectedAgentHandle]
  );

  const selectedPool = useMemo(
    () => pools.find((p) => p.pair === selectedPoolPair) || pools[2] || pools[0],
    [pools, selectedPoolPair]
  );

  const witnessAttestation = useMemo(
    () => buildWitnessAttestation(selectedPool, activeWitnessKey),
    [selectedPool, activeWitnessKey]
  );

  const filteredPools = useMemo(() => {
    return pools.filter((pool) => {
      if (poolTab === 'AT_RISK' && pool.riskScore < 5.0) return false;
      if (poolTab === 'WATCH' && pool.status !== 'WATCH') return false;
      if (poolTab === 'HIGH' && pool.status !== 'HIGH') return false;
      if (poolTab === 'CRITICAL' && pool.status !== 'CRITICAL') return false;
      if (dexFilter !== 'ALL' && pool.dex !== dexFilter) return false;
      if (statusFilter !== 'ALL' && pool.status !== statusFilter) return false;
      if (categoryFilter !== 'ALL' && pool.category !== categoryFilter) return false;
      if (
        searchQuery.trim() &&
        !pool.pair.toLowerCase().includes(searchQuery.trim().toLowerCase()) &&
        !pool.dex.toLowerCase().includes(searchQuery.trim().toLowerCase()) &&
        !pool.poolAddress.toLowerCase().includes(searchQuery.trim().toLowerCase())
      ) {
        return false;
      }
      return true;
    });
  }, [pools, poolTab, dexFilter, statusFilter, categoryFilter, searchQuery]);

  const filteredTxPackets = useMemo(() => {
    return txPackets.filter((pkt) => {
      if (flowFilter === 'RISK') return pkt.status === 'CRITICAL' || pkt.status === 'HIGH';
      if (flowFilter === 'WITNESS') return pkt.flowType === 'WITNESS_ATTESTATION';
      if (flowFilter === 'SETTLEMENT') return pkt.flowType === 'RAIL_SETTLEMENT' || Boolean(pkt.rail);
      return true;
    });
  }, [txPackets, flowFilter]);

  const handleCopy = (label: string, value: string) => {
    navigator.clipboard?.writeText(value);
    setCopiedField(label);
    setTimeout(() => setCopiedField(null), 1600);
  };

  const handleSelectPresetAgent = (handle: string) => {
    setAgentSearchInput(handle);
    setInspectedAgentHandle(handle);
    setBirthCertVerificationState('idle');
  };

  const handleInspectAgentSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (agentSearchInput.trim()) {
      setInspectedAgentHandle(agentSearchInput.trim());
      setBirthCertVerificationState('idle');
    }
  };

  // LOGIN GATE FOR SENTINEL TAB
  if (!isAuthenticated) {
    return (
      <div className="max-w-[1360px] mx-auto px-4 sm:px-6 py-10">
        <div className="molt-card-purple cyber-ruler-left p-8 sm:p-10 max-w-2xl mx-auto text-center space-y-5 relative overflow-hidden">
          <div className="mx-auto w-40 h-40 molt-card p-2 relative bg-[#040814]">
            <div className="bracket-tick bracket-tick-tl" />
            <div className="bracket-tick bracket-tick-tr" />
            <div className="bracket-tick bracket-tick-bl" />
            <div className="bracket-tick bracket-tick-br" />
            <SentinelShieldSvg showWordmark className="w-full h-full" />
          </div>

          <div className="cyber-cut-sm inline-flex items-center gap-2 px-3.5 py-1 border border-cyan-400/50 bg-cyan-950/50 text-cyan-300 text-xs font-mono uppercase">
            <Lock className="w-3.5 h-3.5 text-cyan-400" />
            <span>SENTINEL CRYPTOGRAPHIC ACCESS REQUIRED</span>
          </div>

          <h1 className="font-display font-extrabold text-3xl sm:text-4xl text-white">
            Authenticate to Unlock Sentinel Terminal
          </h1>

          <p className="text-slate-300 text-sm sm:text-base leading-relaxed max-w-xl mx-auto">
            Access to real-time Solana DEX microstructure risk alerts, the live multi-rail
            transaction flow visualizer, Agent Credit Bureau &amp; DuesProof BirthCerts, and Ed25519
            state witness telemetry requires an authenticated operator session.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-left text-xs text-slate-300 pt-2">
            <div className="bracket-card p-3.5 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                <Bell className="w-3.5 h-3.5" />
                <span>Real-Time Risk Alerts</span>
              </div>
              <p className="text-slate-400">Instant LP drain, rug-pull, and MEV anomaly stream.</p>
            </div>
            <div className="bracket-card p-3.5 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5" />
                <span>Live Tx Flow Visualizer</span>
              </div>
              <p className="text-slate-400">Multi-DEX &amp; SOL/USDC/Nano settlement telemetry.</p>
            </div>
            <div className="bracket-card p-3.5 space-y-1">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>DuesProof &amp; Witnesses</span>
              </div>
              <p className="text-slate-400">Agent BirthCerts, RFC 8785 JSON &amp; SHA-256 proofs.</p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-3">
            <button
              type="button"
              onClick={onGoogleLogin}
              className="molt-btn-cyan w-full sm:w-auto px-6 py-3.5 text-xs sm:text-sm font-bold inline-flex items-center justify-center gap-2.5 cursor-pointer"
            >
              <ShieldCheck className="w-4 h-4" />
              <span>Sign In with Google (Firebase Auth)</span>
            </button>

            <button
              type="button"
              onClick={onOperatorSessionLogin}
              className="cyber-btn-ghost w-full sm:w-auto px-6 py-3.5 text-xs sm:text-sm font-mono uppercase tracking-wider text-cyan-200 inline-flex items-center justify-center gap-2 transition-colors cursor-pointer"
            >
              <KeyRound className="w-4 h-4 text-cyan-400" />
              <span>Verify Operator Passkey (Instant Session)</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1420px] mx-auto px-4 sm:px-6 pt-4 pb-16 space-y-5">
      {/* TOP SECTION OF SENTINEL TERMINAL — Compact, zero-black-gap layout */}
      <section className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-stretch">
        {/* Left 4 columns: Open Sentinel Terminal Hero + Frameless MoltAlpha Sentinel Shield */}
        <div className="xl:col-span-4 py-1 px-1 flex flex-col justify-between relative">
          <div className="space-y-3 z-10">
            <div className="flex flex-wrap items-center gap-2">
              <div className="cyber-cut-sm inline-flex items-center gap-2 px-3 py-1 border border-cyan-400/50 bg-cyan-950/50 text-cyan-300 text-[11px] font-mono uppercase tracking-wider">
                <span className="w-1.5 h-1.5 bg-cyan-400 shrink-0" />
                <span>&lt;/&gt; AUTONOMOUS MARKET INTELLIGENCE</span>
              </div>
              <span
                data-testid="sentinel-simulated-badge"
                className="cyber-cut-sm px-2.5 py-1 bg-amber-500/15 border border-amber-400/50 text-amber-300 text-[10px] font-mono font-bold uppercase"
              >
                SIMULATED DEMO TELEMETRY
              </span>
            </div>

            <h1 className="font-display font-extrabold text-3xl sm:text-4xl text-white tracking-tight drop-shadow-[0_4px_20px_rgba(0,0,0,0.65)]">
              Sentinel Terminal
            </h1>

            <p className="text-xs sm:text-sm text-slate-200 leading-relaxed max-w-md">
              Real-time DEX risk intelligence, live Coinbase Exchange telemetry, agent
              track-record verification, and Ed25519 witnesses for Solana.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center pt-0.5">
              <ul className="sm:col-span-7 space-y-1.5 text-xs text-slate-200">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>Pre-trade risk assessment</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>Coinbase Exchange live feed</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>Cryptographic witness verification</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>Agent Credit &amp; DuesProof BirthCert</span>
                </li>
              </ul>

              <div className="sm:col-span-5 flex justify-center">
                <IsometricChipGraphic compact variant="sentinel" />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-3 z-10">
            <button
              type="button"
              onClick={onTriggerSimulatedAlert}
              className="molt-btn-cyan px-4 py-2 text-xs inline-flex items-center gap-2 cursor-pointer"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Launch Analysis</span>
            </button>
            <button
              type="button"
              onClick={onNavigateDevelopers}
              className="cyber-btn-ghost px-4 py-2 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-2 transition-colors cursor-pointer"
            >
              <Code2 className="w-3.5 h-3.5 text-cyan-400" />
              <span>API Integration</span>
            </button>
          </div>
        </div>

        {/* Center 5 columns: 4 KPI Cards on top + Filled Risk Heatmap & Risk Distribution below */}
        <div className="xl:col-span-5 flex flex-col justify-between gap-3">
          {/* 4 KPI Cards Row with Mini Sparklines */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {/* Total Pools */}
            <div className="molt-card p-3 flex flex-col justify-between">
              <div className="flex items-center gap-1.5 text-[11px] text-slate-300 whitespace-nowrap">
                <Layers className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span>Total Pools</span>
              </div>
              <div className="font-display font-extrabold text-2xl text-white tabular-nums my-0.5">
                10,482
              </div>
              <div className="flex items-center justify-between gap-1 text-[10px] font-mono text-emerald-400">
                <span className="whitespace-nowrap">▲ +2.3% (24h)</span>
                <svg viewBox="0 0 44 14" className="w-10 h-3.5 shrink-0">
                  <polyline
                    fill="none"
                    stroke="#22D3EE"
                    strokeWidth="1.6"
                    points="1,11 10,8 18,10 27,5 35,6 43,2"
                  />
                </svg>
              </div>
            </div>

            {/* At-Risk Pools */}
            <div className="molt-card-purple p-3 flex flex-col justify-between">
              <div className="flex items-center gap-1.5 text-[11px] text-slate-300 whitespace-nowrap">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                <span>At-Risk Pools</span>
              </div>
              <div className="font-display font-extrabold text-2xl text-white tabular-nums my-0.5">
                {27 + (alerts.length - 5)}
              </div>
              <div className="flex items-center justify-between gap-1 text-[10px] font-mono text-emerald-400">
                <span className="whitespace-nowrap">▼ -14.3% (24h)</span>
                <svg viewBox="0 0 44 14" className="w-10 h-3.5 shrink-0">
                  <polyline
                    fill="none"
                    stroke="#F43F5E"
                    strokeWidth="1.6"
                    points="1,10 11,11 20,7 29,9 36,4 43,5"
                  />
                </svg>
              </div>
            </div>

            {/* Avg. Risk Score */}
            <div className="molt-card p-3 flex flex-col justify-between">
              <div className="flex items-center gap-1.5 text-[11px] text-slate-300 whitespace-nowrap">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span>Avg. Risk Score</span>
              </div>
              <div className="font-display font-extrabold text-2xl text-white tabular-nums my-0.5">
                04<span className="text-sm font-normal text-slate-400">/10</span>
              </div>
              <div className="flex items-center justify-between gap-1 text-[10px] font-mono text-emerald-400">
                <span className="whitespace-nowrap">▼ -0.7 (24h)</span>
                <svg viewBox="0 0 44 14" className="w-10 h-3.5 shrink-0">
                  <polyline
                    fill="none"
                    stroke="#38BDF8"
                    strokeWidth="1.6"
                    points="1,9 10,7 19,9 28,6 36,7 43,3"
                  />
                </svg>
              </div>
            </div>

            {/* 24h Volume */}
            <div className="molt-card p-3 flex flex-col justify-between">
              <div className="flex items-center gap-1.5 text-[11px] text-slate-300 whitespace-nowrap">
                <BarChart3 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span>24h Volume</span>
              </div>
              <div className="font-display font-extrabold text-2xl text-white tabular-nums my-0.5">
                $1.24B
              </div>
              <div className="flex items-center justify-between gap-1 text-[10px] font-mono text-emerald-400">
                <span className="whitespace-nowrap">▲ +4.7%</span>
                <svg viewBox="0 0 44 14" className="w-10 h-3.5 shrink-0">
                  <polyline
                    fill="none"
                    stroke="#C084FC"
                    strokeWidth="1.6"
                    points="1,12 10,10 19,8 28,9 36,4 43,2"
                  />
                </svg>
              </div>
            </div>
          </div>

          {/* Risk Heatmap + Risk Distribution Row — Filled edge-to-edge with zero empty black space */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-3 flex-1">
            {/* Risk Heatmap (7 cols) */}
            <div className="md:col-span-7 molt-card p-3.5 flex flex-col justify-between gap-2.5">
              <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                <div className="flex items-center gap-1.5 font-display font-bold text-sm text-white">
                  <span>Risk Heatmap</span>
                  <Info className="w-3.5 h-3.5 text-slate-400" />
                </div>
                <span className="text-[10px] font-mono text-cyan-300">Solana CLMM/AMM · 96 Bins</span>
              </div>

              <div className="flex items-center gap-3 py-1">
                {/* 16x6 Grid of interactive rounded-square cells */}
                <div className="grid grid-cols-16 gap-1.5 flex-1">
                  {HEATMAP_CELLS.flatMap((row, rIdx) =>
                    row.map((val, cIdx) => (
                      <button
                        key={`${rIdx}-${cIdx}`}
                        type="button"
                        onClick={() =>
                          onSelectPoolPair(
                            val >= 8 ? 'POPCAT/SOL' : val >= 7 ? 'WIF/SOL' : val >= 5 ? 'BONK/SOL' : 'RAY/SOL'
                          )
                        }
                        title={`Pool Cluster [${rIdx + 1},${cIdx + 1}] — Risk Score: ${val}/10`}
                        aria-label={`Heatmap cell row ${rIdx + 1} col ${cIdx + 1} risk ${val}`}
                        className={`heatmap-cell h-4.5 transition-transform hover:scale-125 cursor-pointer ${getHeatmapCellColor(
                          val
                        )}`}
                      />
                    ))
                  )}
                </div>

                {/* Legend matching Image 1 */}
                <div className="space-y-1 text-[10px] font-mono text-slate-300 shrink-0">
                  <div className="flex items-center gap-1.5">
                    <span className="heatmap-swatch w-2.5 h-2.5 bg-rose-500" />
                    <span>&ge; 09 Critical</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="heatmap-swatch w-2.5 h-2.5 bg-orange-500" />
                    <span>07 – 08 High</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="heatmap-swatch w-2.5 h-2.5 bg-amber-400" />
                    <span>05 – 06 Watch</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="heatmap-swatch w-2.5 h-2.5 bg-lime-400" />
                    <span>03 – 04 Low</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="heatmap-swatch w-2.5 h-2.5 bg-emerald-500" />
                    <span>00 – 02 Safe</span>
                  </div>
                </div>
              </div>

              {/* Bottom Microstructure Summary Strip so there is zero empty black space */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80 text-[10px] font-mono">
                <div className="bg-slate-950/80 px-2.5 py-1 border border-slate-800/90 flex items-center gap-1.5">
                  <span className="text-slate-400">Target:</span>
                  <span className="text-cyan-300 font-bold">{selectedPool.pair}</span>
                </div>
                <div className="bg-slate-950/80 px-2.5 py-1 border border-slate-800/90 flex items-center gap-2">
                  <span className="text-slate-400">
                    HHI: <strong className="text-white">{selectedPool.lpConcentrationHhi}</strong>
                  </span>
                  <span className="text-slate-600">·</span>
                  <span className="text-slate-400">
                    Slip: <strong className="text-emerald-400">{selectedPool.slippageBps10k} bps</strong>
                  </span>
                </div>
              </div>
            </div>

            {/* Risk Distribution Donut (5 cols) */}
            <div className="md:col-span-5 molt-card p-3.5 flex flex-col justify-between gap-2.5">
              <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                <div className="flex items-center gap-1.5 font-display font-bold text-sm text-white">
                  <span>Risk Distribution</span>
                  <Info className="w-3.5 h-3.5 text-slate-400" />
                </div>
                <span className="text-[10px] font-mono text-emerald-400">82.3% Safe</span>
              </div>

              <div className="flex items-center justify-between gap-2.5 py-1 pr-1">
                {/* SVG Donut Chart */}
                <div className="relative w-20 h-20 shrink-0 flex items-center justify-center">
                  <svg viewBox="0 0 36 36" className="w-20 h-20 -rotate-90">
                    <circle cx="18" cy="18" r="14" fill="none" stroke="#1E293B" strokeWidth="4.4" />
                    {/* Safe 82.3% */}
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#10B981"
                      strokeWidth="4.4"
                      strokeDasharray="72.4 100"
                    />
                    {/* Watch 11.1% */}
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#FACC15"
                      strokeWidth="4.4"
                      strokeDasharray="9.8 100"
                      strokeDashoffset="-72.4"
                    />
                    {/* High 3.4% + Critical */}
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#F97316"
                      strokeWidth="4.4"
                      strokeDasharray="5.8 100"
                      strokeDashoffset="-82.2"
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="font-display font-extrabold text-[11px] text-white tabular-nums">
                      10,482
                    </span>
                    <span className="text-[9px] text-slate-400">Pools</span>
                  </div>
                </div>

                {/* Distribution Legend */}
                <div className="space-y-1.5 text-[10px] flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-1 whitespace-nowrap">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <span className="heatmap-swatch w-2 h-2 bg-emerald-400 shrink-0" />
                      <span>Safe (0–4)</span>
                    </span>
                    <span className="font-mono font-semibold text-white tabular-nums">82.3%</span>
                  </div>
                  <div className="flex items-center justify-between gap-1 whitespace-nowrap">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <span className="heatmap-swatch w-2 h-2 bg-amber-400 shrink-0" />
                      <span>Watch (5–6)</span>
                    </span>
                    <span className="font-mono font-semibold text-white tabular-nums">11.1%</span>
                  </div>
                  <div className="flex items-center justify-between gap-1 whitespace-nowrap">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <span className="heatmap-swatch w-2 h-2 bg-orange-400 shrink-0" />
                      <span>High (7–8)</span>
                    </span>
                    <span className="font-mono font-semibold text-white tabular-nums">3.4%</span>
                  </div>
                  <div className="flex items-center justify-between gap-1 whitespace-nowrap">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <span className="heatmap-swatch w-2 h-2 bg-rose-500 shrink-0" />
                      <span>Critical (&ge; 9)</span>
                    </span>
                    <span className="font-mono font-semibold text-white tabular-nums">0.2%</span>
                  </div>
                </div>
              </div>

              {/* Bottom Live Oracle Strip */}
              <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono">
                <span className="flex items-center gap-1.5 text-slate-300">
                  <img
                    src="/assets/coins/SOL.png"
                    alt="SOL"
                    className="w-3.5 h-3.5 rounded-full object-cover"
                  />
                  <span>SOL Spot:</span>
                  <strong className="text-cyan-300">${solPriceUsd.toFixed(2)}</strong>
                </span>
                <span className="text-emerald-400">Coinbase Sync</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right 3 columns: Recent Alerts with Real Coin Icons */}
        <div className="xl:col-span-3 molt-card-purple p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-1.5">
            <div className="flex items-center gap-2 font-display font-bold text-sm text-white">
              <Bell className="w-4 h-4 text-cyan-400" />
              <span>Recent Alerts</span>
            </div>
            <button
              type="button"
              onClick={onTriggerSimulatedAlert}
              className="text-xs text-cyan-300 hover:text-cyan-200 inline-flex items-center gap-1 font-medium cursor-pointer"
            >
              <span>Simulate Alert</span>
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>

          <div className="space-y-1.5">
            {alerts.slice(0, 5).map((alert) => (
              <button
                key={alert.id}
                type="button"
                onClick={() => {
                  onSelectPoolPair(alert.pair);
                  setExpandedPoolPair(alert.pair);
                }}
                className="w-full text-left bg-slate-950/85 hover:bg-slate-900 border border-slate-800/90 hover:border-cyan-500/40 px-2.5 py-1.5 transition-colors cursor-pointer"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <img
                      src={getTokenIcon(alert.pair)}
                      alt={alert.pair}
                      className="w-4 h-4 rounded-full object-cover shrink-0 border border-slate-700"
                    />
                    <span className="text-[11px] font-bold text-white truncate">{alert.headline}</span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span
                      className={`px-1.5 py-0.5 text-[9px] font-mono font-bold ${
                        alert.status === 'CRITICAL'
                          ? 'bg-rose-500/20 text-rose-300 border border-rose-500/50'
                          : alert.status === 'HIGH'
                            ? 'bg-orange-500/20 text-orange-300 border border-orange-500/50'
                            : alert.status === 'WATCH'
                              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/50'
                              : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/50'
                      }`}
                    >
                      {alert.status}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">{alert.timeAgo}</span>
                  </div>
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5 pl-6 truncate">{alert.detail}</div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* LIVE TRANSACTION FLOW VISUALIZER */}
      <section
        className="molt-card p-4 sm:p-5 space-y-3.5"
        data-testid="live-transaction-flow-visualizer"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 cyber-cut-sm bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-300">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-display font-bold text-base text-white">
                  Live Transaction Flow Visualizer
                </h2>
                <span className="cyber-cut-sm px-2 py-0.5 text-[10px] font-mono font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/40">
                  Solana DEX + Multi-Rail Telemetry
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Real-time microstructure swap flow, MEV sandwich guards, Ed25519 witness signing &amp;
                SOL/USDC/Nano settlement pipeline.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                { id: 'ALL', label: 'All Flows' },
                { id: 'RISK', label: 'Risk Spikes' },
                { id: 'WITNESS', label: 'Witness Proofs' },
                { id: 'SETTLEMENT', label: 'Multi-Rail (SOL/USDC/Nano)' },
              ] as const
            ).map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFlowFilter(f.id)}
                className={`cyber-cut-sm px-3 py-1 text-xs font-mono transition-colors cursor-pointer border ${
                  flowFilter === f.id
                    ? 'bg-cyan-500/25 text-cyan-200 border-cyan-400/60 font-semibold'
                    : 'bg-slate-900/90 text-slate-400 border-slate-800 hover:text-slate-200'
                }`}
              >
                {f.label}
              </button>
            ))}

            <button
              type="button"
              onClick={() => setIsStreamPaused((p) => !p)}
              className="cyber-cut-sm px-3 py-1 bg-slate-900 border border-slate-700 hover:border-cyan-400/50 text-xs font-mono text-slate-200 inline-flex items-center gap-1.5 cursor-pointer"
            >
              {isStreamPaused ? <Play className="w-3 h-3 text-emerald-400" /> : <Pause className="w-3 h-3 text-amber-400" />}
              <span>{isStreamPaused ? 'Resume Stream' : 'Pause Stream'}</span>
            </button>
          </div>
        </div>

        {/* Visual Node Pipeline Diagram + Live Packet Cards */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-center">
          {/* Left 5 cols: Interactive SVG Node Pipeline */}
          <div className="lg:col-span-5 bg-slate-950/85 border border-slate-800/90 p-3">
            <svg viewBox="0 0 480 148" className="w-full h-34">
              <defs>
                <linearGradient id="flowPipe" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#00F0FF" />
                  <stop offset="50%" stopColor="#38BDF8" />
                  <stop offset="100%" stopColor="#A855F7" />
                </linearGradient>
              </defs>

              {/* Connecting flow lines */}
              <path d="M112,32 C150,32 155,74 194,74" stroke="url(#flowPipe)" strokeWidth="2" fill="none" />
              <path d="M112,74 L194,74" stroke="url(#flowPipe)" strokeWidth="2" fill="none" />
              <path d="M112,116 C150,116 155,74 194,74" stroke="url(#flowPipe)" strokeWidth="2" fill="none" />
              <path d="M286,74 L342,44" stroke="url(#flowPipe)" strokeWidth="2" fill="none" />
              <path d="M286,74 L342,104" stroke="url(#flowPipe)" strokeWidth="2" fill="none" />

              {/* Source DEX Nodes */}
              <g>
                <rect x="8" y="16" width="104" height="32" rx="6" fill="#0B132B" stroke="#00F0FF" strokeWidth="1.2" />
                <text x="60" y="36" fill="#E2E8F0" fontSize="9.5" fontWeight="bold" textAnchor="middle" fontFamily="JetBrains Mono">
                  Raydium CLMM
                </text>

                <rect x="8" y="58" width="104" height="32" rx="6" fill="#0B132B" stroke="#38BDF8" strokeWidth="1.2" />
                <text x="60" y="78" fill="#E2E8F0" fontSize="9.5" fontWeight="bold" textAnchor="middle" fontFamily="JetBrains Mono">
                  Orca / Jupiter
                </text>

                <rect x="8" y="100" width="104" height="32" rx="6" fill="#0B132B" stroke="#A855F7" strokeWidth="1.2" />
                <text x="60" y="120" fill="#E2E8F0" fontSize="9.5" fontWeight="bold" textAnchor="middle" fontFamily="JetBrains Mono">
                  Jito MEV Relay
                </text>
              </g>

              {/* Central Sentinel Risk Engine Node */}
              <g>
                <rect x="194" y="44" width="92" height="60" rx="10" fill="#111C44" stroke="#00F5FF" strokeWidth="2" />
                <text x="240" y="70" fill="#00F5FF" fontSize="10" fontWeight="bold" textAnchor="middle" fontFamily="Outfit">
                  SENTINEL
                </text>
                <text x="240" y="86" fill="#CBD5E1" fontSize="8.5" textAnchor="middle" fontFamily="JetBrains Mono">
                  Risk Telemetry
                </text>
              </g>

              {/* Output Nodes: Ed25519 State Witness & Multi-Rail Settlement */}
              <g>
                <rect x="342" y="22" width="130" height="42" rx="8" fill="#0D1F2D" stroke="#10B981" strokeWidth="1.5" />
                <text x="407" y="41" fill="#34D399" fontSize="9.5" fontWeight="bold" textAnchor="middle" fontFamily="JetBrains Mono">
                  Ed25519 Witness
                </text>
                <text x="407" y="55" fill="#94A3B8" fontSize="8.5" textAnchor="middle" fontFamily="JetBrains Mono">
                  RFC 8785 Signed
                </text>

                <rect x="342" y="84" width="130" height="42" rx="8" fill="#1E1436" stroke="#C084FC" strokeWidth="1.5" />
                <text x="407" y="103" fill="#E879F9" fontSize="9.5" fontWeight="bold" textAnchor="middle" fontFamily="JetBrains Mono">
                  SOL / USDC / Nano
                </text>
                <text x="407" y="117" fill="#94A3B8" fontSize="8.5" textAnchor="middle" fontFamily="JetBrains Mono">
                  Multi-Rail Settle
                </text>
              </g>
            </svg>
          </div>

          {/* Right 7 cols: Live Transaction Stream Cards with Real Coin Icons */}
          <div className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {filteredTxPackets.slice(0, 4).map((pkt) => (
              <button
                key={pkt.id}
                type="button"
                onClick={() => {
                  setSelectedPacketId(pkt.id === selectedPacketId ? null : pkt.id);
                  onSelectPoolPair(pkt.pair);
                  setExpandedPoolPair(pkt.pair);
                }}
                className={`text-left p-3 border transition-all cursor-pointer ${
                  selectedPacketId === pkt.id
                    ? 'bg-cyan-950/40 border-cyan-400'
                    : 'bg-slate-950/80 border-slate-800 hover:border-cyan-500/40'
                }`}
              >
                <div className="flex items-center justify-between text-[11px] font-mono">
                  <span className="font-bold text-white flex items-center gap-2">
                    <img
                      src={getTokenIcon(pkt.pair)}
                      alt={pkt.pair}
                      className="w-4 h-4 rounded-full object-cover border border-cyan-400/40"
                    />
                    <span>{pkt.pair}</span>
                  </span>
                  <span
                    className={`px-1.5 py-0.5 text-[10px] font-bold ${
                      pkt.status === 'CRITICAL'
                        ? 'bg-rose-500/20 text-rose-300'
                        : pkt.status === 'HIGH'
                          ? 'bg-orange-500/20 text-orange-300'
                          : pkt.status === 'WATCH'
                            ? 'bg-amber-500/20 text-amber-300'
                            : 'bg-emerald-500/20 text-emerald-300'
                    }`}
                  >
                    {pkt.flowType.replace('_', ' ')}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-1.5 text-xs">
                  <span className="text-cyan-300 font-mono font-semibold">{pkt.amountFormatted}</span>
                  <span className="text-slate-400 font-mono text-[11px] flex items-center gap-1">
                    <img
                      src={getDexIcon(pkt.dex)}
                      alt={pkt.dex}
                      className="w-3.5 h-3.5 rounded-full object-cover"
                    />
                    <span>
                      {pkt.dex} {pkt.rail ? `· ${pkt.rail}` : ''}
                    </span>
                  </span>
                </div>
                <div className="flex items-center justify-between mt-1 text-[10px] font-mono text-slate-400">
                  <span>{pkt.witnessSigPrefix}</span>
                  <span className="text-emerald-400">{pkt.latencyMs}ms</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* MIDDLE SECTION: LIVE POOLS TABLE WITH EXPANDABLE ROWS (Left 8 cols) + CRYPTOGRAPHIC WITNESS VERIFICATION (Right 4 cols) */}
      <section className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-stretch">
        {/* Left 8 columns: Live Pools (10,482) with Real Crypto Icons, Live Coinbase Sync & Expandable Rows */}
        <div className="xl:col-span-8 molt-card p-4 sm:p-5 flex flex-col justify-between space-y-4">
          {/* Header, Live Feed Attribution & Tabs Row */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-2.5">
              <div className="flex items-center gap-2.5">
                <Layers className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-bold text-lg text-white">
                  Live Pools <span className="text-slate-400 font-normal">(10,482)</span>
                </h2>
                <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span>{marketProviderSummary}</span>
                </span>
              </div>

              <div className="flex items-center gap-2 text-xs font-mono">
                <span className="text-[11px] text-slate-400">
                  SOL: <strong className="text-cyan-300">${solPriceUsd.toFixed(2)}</strong> · Sync: {lastMarketSync}
                </span>
                {onRefreshMarketTelemetry && (
                  <button
                    type="button"
                    onClick={onRefreshMarketTelemetry}
                    disabled={isSyncingMarket}
                    className="cyber-cut-sm px-2.5 py-1 bg-slate-900 hover:bg-slate-800 border border-cyan-500/40 text-cyan-200 text-[11px] inline-flex items-center gap-1 cursor-pointer"
                  >
                    <RefreshCw className={`w-3 h-3 ${isSyncingMarket ? 'animate-spin' : ''}`} />
                    <span>Refresh Feed</span>
                  </button>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              {/* Pool Category Filter Tabs */}
              <div className="flex flex-wrap items-center gap-1 bg-slate-950/90 p-1 border border-slate-800 text-xs">
                {(
                  [
                    { id: 'ALL', label: 'All Pools' },
                    { id: 'AT_RISK', label: 'At-Risk (27)' },
                    { id: 'WATCH', label: 'Watch (116)' },
                    { id: 'HIGH', label: 'High (36)' },
                    { id: 'CRITICAL', label: 'Critical (2)' },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setPoolTab(t.id)}
                    className={`cyber-cut-sm px-3 py-1 font-medium transition-colors cursor-pointer ${
                      poolTab === t.id
                        ? 'bg-cyan-400 text-slate-950 font-bold shadow-[0_0_12px_rgba(34,211,238,0.4)]'
                        : 'text-slate-300 hover:text-white'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {/* Timeframe Selector */}
              <div className="flex items-center gap-1 bg-slate-950/90 p-1 border border-slate-800 text-xs font-mono">
                {(['24h', '7d', '30d'] as const).map((tf) => (
                  <button
                    key={tf}
                    type="button"
                    onClick={() => setTimeframe(tf)}
                    className={`cyber-cut-sm px-2.5 py-1 transition-colors cursor-pointer ${
                      timeframe === tf
                        ? 'bg-cyan-500/30 text-cyan-200 border border-cyan-400/50 font-bold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Search & Dropdown Filter Bar */}
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search pools (e.g., RAY/SOL, POPCAT, pool address)..."
                aria-label="Search pools"
                className="w-full pl-9 pr-3.5 py-2 bg-slate-950/90 border border-slate-800 focus:border-cyan-400 focus:outline-none text-xs text-white placeholder:text-slate-500"
              />
            </div>

            <select
              value={dexFilter}
              onChange={(e) => setDexFilter(e.target.value)}
              aria-label="Filter by DEX"
              className="px-3 py-2 bg-slate-950/90 border border-slate-800 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none cursor-pointer"
            >
              <option value="ALL">All DEXs</option>
              <option value="Raydium">Raydium</option>
              <option value="Orca">Orca</option>
              <option value="Jupiter">Jupiter</option>
              <option value="Jito">Jito</option>
            </select>

            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label="Filter by Status"
              className="px-3 py-2 bg-slate-950/90 border border-slate-800 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none cursor-pointer"
            >
              <option value="ALL">All Status</option>
              <option value="SAFE">SAFE</option>
              <option value="WATCH">WATCH</option>
              <option value="HIGH">HIGH</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>

            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              aria-label="Filter by Category"
              className="px-3 py-2 bg-slate-950/90 border border-slate-800 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none cursor-pointer"
            >
              <option value="ALL">All Categories</option>
              <option value="DeFi">DeFi</option>
              <option value="Meme">Meme</option>
              <option value="Infra">Infra</option>
              <option value="LST">LST</option>
            </select>

            <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none ml-auto">
              <input
                type="checkbox"
                checked={showTrends}
                onChange={(e) => setShowTrends(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-8 h-4.5 bg-slate-800 peer-checked:bg-cyan-500 rounded-full relative transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3.5 after:h-3.5 after:bg-white after:rounded-full peer-checked:after:translate-x-3.5 after:transition-transform" />
              <span>Show Trends</span>
            </label>
          </div>

          {/* Live Pools Data Table with Inline Expandable Detail Drawer */}
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400">
                  <th className="py-2.5 px-2 w-8"></th>
                  <th className="py-2.5 px-2 w-8">#</th>
                  <th className="py-2.5 px-2">Pair &amp; Spot Price</th>
                  <th className="py-2.5 px-2">DEX</th>
                  <th className="py-2.5 px-2 text-right">Liquidity (USD)</th>
                  <th className="py-2.5 px-2 text-right">24h Vol (USD)</th>
                  <th className="py-2.5 px-2 text-center">Risk Score</th>
                  <th className="py-2.5 px-2 text-center">Status</th>
                  <th className="py-2.5 px-2 text-right">24h Change</th>
                  {showTrends && <th className="py-2.5 px-2 text-center">7d Trend</th>}
                  <th className="py-2.5 px-2 text-right">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-xs">
                {filteredPools.map((pool) => {
                  const isSelected = pool.pair === selectedPool.pair;
                  const isExpanded = expandedPoolPair === pool.pair;
                  const colSpanCount = showTrends ? 11 : 10;

                  return (
                    <React.Fragment key={pool.id}>
                      <tr
                        onClick={() => {
                          onSelectPoolPair(pool.pair);
                          setExpandedPoolPair((prev) => (prev === pool.pair ? null : pool.pair));
                        }}
                        className={`transition-colors cursor-pointer ${
                          isSelected
                            ? 'bg-cyan-500/15 hover:bg-cyan-500/20'
                            : 'hover:bg-slate-900/70'
                        }`}
                      >
                        <td
                          className="py-2.5 px-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            onToggleStarPool(pool.id);
                          }}
                        >
                          <button
                            type="button"
                            aria-label={`Favorite ${pool.pair}`}
                            className="text-slate-500 hover:text-amber-400 cursor-pointer"
                          >
                            <Star
                              className={`w-3.5 h-3.5 ${
                                pool.starred ? 'fill-amber-400 text-amber-400' : ''
                              }`}
                            />
                          </button>
                        </td>
                        <td className="py-2.5 px-2 font-mono text-slate-400 tabular-nums">
                          {pool.rank}
                        </td>
                        <td className="py-2.5 px-2 whitespace-nowrap">
                          <div className="flex items-center gap-2.5">
                            <div className="relative flex items-center shrink-0">
                              <img
                                src={pool.coinIcon}
                                alt={pool.baseToken}
                                className="w-6 h-6 rounded-full border border-cyan-400/50 bg-slate-950 object-cover"
                              />
                              <img
                                src={pool.quoteIcon}
                                alt={pool.quoteToken}
                                className="w-3.5 h-3.5 rounded-full border border-slate-700 bg-slate-950 object-cover -ml-1.5 mt-2.5"
                              />
                            </div>
                            <div>
                              <div className="font-bold text-white leading-tight">{pool.pair}</div>
                              <div className="text-[10px] font-mono text-cyan-300 tabular-nums">
                                {formatTokenPriceUsd(pool.priceUsd)}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="py-2.5 px-2 text-slate-300 whitespace-nowrap">
                          <div className="flex items-center gap-1.5">
                            <img
                              src={pool.dexIcon}
                              alt={pool.dex}
                              className="w-4 h-4 rounded-full object-cover border border-slate-700"
                            />
                            <span>{pool.dex}</span>
                          </div>
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono text-white tabular-nums">
                          {formatCompactUsd(pool.liquidityUsd)}
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono text-slate-200 tabular-nums">
                          {formatCompactUsd(pool.volume24hUsd)}
                        </td>
                        <td className="py-2.5 px-2 text-center">
                          <span
                            className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-mono font-bold tabular-nums border ${
                              pool.status === 'CRITICAL'
                                ? 'bg-rose-500/20 text-rose-300 border-rose-500/50'
                                : pool.status === 'HIGH'
                                  ? 'bg-orange-500/20 text-orange-300 border-orange-500/50'
                                  : pool.status === 'WATCH'
                                    ? 'bg-amber-500/20 text-amber-300 border-amber-500/50'
                                    : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                            }`}
                          >
                            {pool.riskScore.toFixed(1)} / 10
                          </span>
                        </td>
                        <td className="py-2.5 px-2 text-center">
                          <span
                            className={`inline-block px-2 py-0.5 text-[10px] font-mono font-bold ${
                              pool.status === 'CRITICAL'
                                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                                : pool.status === 'HIGH'
                                  ? 'bg-orange-500/20 text-orange-300 border border-orange-500/40'
                                  : pool.status === 'WATCH'
                                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                                    : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            }`}
                          >
                            {pool.status}
                          </span>
                        </td>
                        <td
                          className={`py-2.5 px-2 text-right font-mono font-semibold tabular-nums ${
                            pool.change24hPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {pool.change24hPct >= 0 ? `+${pool.change24hPct}%` : `${pool.change24hPct}%`}
                        </td>
                        {showTrends && (
                          <td className="py-2.5 px-2 w-24">
                            <svg viewBox="0 0 70 22" className="w-20 h-5 mx-auto">
                              <polyline
                                fill="none"
                                stroke={pool.change24hPct >= 0 ? '#10B981' : '#F43F5E'}
                                strokeWidth="1.8"
                                points={pool.trend7d
                                  .map((v, i) => `${i * 11},${20 - (v / 90) * 18}`)
                                  .join(' ')}
                              />
                            </svg>
                          </td>
                        )}
                        <td className="py-2.5 px-2 text-right font-mono text-slate-400 whitespace-nowrap">
                          <span className="inline-flex items-center gap-1 text-cyan-300 text-[11px]">
                            <span>{pool.lastUpdate}</span>
                            {isExpanded ? (
                              <ChevronUp className="w-3.5 h-3.5 text-cyan-400" />
                            ) : (
                              <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
                            )}
                          </span>
                        </td>
                      </tr>

                      {/* EXPANDED INLINE POOL TELEMETRY DRAWER */}
                      {isExpanded && (
                        <tr className="bg-[#060b16] border-b border-cyan-500/30">
                          <td colSpan={colSpanCount} className="p-3.5">
                            <div
                              data-testid={`expanded-pool-details-${pool.baseToken}`}
                              className="bracket-card p-4 space-y-3 bg-[#091122]"
                            >
                              <div className="bracket-tick bracket-tick-tl" />
                              <div className="bracket-tick bracket-tick-tr" />
                              <div className="bracket-tick bracket-tick-bl" />
                              <div className="bracket-tick bracket-tick-br" />

                              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2.5">
                                <div className="flex items-center gap-2.5">
                                  <img
                                    src={pool.coinIcon}
                                    alt={pool.baseToken}
                                    className="w-7 h-7 rounded-full border border-cyan-400/60"
                                  />
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <span className="font-display font-bold text-sm text-white">
                                        {pool.pair} Deep Microstructure &amp; Market Telemetry
                                      </span>
                                      <span className="cyber-cut-sm px-2 py-0.5 text-[10px] font-mono bg-cyan-500/15 text-cyan-300 border border-cyan-500/40">
                                        {pool.liveSource}
                                      </span>
                                    </div>
                                    <div className="text-[11px] font-mono text-slate-400">
                                      Pool Address: <span className="text-slate-200">{pool.poolAddress}</span>
                                    </div>
                                  </div>
                                </div>

                                <div className="flex items-center gap-2">
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleCopy(`pool-${pool.id}`, pool.poolAddress);
                                    }}
                                    className="cyber-cut-sm px-2.5 py-1 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-[11px] font-mono text-slate-200 inline-flex items-center gap-1 cursor-pointer"
                                  >
                                    {copiedField === `pool-${pool.id}` ? (
                                      <Check className="w-3 h-3 text-emerald-400" />
                                    ) : (
                                      <Copy className="w-3 h-3 text-cyan-400" />
                                    )}
                                    <span>Copy Pool Address</span>
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setExplorerModalOpen(true);
                                    }}
                                    className="molt-btn-cyan px-3 py-1 text-[11px] font-mono inline-flex items-center gap-1 cursor-pointer"
                                  >
                                    <ShieldCheck className="w-3.5 h-3.5" />
                                    <span>Inspect Ed25519 Proof</span>
                                  </button>
                                </div>
                              </div>

                              {/* 3-Column Telemetry Breakdown */}
                              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs font-mono">
                                {/* Col 1: Live Coinbase Exchange Market Data */}
                                <div className="bg-slate-950/90 border border-slate-800 p-3 space-y-1.5">
                                  <div className="text-[10px] uppercase tracking-wider text-cyan-400 font-bold">
                                    Coinbase Exchange Market Data
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Spot Price (USD):</span>
                                    <span className="text-white font-bold">
                                      {formatTokenPriceUsd(pool.priceUsd)}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">24h High / Low:</span>
                                    <span className="text-slate-200">
                                      {formatTokenPriceUsd(pool.low24hUsd)} – {formatTokenPriceUsd(pool.high24hUsd)}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Market Cap:</span>
                                    <span className="text-emerald-300 font-bold">
                                      {formatCompactUsd(pool.marketCapUsd)}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Fully Diluted (FDV):</span>
                                    <span className="text-slate-200">{formatCompactUsd(pool.fdvUsd)}</span>
                                  </div>
                                </div>

                                {/* Col 2: CLMM / AMM Liquidity Microstructure (Simulated Demo) */}
                                <div className="bg-slate-950/90 border border-slate-800 p-3 space-y-1.5">
                                  <div className="text-[10px] uppercase tracking-wider text-purple-400 font-bold">
                                    CLMM Liquidity &amp; Slippage (Simulated Demo)
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">LP Concentration (HHI):</span>
                                    <span
                                      className={`font-bold ${
                                        pool.lpConcentrationHhi >= 0.5 ? 'text-rose-400' : 'text-emerald-400'
                                      }`}
                                    >
                                      {pool.lpConcentrationHhi.toFixed(2)}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Top-5 LP Share:</span>
                                    <span className="text-white font-bold">{pool.top5LpSharePct}%</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">$10k Swap Slippage:</span>
                                    <span
                                      className={`font-bold ${
                                        pool.slippageBps10k >= 100 ? 'text-amber-400' : 'text-cyan-300'
                                      }`}
                                    >
                                      {pool.slippageBps10k} bps ({(pool.slippageBps10k / 100).toFixed(2)}%)
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">DEX Venue:</span>
                                    <span className="text-slate-200">{pool.dex} CLMM</span>
                                  </div>
                                </div>

                                {/* Col 3: Authority Security & Witness State (Simulated Demo) */}
                                <div className="bg-slate-950/90 border border-slate-800 p-3 space-y-1.5">
                                  <div className="text-[10px] uppercase tracking-wider text-emerald-400 font-bold">
                                    Security &amp; Witness Guards (Simulated Demo)
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Mint Authority:</span>
                                    <span className="text-emerald-400 font-bold">{pool.mintAuthority}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Freeze Authority:</span>
                                    <span
                                      className={`font-bold ${
                                        pool.freezeAuthority.includes('Warning')
                                          ? 'text-rose-400'
                                          : 'text-emerald-400'
                                      }`}
                                    >
                                      {pool.freezeAuthority}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Attested Slot:</span>
                                    <span className="text-cyan-300">#{currentSlot.toLocaleString()}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Witness Epoch:</span>
                                    <span className="text-slate-200">{activeWitnessKey.keyId}</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Table Pagination Footer */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80 text-xs text-slate-400">
            <span>
              Showing 1 – {filteredPools.length} of 10,482 pools · Click any row to expand live
              Coinbase Exchange telemetry
            </span>
            <div className="flex items-center gap-1.5 font-mono">
              <span className="cyber-cut-sm px-2.5 py-1 bg-cyan-500/25 border border-cyan-400 text-cyan-200 font-bold">
                1
              </span>
              <span className="px-2 py-1 text-slate-400">2</span>
              <span className="px-2 py-1 text-slate-400">3</span>
              <span className="px-2 py-1 text-slate-400">...</span>
              <span className="px-2 py-1 text-slate-400">1,049</span>
            </div>
          </div>
        </div>

        {/* Right 4 columns: Cryptographic Witness Verification matching Image 1 */}
        <div className="xl:col-span-4 molt-card p-4 sm:p-5 flex flex-col justify-between space-y-4">
          <div className="space-y-3">
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 cyber-cut-sm bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-400 shrink-0">
                  <ShieldCheck className="w-5 h-5" />
                </div>
                <div>
                  <h2 className="font-display font-bold text-base text-white">
                    Cryptographic Witness Verification
                  </h2>
                  <p className="text-[11px] text-slate-400">
                    Canonical, signed attestations for risk analysis, pool state, and market events.
                  </p>
                </div>
              </div>
              <span className="cyber-cut-sm px-2.5 py-1 text-[11px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/50 shrink-0">
                ✓ VERIFIED
              </span>
            </div>

            {/* Sub-navigation Tabs */}
            <div className="grid grid-cols-4 gap-1 bg-slate-950/90 p-1 border border-slate-800 text-[11px]">
              {(['Verification', 'Canonical JSON', 'Signature (Raw)', 'Details'] as const).map(
                (tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setWitnessTab(tab)}
                    className={`cyber-cut-sm py-1.5 px-2 font-medium truncate transition-colors cursor-pointer ${
                      witnessTab === tab
                        ? 'bg-cyan-400 text-slate-950 font-bold'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {tab}
                  </button>
                )
              )}
            </div>

            {/* Witness Target with Real Coin Icon */}
            <div className="bg-slate-950/85 border border-slate-800 p-3 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5 min-w-0">
                <img
                  src={selectedPool.coinIcon}
                  alt={selectedPool.baseToken}
                  className="w-6 h-6 rounded-full border border-cyan-400/50 shrink-0"
                />
                <div className="min-w-0">
                  <div className="text-[11px] text-slate-400">Witness Target</div>
                  <div className="text-xs font-mono font-bold text-white truncate">
                    {witnessAttestation.targetPair} · Slot {witnessAttestation.slot.toLocaleString()}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() =>
                  handleCopy(
                    'target',
                    `${witnessAttestation.targetPair} · Slot ${witnessAttestation.slot}`
                  )
                }
                className="cyber-cut-sm px-2.5 py-1 bg-slate-900 border border-slate-700 hover:border-cyan-400 text-[11px] text-slate-300 inline-flex items-center gap-1 shrink-0 cursor-pointer"
              >
                {copiedField === 'target' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>Copy</span>
              </button>
            </div>

            {/* Witness Hash (SHA-256) */}
            <div className="bg-slate-950/85 border border-slate-800 p-3 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5 min-w-0">
                <Hash className="w-4 h-4 text-cyan-400 shrink-0" />
                <div className="min-w-0">
                  <div className="text-[11px] text-slate-400">Witness Hash (SHA-256)</div>
                  <div className="text-xs font-mono text-slate-200 truncate">
                    {witnessAttestation.witnessHashSha256}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => handleCopy('hash', witnessAttestation.witnessHashSha256)}
                className="cyber-cut-sm px-2.5 py-1 bg-slate-900 border border-slate-700 hover:border-cyan-400 text-[11px] text-slate-300 inline-flex items-center gap-1 shrink-0 cursor-pointer"
              >
                {copiedField === 'hash' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>Copy</span>
              </button>
            </div>

            {/* Signature (Ed25519) */}
            <div className="bg-slate-950/85 border border-slate-800 p-3 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5 min-w-0">
                <PenTool className="w-4 h-4 text-cyan-400 shrink-0" />
                <div className="min-w-0">
                  <div className="text-[11px] text-slate-400">Signature (Ed25519)</div>
                  <div className="text-xs font-mono text-slate-200 truncate">
                    {witnessAttestation.signatureEd25519}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => handleCopy('sig', witnessAttestation.signatureEd25519)}
                className="cyber-cut-sm px-2.5 py-1 bg-slate-900 border border-slate-700 hover:border-cyan-400 text-[11px] text-slate-300 inline-flex items-center gap-1 shrink-0 cursor-pointer"
              >
                {copiedField === 'sig' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>Copy</span>
              </button>
            </div>

            {/* Canonical JSON (RFC 8785) */}
            <div className="bg-slate-950/95 border border-slate-800 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
                  <FileCode2 className="w-4 h-4 text-cyan-400" />
                  <span>Canonical JSON (RFC 8785)</span>
                </div>
                <button
                  type="button"
                  onClick={() => handleCopy('json', witnessAttestation.canonicalJson)}
                  aria-label="Copy Canonical JSON"
                  className="text-slate-400 hover:text-cyan-300 p-1 cursor-pointer"
                >
                  {copiedField === 'json' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
              <pre className="text-[11px] font-mono text-cyan-200 overflow-x-auto leading-relaxed">
                <code>
                  {witnessTab === 'Signature (Raw)'
                    ? `Algorithm: Ed25519\nKey Epoch: ${witnessAttestation.keyEpochId}\nPublic Key: ${witnessAttestation.publicKey}\nSignature: ${witnessAttestation.signatureEd25519}`
                    : witnessAttestation.canonicalJson}
                </code>
              </pre>
            </div>
          </div>

          {/* Bottom Witness Verified Confirmation Banner */}
          <div className="bg-emerald-950/35 border border-emerald-500/40 p-3.5 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
              <div>
                <div className="text-xs font-bold text-white">Witness Verified</div>
                <div className="text-[10px] text-emerald-300">
                  Canonical JSON · Valid Ed25519 Signature · Integrity Confirmed
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setExplorerModalOpen(true)}
              className="cyber-cut-sm px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-cyan-400/40 text-[11px] font-semibold text-cyan-200 inline-flex items-center gap-1 shrink-0 cursor-pointer"
            >
              <span>View on Explorer</span>
              <ExternalLink className="w-3 h-3" />
            </button>
          </div>
        </div>
      </section>

      {/* SECTION 4 • AGENT CREDIT BUREAU & DUESPROOF™ BIRTHCERT LOOKUP TOOL */}
      <section
        className="molt-card cyber-ruler-left p-5 sm:p-6 space-y-5"
        data-testid="agent-credit-bureau-section"
      >
        {/* Header Bar */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/40 uppercase tracking-wider">
                SECTION 4 • AGENT CREDIT BUREAU &amp; DUESPROOF REGISTRY
              </span>
              <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/40">
                Ed25519 BirthCert Attested
              </span>
              <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono bg-amber-500/15 text-amber-300 border border-amber-400/50 font-semibold">
                SIMULATED DEMO REGISTRY
              </span>
            </div>
            <h2 className="font-display font-extrabold text-xl sm:text-2xl text-white tracking-tight">
              Autonomous Agent Reputation, Track-Record &amp; DuesProof™ BirthCert Profiling
            </h2>
            <p className="text-xs text-slate-400 max-w-3xl">
              Evaluates published work (track record), delivery reliability score, unfulfilled claims,
              and cryptographic <strong className="text-cyan-300">DuesProof BirthCert</strong> genesis
              standing. Distinguishes observed wallet activity from human proof.
            </p>
          </div>

          <div className="text-xs font-mono text-slate-400 shrink-0">
            Endpoint:{' '}
            <code className="cyber-cut-sm px-2.5 py-1 bg-slate-950 border border-slate-800 text-cyan-300">
              GET /v1/sentinel/agents/&#123;id&#125;
            </code>
          </div>
        </div>

        {/* Search Input + INSPECT DOSSIER Button + Presets Row */}
        <div className="space-y-2.5">
          <form onSubmit={handleInspectAgentSubmit} className="flex flex-col sm:flex-row gap-2.5">
            <div className="relative flex-1">
              <Bot className="w-4 h-4 text-cyan-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={agentSearchInput}
                onChange={(e) => setAgentSearchInput(e.target.value)}
                placeholder="Enter autonomous agent handle or wallet (e.g. antigravityandrew, jeeves_hermes, osai2026)..."
                aria-label="Agent Lookup Handle"
                className="w-full pl-10 pr-4 py-2.5 bg-[#050914] border border-slate-800 focus:border-cyan-400 focus:outline-none text-xs sm:text-sm font-mono text-white"
              />
            </div>
            <button
              type="submit"
              className="molt-btn-cyan px-6 py-2.5 text-xs font-mono uppercase tracking-wider inline-flex items-center justify-center gap-2 cursor-pointer shrink-0"
            >
              <Search className="w-3.5 h-3.5" />
              <span>INSPECT DOSSIER</span>
            </button>
          </form>

          {/* Preset Selector Pills matching user screenshot */}
          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
            <span className="text-slate-400 text-[11px]">Presets:</span>
            <button
              type="button"
              onClick={() => handleSelectPresetAgent('antigravityandrew')}
              className={`cyber-cut-sm px-2.5 py-1 border transition-colors cursor-pointer ${
                inspectedAgentHandle.toLowerCase() === 'antigravityandrew'
                  ? 'bg-cyan-500/20 text-cyan-200 border-cyan-400 font-bold'
                  : 'bg-slate-900/90 hover:bg-slate-800 text-slate-300 border-slate-800'
              }`}
            >
              antigravityandrew (Verified Operator)
            </button>
            <button
              type="button"
              onClick={() => handleSelectPresetAgent('jeeves_hermes')}
              className={`cyber-cut-sm px-2.5 py-1 border transition-colors cursor-pointer ${
                inspectedAgentHandle.toLowerCase() === 'jeeves_hermes'
                  ? 'bg-cyan-500/20 text-cyan-200 border-cyan-400 font-bold'
                  : 'bg-slate-900/90 hover:bg-slate-800 text-slate-300 border-slate-800'
              }`}
            >
              jeeves_hermes (4 Deliveries)
            </button>
            <button
              type="button"
              onClick={() => handleSelectPresetAgent('osai2026')}
              className={`cyber-cut-sm px-2.5 py-1 border transition-colors cursor-pointer ${
                inspectedAgentHandle.toLowerCase() === 'osai2026'
                  ? 'bg-cyan-500/20 text-cyan-200 border-cyan-400 font-bold'
                  : 'bg-slate-900/90 hover:bg-slate-800 text-slate-300 border-slate-800'
              }`}
            >
              osai2026 (Commercial Seller)
            </button>
            <button
              type="button"
              onClick={() => handleSelectPresetAgent('frantic_129')}
              className={`cyber-cut-sm px-2.5 py-1 border transition-colors cursor-pointer ${
                inspectedAgentHandle.toLowerCase() === 'frantic_129'
                  ? 'bg-rose-500/25 text-rose-200 border-rose-400 font-bold'
                  : 'bg-rose-950/60 hover:bg-rose-900/70 text-rose-300 border-rose-800/70'
              }`}
            >
              frantic_129 (Dead Sponsor)
            </button>
          </div>
        </div>

        {/* Agent Dossier Card */}
        <div className="bracket-card p-5 bg-[#050a16]/95 space-y-5">
          <div className="bracket-tick bracket-tick-tl" />
          <div className="bracket-tick bracket-tick-tr" />
          <div className="bracket-tick bracket-tick-bl" />
          <div className="bracket-tick bracket-tick-br" />

          {/* Top Identity & Reliability Score Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-12 h-12 cyber-cut-sm bg-gradient-to-br from-cyan-500/20 to-purple-500/20 border border-cyan-400/50 flex items-center justify-center text-cyan-300 shrink-0">
                <Bot className="w-6 h-6" />
              </div>
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    data-testid="agent-dossier-handle"
                    className="font-mono font-bold text-lg text-white"
                  >
                    {agentDossier.identifier}
                  </span>
                  <span
                    className={`cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono font-bold border ${
                      agentDossier.reputationTier === 'VERIFIED_OPERATOR'
                        ? 'bg-emerald-950/90 text-emerald-300 border-emerald-500/60'
                        : agentDossier.reputationTier === 'COMMERCIAL_SELLER'
                          ? 'bg-cyan-950/90 text-cyan-300 border-cyan-500/60'
                          : agentDossier.reputationTier === 'DEAD_SPONSOR'
                            ? 'bg-rose-950/90 text-rose-300 border-rose-500/60'
                            : 'bg-slate-800 text-slate-300 border-slate-600'
                    }`}
                  >
                    {agentDossier.reputationTier}
                  </span>
                  <span
                    className={`cyber-cut-sm px-2 py-0.5 text-[10px] font-mono font-semibold border ${
                      agentDossier.birthCert.status === 'DUESPROOF_VERIFIED'
                        ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                        : agentDossier.birthCert.status === 'PROVISIONAL'
                          ? 'bg-amber-500/15 text-amber-300 border-amber-400/40'
                          : 'bg-rose-500/15 text-rose-300 border-rose-400/40'
                    }`}
                  >
                    {agentDossier.birthCert.status === 'DUESPROOF_VERIFIED'
                      ? '✓ DUESPROOF BIRTHCERT ACTIVE'
                      : agentDossier.birthCert.status === 'PROVISIONAL'
                        ? '⚠ UNOBSERVED / PROVISIONAL'
                        : '✕ DUESPROOF REVOKED'}
                  </span>
                  <span className="cyber-cut-sm px-2 py-0.5 text-[10px] font-mono bg-amber-500/15 text-amber-300 border border-amber-400/50">
                    SIMULATED DEMO DOSSIER
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-slate-400">
                  <span>
                    Wallet:{' '}
                    <strong className="text-slate-200">
                      {agentDossier.walletAddress || 'Unverified (No On-Chain Link)'}
                    </strong>
                  </span>
                  <span>·</span>
                  <span className="text-cyan-300/90">{agentDossier.specialty}</span>
                </div>
              </div>
            </div>

            {/* Right: Delivery Reliability Score */}
            <div className="text-left sm:text-right shrink-0">
              <div
                data-testid="agent-reliability-score"
                className={`font-mono font-extrabold text-2xl sm:text-3xl tabular-nums ${
                  (agentDossier.reliabilityPct ?? 0) >= 80
                    ? 'text-emerald-400'
                    : (agentDossier.reliabilityPct ?? 0) > 0
                      ? 'text-amber-400'
                      : 'text-rose-400'
                }`}
              >
                {agentDossier.reliabilityPct !== null ? `${agentDossier.reliabilityPct}%` : 'N/A'}
              </div>
              <div className="text-[11px] font-mono text-slate-400">
                Delivery Reliability Score
              </div>
            </div>
          </div>

          {/* 4 Core Counterparty KPI Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center font-mono">
            <div className="bg-slate-900/75 p-3 border border-slate-800">
              <span className="text-[11px] text-slate-400 block">Known Deliveries</span>
              <span className="text-base font-extrabold text-white mt-0.5 block tabular-nums">
                {agentDossier.knownDeliveries}
              </span>
            </div>
            <div className="bg-slate-900/75 p-3 border border-slate-800">
              <span className="text-[11px] text-slate-400 block">Unfulfilled Claims</span>
              <span
                className={`text-base font-extrabold mt-0.5 block tabular-nums ${
                  agentDossier.unfulfilledClaims === 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {agentDossier.unfulfilledClaims}
              </span>
            </div>
            <div className="bg-slate-900/75 p-3 border border-slate-800">
              <span className="text-[11px] text-slate-400 block">Verification Status</span>
              <span
                className={`text-base font-extrabold mt-0.5 block ${
                  agentDossier.verificationStatus === 'ACTIVE'
                    ? 'text-emerald-400'
                    : 'text-rose-400'
                }`}
              >
                {agentDossier.verificationStatus}
              </span>
            </div>
            <div className="bg-slate-900/75 p-3 border border-slate-800">
              <span className="text-[11px] text-slate-400 block">Dead Sponsor Flags</span>
              <span
                className={`text-base font-extrabold mt-0.5 block tabular-nums ${
                  agentDossier.deadSponsorFlags === 0 ? 'text-slate-300' : 'text-rose-400'
                }`}
              >
                {agentDossier.deadSponsorFlags}
              </span>
            </div>
          </div>

          {/* 2-Column Deep-Dive: Published Work (Track Record) + DuesProof BirthCert */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 pt-1">
            {/* Left 6 cols: Published Work & Verifiable Track Record */}
            <div className="lg:col-span-6 bg-slate-950/90 border border-slate-800 p-4 flex flex-col justify-between space-y-3">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
                <div className="flex items-center gap-2">
                  <Award className="w-4 h-4 text-cyan-400" />
                  <h3 className="font-display font-bold text-sm text-white">
                    Published Work &amp; Verifiable Track Record
                  </h3>
                </div>
                <span className="text-[11px] font-mono text-cyan-300">
                  {agentDossier.publishedWork.length} Attested Deliverables
                </span>
              </div>

              {agentDossier.publishedWork.length === 0 ? (
                <div className="p-5 bg-rose-950/25 border border-rose-500/40 text-xs font-mono text-rose-200 space-y-1.5 my-auto">
                  <div className="font-bold flex items-center gap-2 text-rose-300">
                    <AlertTriangle className="w-4 h-4 shrink-0" />
                    <span>
                      {agentDossier.verificationStatus === 'UNOBSERVED'
                        ? 'Zero Verified Deliveries — Unobserved Agent Handle'
                        : 'Zero Verified Deliveries — Counterparty Default Alert'}
                    </span>
                  </div>
                  <p className="text-slate-300 leading-relaxed">
                    {agentDossier.verificationStatus === 'UNOBSERVED' ? (
                      <>
                        Agent <strong>{agentDossier.identifier}</strong> has no independently verified
                        deliveries or staked operator bond in the registry. Unknown handles are never
                        assigned verified standing.
                      </>
                    ) : (
                      <>
                        Agent <strong>{agentDossier.identifier}</strong> has{' '}
                        <strong>{agentDossier.unfulfilledClaims} unfulfilled bounty claims</strong> and{' '}
                        <strong>{agentDossier.deadSponsorFlags} dead sponsor flag</strong>. Do not route
                        prepaid credits or autonomous task escrows to this counterparty.
                      </>
                    )}
                  </p>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {agentDossier.publishedWork.map((work) => {
                    const uriCheck = validateSafeExternalUri(work.deliverableUri);
                    const provenanceLabel = work.witnessReceiptSig.startsWith('ed25519:')
                      ? 'CRYPTOGRAPHICALLY_VERIFIED'
                      : work.witnessReceiptSig.startsWith('sim_demo_receipt:')
                        ? 'SIMULATED_DEMO_SAMPLE'
                        : 'SELF_REPORTED (NOT COUNTED)';
                    return (
                      <div
                        key={work.id}
                        className="p-3 bg-slate-900/75 border border-slate-800/90 hover:border-cyan-500/40 transition-colors space-y-1.5"
                      >
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="font-bold text-white truncate">
                            {sanitizePlainText(work.title, 120)}
                          </span>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span className="cyber-cut-sm px-2 py-0.5 text-[9px] font-mono bg-cyan-500/15 text-cyan-300 border border-cyan-500/40">
                              {provenanceLabel}
                            </span>
                            <span className="cyber-cut-sm px-2 py-0.5 text-[10px] font-mono bg-emerald-500/15 text-emerald-300 border border-emerald-500/40">
                              {work.rewardSettled}
                            </span>
                          </div>
                        </div>
                        <p className="text-[11px] text-slate-300 leading-relaxed">
                          {sanitizePlainText(work.summary, 320)}
                        </p>
                        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[10px] font-mono text-slate-400">
                          <span className="text-cyan-300 truncate max-w-[260px]">
                            URI: {uriCheck.allowed ? uriCheck.data : '[BLOCKED_UNSAFE_URI]'}
                          </span>
                          <span>
                            Slot #{work.slot.toLocaleString()} · {work.witnessReceiptSig}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Right 6 cols: DuesProof™ Cryptographic Birth Certificate (BirthCert) */}
            <div
              data-testid="duesproof-birthcert-card"
              className="lg:col-span-6 bg-slate-950/90 border border-cyan-500/40 p-4 flex flex-col justify-between space-y-3 relative overflow-hidden"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2.5">
                <div className="flex items-center gap-2">
                  <Fingerprint className="w-4 h-4 text-cyan-400" />
                  <h3 className="font-display font-bold text-sm text-white">
                    DuesProof™ Cryptographic Birth Certificate
                  </h3>
                </div>
                <span
                  className={`cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono font-bold border ${
                    agentDossier.birthCert.status === 'DUESPROOF_VERIFIED'
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'
                      : 'bg-rose-500/20 text-rose-300 border-rose-500/50'
                  }`}
                >
                  {agentDossier.birthCert.status}
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs font-mono">
                <div className="bg-slate-900/80 border border-slate-800 p-2.5">
                  <span className="text-[10px] text-slate-400 block">Certificate ID</span>
                  <span className="text-cyan-300 font-bold truncate block">
                    {agentDossier.birthCert.certId}
                  </span>
                </div>
                <div className="bg-slate-900/80 border border-slate-800 p-2.5">
                  <span className="text-[10px] text-slate-400 block">Genesis Slot &amp; Mint Date</span>
                  <span className="text-white font-bold truncate block">
                    Slot #{agentDossier.birthCert.genesisSlot.toLocaleString()} ·{' '}
                    {agentDossier.birthCert.genesisTimestampIso.slice(0, 10)}
                  </span>
                </div>
                <div className="sm:col-span-2 bg-slate-900/80 border border-slate-800 p-2.5">
                  <span className="text-[10px] text-slate-400 block">
                    Protocol Dues &amp; Sponsor Bond Standing
                  </span>
                  <span
                    className={`font-bold block ${
                      agentDossier.birthCert.status === 'DUESPROOF_VERIFIED'
                        ? 'text-emerald-300'
                        : 'text-rose-300'
                    }`}
                  >
                    {agentDossier.birthCert.duesStakedFormatted}
                  </span>
                </div>
                <div className="sm:col-span-2 bg-slate-900/80 border border-slate-800 p-2.5 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-slate-400">Agent Ed25519 Identity Key:</span>
                    <span className="text-[10px] text-purple-300">RFC 8785 Witnessed</span>
                  </div>
                  <div className="text-[11px] text-slate-200 truncate">
                    {agentDossier.birthCert.identityPubKeyEd25519}
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    Witness Sig: <span className="text-cyan-300">{agentDossier.birthCert.witnessSignatureEd25519}</span>
                  </div>
                </div>
              </div>

              {showBirthCertJson && (
                <pre className="bg-black/80 border border-slate-800 p-2.5 text-[10px] font-mono text-cyan-200 overflow-x-auto leading-relaxed">
                  <code>{agentDossier.birthCert.canonicalBirthCertJson}</code>
                </pre>
              )}

              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowBirthCertJson((v) => !v)}
                    className="cyber-cut-sm px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-[11px] font-mono text-slate-200 inline-flex items-center gap-1.5 cursor-pointer"
                  >
                    <FileCheck2 className="w-3.5 h-3.5 text-cyan-400" />
                    <span>{showBirthCertJson ? 'Hide BirthCert JSON' : 'Inspect BirthCert JSON'}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      handleCopy('birthcert', agentDossier.birthCert.canonicalBirthCertJson)
                    }
                    className="cyber-cut-sm px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-[11px] font-mono text-slate-200 inline-flex items-center gap-1.5 cursor-pointer"
                  >
                    {copiedField === 'birthcert' ? (
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="w-3.5 h-3.5 text-cyan-400" />
                    )}
                    <span>Copy BirthCert</span>
                  </button>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    const isAuthentic = verifyDuesProofBirthCert(agentDossier.birthCert);
                    setBirthCertVerificationState(isAuthentic ? 'verified' : 'rejected');
                  }}
                  className={`px-3.5 py-1.5 text-[11px] font-mono inline-flex items-center gap-1.5 cursor-pointer ${
                    birthCertVerificationState === 'rejected'
                      ? 'cyber-cut-sm bg-rose-950/80 border border-rose-500/70 text-rose-200'
                      : 'molt-btn-cyan'
                  }`}
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>
                    {birthCertVerificationState === 'verified'
                      ? '✓ BirthCert Ed25519 Verified'
                      : birthCertVerificationState === 'rejected'
                        ? '✕ BirthCert Verification Rejected'
                        : 'Verify DuesProof BirthCert'}
                  </span>
                </button>
              </div>
            </div>
          </div>

          {/* Non-Repudiation Note matching user screenshot */}
          <div className="p-3 bg-slate-900/50 border border-slate-800/90 text-[11px] font-mono text-slate-400 flex items-start gap-2">
            <span className="text-cyan-400 font-bold shrink-0">ℹ Note:</span>
            <span>
              Observed wallet activity validates on-chain transaction history, DuesProof™ genesis
              bond standing, and delivery reputation; it does not constitute mathematical proof of
              human identity.
            </span>
          </div>
        </div>
      </section>

      {/* EXPLORER PROOF MODAL */}
      {explorerModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="molt-card max-w-lg w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <h3 className="font-display font-bold text-lg text-white">
                  Solana State Witness Explorer — Slot #{currentSlot.toLocaleString()}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setExplorerModalOpen(false)}
                className="text-slate-400 hover:text-white text-xs font-mono cursor-pointer"
              >
                [ESC]
              </button>
            </div>
            <div className="space-y-2 text-xs font-mono bg-slate-950 p-4 border border-slate-800">
              <div className="text-slate-400">
                Pair: <span className="text-white font-bold">{witnessAttestation.targetPair}</span>
              </div>
              <div className="text-slate-400">
                Signer Key Epoch:{' '}
                <span className="text-cyan-300">{witnessAttestation.keyEpochId}</span>
              </div>
              <div className="text-slate-400 break-all">
                SHA-256 Digest:{' '}
                <span className="text-emerald-300">{witnessAttestation.witnessHashSha256}</span>
              </div>
              <div className="text-slate-400 break-all">
                Ed25519 Signature:{' '}
                <span className="text-fuchsia-300">{witnessAttestation.signatureEd25519}</span>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setExplorerModalOpen(false)}
                className="molt-btn-cyan px-4 py-2 text-xs font-bold cursor-pointer"
              >
                Close Proof Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
