import React, { useState } from 'react';
import {
  Home,
  Users,
  Code2,
  Coins,
  Bot,
  Radar,
  BarChart3,
  ShieldCheck,
  FileText,
  Settings,
  Plus,
  KeyRound,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Zap,
  ArrowRight,
  Lock,
  Sliders,
  ChevronDown,
  Monitor,
  HeartPulse,
} from 'lucide-react';
import { IsometricChipGraphic, SentinelShieldBadge } from './IsometricChipGraphic';
import {
  PaymentRecord,
  AuditLogItem,
  WitnessKeyRecord,
  ManagedUserRecord,
  AgentOperationItem,
  PaymentRail,
  PricingTierName,
} from '../utils/cryptoEngine';

export type AdminSectionId =
  | 'dashboard'
  | 'user-management'
  | 'api-usage'
  | 'payment-settlements'
  | 'sentinel-ops'
  | 'global-analytics'
  | 'verifications-witness'
  | 'system-logs'
  | 'security-settings';

interface AdminPanelPageProps {
  currentSlot: number;
  payments: PaymentRecord[];
  auditLogs: AuditLogItem[];
  witnessKeys: WitnessKeyRecord[];
  managedUsers: ManagedUserRecord[];
  agentOps: AgentOperationItem[];
  onCreateUser: (handle: string, email: string, tier: PricingTierName) => Promise<void>;
  onAddCredits: (userHandle: string, credits: number, rail: PaymentRail) => Promise<void>;
  onIssueApiKey: (userHandle: string) => Promise<void>;
  onRotateWitnessKey: () => Promise<void>;
  onUpdateUserRateLimit: (uid: string, newRps: number) => void;
  onToggleAgentStatus: (agentId: string) => void;
  onReturnToPlatform: () => void;
}

export const AdminPanelPage: React.FC<AdminPanelPageProps> = ({
  currentSlot,
  payments,
  auditLogs,
  witnessKeys,
  managedUsers,
  agentOps,
  onCreateUser,
  onAddCredits,
  onIssueApiKey,
  onRotateWitnessKey,
  onUpdateUserRateLimit,
  onToggleAgentStatus,
  onReturnToPlatform,
}) => {
  const [activeSection, setActiveSection] = useState<AdminSectionId>('dashboard');
  const [chartRange, setChartRange] = useState<'24h' | '7d' | '30d' | '90d'>('24h');
  const [newUserModalOpen, setNewUserModalOpen] = useState(false);
  const [addCreditsModalOpen, setAddCreditsModalOpen] = useState(false);
  const [newUserHandle, setNewUserHandle] = useState('');
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserTier, setNewUserTier] = useState<PricingTierName>('Pro');
  const [creditTargetUser, setCreditTargetUser] = useState('tradebot42');
  const [creditAmount, setCreditAmount] = useState(1500);
  const [creditRail, setCreditRail] = useState<PaymentRail>('SOL');
  const [userFormError, setUserFormError] = useState<string | null>(null);
  const [globalBurstLimit, setGlobalBurstLimit] = useState(250);
  const [strictMtlsEnabled, setStrictMtlsEnabled] = useState(true);
  const [autoKeyRotationHours, setAutoKeyRotationHours] = useState(24);
  const [briefingSequence, setBriefingSequence] = useState(1);

  const activeKey = witnessKeys.find((k) => k.status === 'Active') || witnessKeys[0];

  const totalCredits = managedUsers.reduce((acc, u) => acc + u.credits, 7_638_000);

  // Side panel options matching the prompt:
  // "the side panel on the admin page would have options for user management, system logs, security settings, global analytics & intelligence, api usage, payment & settlements, verifications & witness and sentinel ops"
  const sidebarItems: {
    id: AdminSectionId;
    label: string;
    icon: React.FC<{ className?: string }>;
  }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: Home },
    { id: 'user-management', label: 'User Management', icon: Users },
    { id: 'api-usage', label: 'API Usage', icon: Code2 },
    { id: 'payment-settlements', label: 'Payment & Settlements', icon: Coins },
    { id: 'sentinel-ops', label: 'Sentinel Ops', icon: Radar },
    { id: 'global-analytics', label: 'Global Analytics & Intelligence', icon: BarChart3 },
    { id: 'verifications-witness', label: 'Verifications & Witness', icon: ShieldCheck },
    { id: 'system-logs', label: 'System Logs', icon: FileText },
    { id: 'security-settings', label: 'Security Settings', icon: Settings },
  ];

  const handleSubmitNewUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUserHandle.trim() || !newUserEmail.trim() || !newUserEmail.includes('@')) {
      setUserFormError('Please provide a valid operator handle and email address.');
      return;
    }
    setUserFormError(null);
    await onCreateUser(newUserHandle.trim(), newUserEmail.trim(), newUserTier);
    setNewUserHandle('');
    setNewUserEmail('');
    setNewUserModalOpen(false);
  };

  const handleSubmitAddCredits = async (e: React.FormEvent) => {
    e.preventDefault();
    await onAddCredits(creditTargetUser, creditAmount, creditRail);
    setAddCreditsModalOpen(false);
  };

  return (
    <div className="min-h-[calc(100vh-64px)] flex flex-col lg:flex-row">
      {/* LEFT SIDEBAR matching Image 4 + all 8 requested sections */}
      <aside className="w-full lg:w-[256px] shrink-0 bg-[#080d16]/95 border-b lg:border-b-0 lg:border-r border-[#1e293b] p-3.5 flex flex-col justify-between gap-4">
        <div className="space-y-3">
          {/* Control Center Header */}
          <div className="px-2.5 py-1.5 flex items-center justify-between border-b border-slate-800/80">
            <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-cyan-300">
              Platform Control Center
            </span>
            <span className="text-[10px] font-mono text-slate-400">v0.7.2</span>
          </div>

          {/* Sidebar Nav Links */}
          <nav aria-label="Admin Sidebar Navigation" className="space-y-1.5">
            {sidebarItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeSection === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveSection(item.id)}
                  className={`cyber-cut-sm w-full px-3.5 py-2.5 text-xs font-semibold flex items-center justify-between gap-2.5 transition-all cursor-pointer border ${
                    isActive
                      ? 'bg-gradient-to-r from-cyan-500/30 via-blue-600/30 to-purple-600/30 text-white border-cyan-400/80 shadow-[0_0_16px_rgba(6,182,212,0.28)]'
                      : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
                  }`}
                >
                  <div className="flex items-center gap-2.5 truncate">
                    {item.id === 'sentinel-ops' ? (
                      <SentinelShieldBadge size="xs" />
                    ) : (
                      <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-cyan-300' : 'text-cyan-400/80'}`} />
                    )}
                    <span className="truncate">{item.label}</span>
                  </div>
                  <ChevronDown
                    className={`w-3.5 h-3.5 shrink-0 transition-transform ${
                      isActive ? '-rotate-90 text-cyan-300' : 'text-slate-500'
                    }`}
                  />
                </button>
              );
            })}
          </nav>
        </div>

        {/* Bottom MoltAlpha Neon Data Core & Platform Control Center Badge matching Image 4 */}
        <div className="hidden lg:flex flex-col items-center text-center pt-4 border-t border-slate-800/80 space-y-2">
          <IsometricChipGraphic compact variant="datacore" className="max-w-[185px]" />
          <div className="font-display font-extrabold text-base text-white tracking-tight">
            MoltALPHA Admin
          </div>
          <div className="text-[11px] text-slate-400">Platform Control Center</div>
          <div className="flex items-center justify-center gap-1.5 pt-1">
            <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/40">
              Solana
            </span>
            <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
              USDC
            </span>
            <span className="cyber-cut-sm px-2.5 py-0.5 text-[10px] font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
              Nano
            </span>
          </div>
          <div className="text-[10px] font-mono text-slate-500 pt-0.5">v0.7.2</div>
        </div>
      </aside>

      {/* MAIN ADMIN CONTENT AREA */}
      <div className="flex-1 min-w-0 p-4 sm:p-6 space-y-5">
        {/* Top Admin Status Subbar matching Image 4 */}
        <div className="molt-card cyber-ruler-left px-4 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2.5 font-display font-bold text-base text-white">
              <SentinelShieldBadge size="sm" />
              <span>Admin Panel</span>
            </div>
            <span className="cyber-cut-sm inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs font-mono font-semibold">
              <span className="w-1.5 h-1.5 bg-emerald-400" />
              SYSTEM OPERATIONAL
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-slate-300">
            <span className="cyber-cut-sm px-3 py-1 bg-amber-500/15 border border-amber-400/50 text-amber-300 font-semibold">
              Environment: Isolated Dev Sandbox (SIMULATED DEMO)
            </span>
            <span className="text-slate-400">Version: v0.7.2</span>
            <span className="text-cyan-300 tabular-nums">
              Nov 6, 2026 00:15:23 (EST) · Slot #{currentSlot.toLocaleString()}
            </span>
            <div className="flex items-center gap-2 pl-2 border-l border-slate-800">
              <div className="w-7 h-7 cyber-cut-sm bg-cyan-500/20 border border-cyan-400 flex items-center justify-center text-cyan-300 font-bold text-xs">
                A
              </div>
              <div className="leading-tight">
                <div className="font-bold text-white text-xs">admin (sandbox)</div>
                <div className="text-[10px] text-slate-400">Server-Verified RBAC Required in Prod</div>
              </div>
            </div>
          </div>
        </div>

        {/* Admin Dashboard Title + Primary Action Buttons matching Image 4 */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 cyber-cut-sm bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-400">
              <Monitor className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-display font-extrabold text-2xl sm:text-3xl text-white">
                Admin Dashboard
              </h1>
              <p className="text-xs sm:text-sm text-slate-300">
                Platform operations, users, credits, payments, agents and system health (Sandbox Simulation).
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={() => setNewUserModalOpen(true)}
              className="molt-btn-cyan px-3.5 py-2 text-xs inline-flex items-center gap-1.5 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Create User</span>
            </button>

            <button
              type="button"
              onClick={() => setAddCreditsModalOpen(true)}
              className="cyber-btn-ghost px-3.5 py-2 text-xs font-mono uppercase tracking-wider text-purple-200 inline-flex items-center gap-1.5 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5 text-purple-400" />
              <span>Add Credits</span>
            </button>

            <button
              type="button"
              onClick={() => onIssueApiKey('tradebot42')}
              className="cyber-btn-ghost px-3.5 py-2 text-xs font-mono uppercase tracking-wider text-slate-200 inline-flex items-center gap-1.5 cursor-pointer"
            >
              <KeyRound className="w-3.5 h-3.5 text-cyan-400" />
              <span>Issue API Key</span>
            </button>

            <button
              type="button"
              onClick={onRotateWitnessKey}
              className="cyber-btn-ghost px-3.5 py-2 text-xs font-mono uppercase tracking-wider text-emerald-300 inline-flex items-center gap-1.5 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 text-emerald-400" />
              <span>Rotate Ed25519 Key</span>
            </button>
          </div>
        </div>

        {/* DAILY BRIEFING FOR KPIs & SECURITY ALERTS (Explicitly labeled as SIMULATED DEMO per directive) */}
        <section
          className="molt-card-purple rounded-2xl p-4 border border-cyan-400/40"
          data-testid="live-daily-briefing"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="px-2.5 py-1 rounded-md bg-amber-500/20 border border-amber-400/50 text-amber-300 text-[11px] font-mono font-bold uppercase">
                SIMULATED BRIEFING #{briefingSequence} (DEMO)
              </span>
              <span className="text-xs sm:text-sm font-semibold text-white">
                Executive KPI &amp; Security Alert Telemetry — Active Signer Epoch:{' '}
                <code className="text-emerald-300 font-mono">{activeKey.keyId}</code>
              </span>
            </div>

            <div className="flex items-center gap-3 text-xs font-mono">
              <span className="text-emerald-400">
                ● 99.98% SLA · 1,248,320 Calls (24h) · 0 Unmitigated Breaches
              </span>
              <button
                type="button"
                onClick={() => setBriefingSequence((n) => n + 1)}
                className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-cyan-300 inline-flex items-center gap-1 cursor-pointer"
              >
                <RefreshCw className="w-3 h-3" />
                <span>Sync Briefing</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3 text-xs">
            <div className="rounded-xl bg-slate-950/80 border border-slate-800/90 p-3 flex items-start justify-between gap-2">
              <div>
                <div className="text-slate-400 font-medium">KPI Velocity (24h)</div>
                <div className="text-white font-semibold mt-0.5">
                  +18.9% Multi-Rail Revenue ($1,482.75) · 52.3% Pro Tier Adoption
                </div>
              </div>
              <span className="font-mono text-emerald-400 font-bold shrink-0">NOMINAL</span>
            </div>

            <div className="rounded-xl bg-slate-950/80 border border-slate-800/90 p-3 flex items-start justify-between gap-2">
              <div>
                <div className="text-slate-400 font-medium">Security Alert Digest</div>
                <div className="text-white font-semibold mt-0.5">
                  POPCAT/SOL LP volatility isolated · Rate-limit guard blocked 14 burst spikes
                </div>
              </div>
              <span className="font-mono text-cyan-300 font-bold shrink-0">GUARDED</span>
            </div>

            <div className="rounded-xl bg-slate-950/80 border border-slate-800/90 p-3 flex items-start justify-between gap-2">
              <div>
                <div className="text-slate-400 font-medium">Cryptographic Integrity</div>
                <div className="text-white font-semibold mt-0.5">
                  Ed25519 Public Key {activeKey.publicKey.slice(0, 20)}... verified across 512 proofs
                </div>
              </div>
              <span className="font-mono text-emerald-400 font-bold shrink-0">VERIFIED</span>
            </div>
          </div>
        </section>

        {/* SECTION SWITCHER FOR SPECIFIC SIDEBAR VIEWS (when not on default Dashboard, shows focused control module above the full control grid) */}
        {activeSection !== 'dashboard' && (
          <section className="molt-card rounded-2xl p-5 space-y-4 border-2 border-cyan-400/50">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div>
                <span className="text-[11px] font-mono uppercase text-cyan-400">
                  ACTIVE CONTROL MODULE
                </span>
                <h2 className="font-display font-extrabold text-xl text-white">
                  {sidebarItems.find((s) => s.id === activeSection)?.label}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setActiveSection('dashboard')}
                className="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-slate-300 hover:text-white cursor-pointer"
              >
                Return to Overview Grid
              </button>
            </div>

            {/* 1. USER MANAGEMENT & API RATE LIMITS */}
            {(activeSection === 'user-management' || activeSection === 'api-usage') && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-950/80 p-3.5 rounded-xl border border-slate-800">
                  <div>
                    <div className="text-xs font-bold text-white">
                      Global API Burst Rate-Limit Ceiling: {globalBurstLimit} req/sec
                    </div>
                    <div className="text-[11px] text-slate-400">
                      Adjust per-operator RPS limits or enforce global token-bucket throttling.
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={20}
                      max={1000}
                      value={globalBurstLimit}
                      onChange={(e) => setGlobalBurstLimit(Number(e.target.value))}
                      aria-label="Global API Burst Rate Limit"
                      className="w-36 accent-cyan-400 cursor-pointer"
                    />
                    <span className="font-mono text-xs text-cyan-300 font-bold tabular-nums">
                      {globalBurstLimit} RPS
                    </span>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-400">
                        <th className="py-2 px-3">Operator Handle</th>
                        <th className="py-2 px-3">Email</th>
                        <th className="py-2 px-3">Tier</th>
                        <th className="py-2 px-3 text-right">Credits</th>
                        <th className="py-2 px-3 text-center">API Rate Limit (RPS)</th>
                        <th className="py-2 px-3 text-center">Status</th>
                        <th className="py-2 px-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {managedUsers.map((u) => (
                        <tr key={u.uid} className="hover:bg-slate-900/60">
                          <td className="py-2.5 px-3 font-mono font-bold text-white">{u.handle}</td>
                          <td className="py-2.5 px-3 text-slate-300">{u.email}</td>
                          <td className="py-2.5 px-3">
                            <span className="px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-300 font-mono text-[11px]">
                              {u.tier}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-white tabular-nums">
                            {u.credits.toLocaleString()}
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <div className="inline-flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() =>
                                  onUpdateUserRateLimit(u.uid, Math.max(5, u.rateLimitRps - 25))
                                }
                                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-mono cursor-pointer"
                              >
                                -
                              </button>
                              <span className="font-mono font-bold text-cyan-300 tabular-nums w-16 text-center">
                                {u.rateLimitRps} rps
                              </span>
                              <button
                                type="button"
                                onClick={() => onUpdateUserRateLimit(u.uid, u.rateLimitRps + 25)}
                                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-mono cursor-pointer"
                              >
                                +
                              </button>
                            </div>
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono text-[10px]">
                              {u.status}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            <button
                              type="button"
                              onClick={() => onIssueApiKey(u.handle)}
                              className="px-2.5 py-1 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 font-mono text-[11px] cursor-pointer"
                            >
                              Issue Key
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 2. VERIFICATIONS & WITNESS / SECURITY SETTINGS (Cryptographic Key Rotation) */}
            {(activeSection === 'verifications-witness' ||
              activeSection === 'security-settings') && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="rounded-xl bg-slate-950/85 border border-slate-800 p-4 space-y-2">
                    <div className="text-xs font-bold text-white flex items-center gap-2">
                      <Lock className="w-4 h-4 text-cyan-400" />
                      <span>Strict mTLS &amp; RFC 8785 Enforcement</span>
                    </div>
                    <p className="text-xs text-slate-400">
                      Require canonical JSON serialization and Ed25519 signature verification on all
                      agent webhook callbacks.
                    </p>
                    <button
                      type="button"
                      onClick={() => setStrictMtlsEnabled((v) => !v)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold cursor-pointer ${
                        strictMtlsEnabled
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {strictMtlsEnabled ? 'ENABLED (STRICT ZERO-TRUST)' : 'DISABLED'}
                    </button>
                  </div>

                  <div className="rounded-xl bg-slate-950/85 border border-slate-800 p-4 space-y-2">
                    <div className="text-xs font-bold text-white flex items-center gap-2">
                      <Sliders className="w-4 h-4 text-cyan-400" />
                      <span>Automated Key Rotation Cadence</span>
                    </div>
                    <p className="text-xs text-slate-400">
                      Scheduled epoch interval for rotating Ed25519 state witness signing keys.
                    </p>
                    <div className="flex items-center gap-2">
                      {[12, 24, 48].map((hrs) => (
                        <button
                          key={hrs}
                          type="button"
                          onClick={() => setAutoKeyRotationHours(hrs)}
                          className={`px-2.5 py-1 rounded text-xs font-mono cursor-pointer ${
                            autoKeyRotationHours === hrs
                              ? 'bg-cyan-500/30 text-cyan-200 border border-cyan-400'
                              : 'bg-slate-900 text-slate-400'
                          }`}
                        >
                          Every {hrs}h
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-xl bg-slate-950/85 border border-slate-800 p-4 flex flex-col justify-between">
                    <div>
                      <div className="text-xs font-bold text-white">Manual Emergency Key Rotation</div>
                      <p className="text-xs text-slate-400 mt-1">
                        Immediately generate a new Ed25519 keypair epoch and mark current key as
                        Rotated.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={onRotateWitnessKey}
                      className="molt-btn-cyan mt-3 py-2 px-4 rounded-xl text-xs font-bold inline-flex items-center justify-center gap-2 cursor-pointer"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      <span>Rotate Ed25519 Signing Key Now</span>
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-bold text-slate-300">
                    Cryptographic Ed25519 Witness Key Epochs
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {witnessKeys.map((k) => (
                      <div
                        key={k.id}
                        className="rounded-xl bg-slate-950/90 border border-slate-800 p-3.5 space-y-1.5 text-xs font-mono"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-white">{k.keyId}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              k.status === 'Active'
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                                : k.status === 'Rotated'
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                                  : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                            }`}
                          >
                            {k.status}
                          </span>
                        </div>
                        <div className="text-[11px] text-cyan-300 truncate">{k.publicKey}</div>
                        <div className="text-[10px] text-slate-400 flex justify-between">
                          <span>{k.createdAt}</span>
                          <span>{k.signedProofsCount.toLocaleString()} proofs</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 3. SYSTEM LOGS / PAYMENT & SETTLEMENTS / SENTINEL OPS / GLOBAL ANALYTICS */}
            {(activeSection === 'system-logs' ||
              activeSection === 'payment-settlements' ||
              activeSection === 'sentinel-ops' ||
              activeSection === 'global-analytics') && (
              <div className="text-xs text-slate-300 space-y-2">
                <p>
                  Showing live synchronized records for{' '}
                  <strong className="text-cyan-300">
                    {sidebarItems.find((s) => s.id === activeSection)?.label}
                  </strong>
                  . Use the interactive tables and agent toggles below to audit events, verify
                  SOL/USDC/Nano settlements, or pause autonomous Sentinel workers.
                </p>
              </div>
            )}
          </section>
        )}

        {/* 5 TOP KPI CARDS ROW matching Image 4 */}
        <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3.5">
          {/* Total Users */}
          <div className="molt-card rounded-2xl p-3.5 flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-400 shrink-0">
              <Users className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-300 truncate">Total Users</div>
              <div className="font-display font-extrabold text-xl 2xl:text-2xl text-white tabular-nums">
                {(1842 + (managedUsers.length - 5)).toLocaleString()}
              </div>
              <div className="text-[11px] font-mono text-emerald-400 mt-0.5">▲ +6.3% (24h)</div>
            </div>
          </div>

          {/* Active API Keys */}
          <div className="molt-card rounded-2xl p-3.5 flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-400 shrink-0">
              <KeyRound className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-300 truncate">Active API Keys</div>
              <div className="font-display font-extrabold text-xl 2xl:text-2xl text-white tabular-nums">
                {(3976 + (auditLogs.length - 5)).toLocaleString()}
              </div>
              <div className="text-[11px] font-mono text-emerald-400 mt-0.5">▲ +8.1% (24h)</div>
            </div>
          </div>

          {/* Credits (Total) */}
          <div className="molt-card rounded-2xl p-3.5 flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-400 shrink-0">
              <LayersIcon />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-300 truncate">Credits (Total)</div>
              <div className="font-display font-extrabold text-xl 2xl:text-2xl text-white tabular-nums">
                {totalCredits.toLocaleString()}
              </div>
              <div className="text-[11px] font-mono text-emerald-400 mt-0.5">▲ +12.4% (24h)</div>
            </div>
          </div>

          {/* Revenue (7d) */}
          <div className="molt-card rounded-2xl p-3.5 flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-amber-500/15 border border-amber-400/40 flex items-center justify-center text-amber-400 shrink-0">
              <Coins className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-300 truncate">Revenue (7d)</div>
              <div className="font-display font-extrabold text-xl 2xl:text-2xl text-white tabular-nums">
                $1,482.75
              </div>
              <div className="text-[11px] font-mono text-emerald-400 mt-0.5">▲ +18.9%</div>
            </div>
          </div>

          {/* Risk Alerts (24h) */}
          <div className="molt-card-purple rounded-2xl p-3.5 flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-rose-500/15 border border-rose-400/40 flex items-center justify-center text-rose-400 shrink-0">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-300 truncate">Risk Alerts (24h)</div>
              <div className="font-display font-extrabold text-xl 2xl:text-2xl text-white tabular-nums">
                0
              </div>
              <div className="text-[11px] text-emerald-400 flex items-center gap-1 mt-0.5">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">No active threats</span>
              </div>
            </div>
          </div>
        </section>

        {/* SECOND ROW: API USAGE & CREDITS CHART (Left 8 cols) + PLATFORM HEALTH (Right 4 cols) matching Image 4 */}
        <section className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-stretch">
          {/* API Usage & Credits */}
          <div className="xl:col-span-8 molt-card rounded-2xl p-5 flex flex-col justify-between space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 font-display font-bold text-base sm:text-lg text-white">
                <Code2 className="w-5 h-5 text-cyan-400" />
                <span>API Usage &amp; Credits</span>
              </div>
              <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs font-mono">
                {(['24h', '7d', '30d', '90d'] as const).map((rng) => (
                  <button
                    key={rng}
                    type="button"
                    onClick={() => setChartRange(rng)}
                    className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
                      chartRange === rng
                        ? 'bg-cyan-500/30 text-cyan-200 border border-cyan-400/50 font-bold'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {rng}
                  </button>
                ))}
              </div>
            </div>

            <svg viewBox="0 0 640 190" className="w-full h-44 overflow-visible">
              <defs>
                <linearGradient id="adminApiCyan" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00F0FF" stopOpacity="0.4" />
                  <stop offset="100%" stopColor="#00F0FF" stopOpacity="0.0" />
                </linearGradient>
                <linearGradient id="adminCreditsPurple" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#C084FC" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#C084FC" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Left Y-axis (API Calls) & Right Y-axis (Credits Used) */}
              {[
                { y: 20, left: '100K', right: '500K' },
                { y: 48, left: '80K', right: '400K' },
                { y: 76, left: '60K', right: '300K' },
                { y: 104, left: '40K', right: '200K' },
                { y: 132, left: '20K', right: '100K' },
                { y: 158, left: '0', right: '0' },
              ].map((r) => (
                <g key={r.left}>
                  <text x="8" y={r.y + 4} fill="#94A3B8" fontSize="10" fontFamily="JetBrains Mono">
                    {r.left}
                  </text>
                  <line
                    x1="44"
                    y1={r.y}
                    x2="590"
                    y2={r.y}
                    stroke="#1E293B"
                    strokeDasharray="3 3"
                  />
                  <text x="598" y={r.y + 4} fill="#C084FC" fontSize="10" fontFamily="JetBrains Mono">
                    {r.right}
                  </text>
                </g>
              ))}

              {/* Cyan Area: API Calls */}
              <path
                d="M44,132 C85,96 115,124 155,108 C195,92 225,84 265,98 C305,112 340,68 385,78 C430,88 465,46 510,56 C545,64 565,34 590,38 L590,158 L44,158 Z"
                fill="url(#adminApiCyan)"
              />
              <path
                d="M44,132 C85,96 115,124 155,108 C195,92 225,84 265,98 C305,112 340,68 385,78 C430,88 465,46 510,56 C545,64 565,34 590,38"
                fill="none"
                stroke="#00F0FF"
                strokeWidth="2.6"
              />

              {/* Purple Area: Credits Used */}
              <path
                d="M44,146 C85,126 115,138 155,128 C195,118 225,112 265,122 C305,132 340,102 385,110 C430,118 465,86 510,94 C545,100 565,78 590,82 L590,158 L44,158 Z"
                fill="url(#adminCreditsPurple)"
              />
              <path
                d="M44,146 C85,126 115,138 155,128 C195,118 225,112 265,122 C305,132 340,102 385,110 C430,118 465,86 510,94 C545,100 565,78 590,82"
                fill="none"
                stroke="#C084FC"
                strokeWidth="2.4"
              />

              {/* X-axis labels */}
              {[
                { x: 54, t: '00:00' },
                { x: 130, t: '03:00' },
                { x: 206, t: '06:00' },
                { x: 282, t: '09:00' },
                { x: 358, t: '12:00' },
                { x: 434, t: '15:00' },
                { x: 510, t: '18:00' },
                { x: 578, t: '21:00' },
              ].map((c) => (
                <text
                  key={c.t}
                  x={c.x}
                  y="178"
                  fill="#94A3B8"
                  fontSize="10"
                  textAnchor="middle"
                  fontFamily="JetBrains Mono"
                >
                  {c.t}
                </text>
              ))}
            </svg>

            <div className="flex flex-wrap items-center justify-center gap-6 text-xs font-mono pt-1">
              <span className="inline-flex items-center gap-2 text-slate-200">
                <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" />
                API Calls (Total: 1,248,320)
              </span>
              <span className="inline-flex items-center gap-2 text-slate-200">
                <span className="w-2.5 h-2.5 rounded-full bg-purple-400" />
                Credits Used (Total: 3,284,750)
              </span>
            </div>
          </div>

          {/* Platform Health (Right 4 cols) matching Image 4 */}
          <div className="xl:col-span-4 molt-card-purple rounded-2xl p-5 flex flex-col justify-between space-y-4">
            <div className="flex items-center gap-2 font-display font-bold text-base sm:text-lg text-white">
              <HeartPulse className="w-5 h-5 text-cyan-400" />
              <span>Platform Health</span>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 my-auto">
              {/* 100% Operational Ring */}
              <div className="relative w-32 h-32 shrink-0 flex items-center justify-center">
                <svg viewBox="0 0 36 36" className="w-32 h-32 -rotate-90">
                  <circle cx="18" cy="18" r="14.5" fill="none" stroke="#1E293B" strokeWidth="3.8" />
                  <circle
                    cx="18"
                    cy="18"
                    r="14.5"
                    fill="none"
                    stroke="#10B981"
                    strokeWidth="3.8"
                    strokeDasharray="92 100"
                    strokeLinecap="round"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="font-display font-extrabold text-2xl text-white tabular-nums">
                    100%
                  </span>
                  <span className="text-[11px] text-slate-300">Operational</span>
                </div>
              </div>

              {/* 6 Health Subsystems */}
              <div className="space-y-2 flex-1 w-full text-xs">
                {[
                  'API Services',
                  'Sentinel Engine',
                  'Payment Verifiers',
                  'Crypto RPC (Solana)',
                  'Database (Primary)',
                  'Background Agents',
                ].map((svc) => (
                  <div key={svc} className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-slate-200">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span className="truncate">{svc}</span>
                    </span>
                    <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px] font-mono font-semibold">
                      Online
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* THIRD ROW: RECENT PAYMENTS & CREDITS (5 cols) + AGENT OPERATIONS (4 cols) + QUICK ACTIONS (3 cols) matching Image 4 */}
        <section className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-stretch">
          {/* Recent Payments & Credits */}
          <div className="xl:col-span-5 molt-card rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
              <div className="flex items-center gap-2 font-display font-bold text-base text-white">
                <Coins className="w-4 h-4 text-cyan-400" />
                <span>Recent Payments &amp; Credits</span>
              </div>
              <button
                type="button"
                onClick={() => setActiveSection('payment-settlements')}
                className="text-xs text-slate-300 hover:text-cyan-300 inline-flex items-center gap-1 cursor-pointer"
              >
                <span>View All</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] text-slate-400">
                    <th className="py-2 px-1.5">Time</th>
                    <th className="py-2 px-1.5">User</th>
                    <th className="py-2 px-1.5 text-right">Amount</th>
                    <th className="py-2 px-1.5">Method</th>
                    <th className="py-2 px-1.5 text-right">Credits</th>
                    <th className="py-2 px-1.5 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                  {payments.slice(0, 5).map((p) => (
                    <tr key={p.id} className="hover:bg-slate-900/60">
                      <td className="py-2 px-1.5 text-slate-400 tabular-nums">{p.time}</td>
                      <td className="py-2 px-1.5 text-white font-semibold">{p.user}</td>
                      <td className="py-2 px-1.5 text-right text-white tabular-nums">
                        ${p.amountUsd.toFixed(2)}
                      </td>
                      <td className="py-2 px-1.5 text-cyan-300">{p.method}</td>
                      <td className="py-2 px-1.5 text-right text-slate-200 tabular-nums">
                        {p.credits.toLocaleString()}
                      </td>
                      <td className="py-2 px-1.5 text-right">
                        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px]">
                          ✓ {p.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Agent Operations */}
          <div className="xl:col-span-4 molt-card rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
              <div className="flex items-center gap-2 font-display font-bold text-base text-white">
                <Bot className="w-4 h-4 text-cyan-400" />
                <span>Agent Operations</span>
              </div>
              <button
                type="button"
                onClick={() => setActiveSection('sentinel-ops')}
                className="text-xs text-slate-300 hover:text-cyan-300 inline-flex items-center gap-1 cursor-pointer"
              >
                <span>View Agents</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="space-y-2">
              {agentOps.map((agent) => (
                <div
                  key={agent.id}
                  className="rounded-xl bg-slate-950/80 border border-slate-800/90 px-3 py-2 flex items-center justify-between gap-2 text-xs"
                >
                  <span className="font-medium text-white truncate">{agent.name}</span>
                  <div className="flex items-center gap-2.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => onToggleAgentStatus(agent.id)}
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold cursor-pointer ${
                        agent.status === 'Running'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      }`}
                    >
                      ● {agent.status}
                    </button>
                    <span className="font-mono text-[11px] text-slate-300 tabular-nums w-28 text-right">
                      {agent.metricLabel}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="xl:col-span-3 molt-card-purple rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3">
            <div className="flex items-center gap-2 font-display font-bold text-base text-white border-b border-slate-800 pb-2.5">
              <Zap className="w-4 h-4 text-cyan-400" />
              <span>Quick Actions</span>
            </div>

            <div className="grid grid-cols-2 gap-2.5 my-auto">
              {[
                { label: 'Manage Users', section: 'user-management' as AdminSectionId, icon: Users },
                {
                  label: 'Credit Adjustments',
                  section: 'payment-settlements' as AdminSectionId,
                  icon: Coins,
                },
                { label: 'Review Alerts', section: 'sentinel-ops' as AdminSectionId, icon: AlertTriangle },
                {
                  label: 'View Witnesses',
                  section: 'verifications-witness' as AdminSectionId,
                  icon: ShieldCheck,
                },
                { label: 'System Logs', section: 'system-logs' as AdminSectionId, icon: FileText },
                {
                  label: 'Platform Settings',
                  section: 'security-settings' as AdminSectionId,
                  icon: Settings,
                },
              ].map((qa) => {
                const Icon = qa.icon;
                return (
                  <button
                    key={qa.label}
                    type="button"
                    onClick={() => setActiveSection(qa.section)}
                    className="rounded-xl bg-slate-900/90 hover:bg-slate-800 border border-cyan-500/30 hover:border-cyan-400 p-3 text-left flex items-center gap-2.5 transition-colors cursor-pointer"
                  >
                    <Icon className="w-4 h-4 text-cyan-400 shrink-0" />
                    <span className="text-xs font-semibold text-white leading-tight">
                      {qa.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        {/* FOURTH ROW: RECENT ACTIVITY (AUDIT LOG) (5 cols) + CREDIT DISTRIBUTION (3 cols) + TOP API USAGE (4 cols) matching Image 4 */}
        <section className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-stretch">
          {/* Recent Activity (Audit Log) */}
          <div className="xl:col-span-5 molt-card rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
              <div className="flex items-center gap-2 font-display font-bold text-base text-white">
                <FileText className="w-4 h-4 text-cyan-400" />
                <span>Recent Activity (Audit Log)</span>
              </div>
              <button
                type="button"
                onClick={() => setActiveSection('system-logs')}
                className="text-xs text-slate-300 hover:text-cyan-300 inline-flex items-center gap-1 cursor-pointer"
              >
                <span>View Full Log</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] text-slate-400">
                    <th className="py-2 px-1.5">Time</th>
                    <th className="py-2 px-1.5">Actor</th>
                    <th className="py-2 px-1.5">Action</th>
                    <th className="py-2 px-1.5">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                  {auditLogs.slice(0, 5).map((log) => (
                    <tr key={log.id} className="hover:bg-slate-900/60">
                      <td className="py-2 px-1.5 text-slate-400 tabular-nums whitespace-nowrap">
                        {log.time}
                      </td>
                      <td className="py-2 px-1.5 text-cyan-300 font-semibold whitespace-nowrap">
                        {log.actor}
                      </td>
                      <td className="py-2 px-1.5 text-white whitespace-nowrap">{log.action}</td>
                      <td className="py-2 px-1.5 text-slate-300 truncate max-w-[210px]">
                        {log.details}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Credit Distribution (Active Users) */}
          <div className="xl:col-span-3 molt-card-purple rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3">
            <div className="flex items-center gap-2 font-display font-bold text-base text-white border-b border-slate-800 pb-2.5">
              <LayersIcon />
              <span>Credit Distribution (Active Users)</span>
            </div>

            <div className="flex items-center justify-between gap-3 my-auto">
              <div className="relative w-28 h-28 shrink-0 flex items-center justify-center">
                <svg viewBox="0 0 36 36" className="w-28 h-28 -rotate-90">
                  <circle cx="18" cy="18" r="14" fill="none" stroke="#1E293B" strokeWidth="4.4" />
                  <circle
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke="#00F0FF"
                    strokeWidth="4.4"
                    strokeDasharray="46 100"
                  />
                  <circle
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke="#3B82F6"
                    strokeWidth="4.4"
                    strokeDasharray="25 100"
                    strokeDashoffset="-46"
                  />
                  <circle
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke="#A855F7"
                    strokeWidth="4.4"
                    strokeDasharray="11 100"
                    strokeDashoffset="-71"
                  />
                  <circle
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke="#F59E0B"
                    strokeWidth="4.4"
                    strokeDasharray="6 100"
                    strokeDashoffset="-82"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="font-display font-extrabold text-sm text-white tabular-nums">
                    7.85M
                  </span>
                  <span className="text-[10px] text-slate-400">Credits</span>
                </div>
              </div>

              <div className="space-y-2 text-xs flex-1">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-slate-200">
                    <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" />
                    Pro (1,500)
                  </span>
                  <span className="font-mono font-bold text-white tabular-nums">52.3%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-slate-200">
                    <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                    Starter (150)
                  </span>
                  <span className="font-mono font-bold text-white tabular-nums">28.7%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-slate-200">
                    <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                    Micro (25)
                  </span>
                  <span className="font-mono font-bold text-white tabular-nums">12.6%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-slate-200">
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                    Custom
                  </span>
                  <span className="font-mono font-bold text-white tabular-nums">6.4%</span>
                </div>
              </div>
            </div>
          </div>

          {/* Top API Usage (24h) */}
          <div className="xl:col-span-4 molt-card rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
              <div className="flex items-center gap-2 font-display font-bold text-base text-white">
                <BarChart3 className="w-4 h-4 text-cyan-400" />
                <span>Top API Usage (24h)</span>
              </div>
              <button
                type="button"
                onClick={() => setActiveSection('api-usage')}
                className="text-xs text-slate-300 hover:text-cyan-300 inline-flex items-center gap-1 cursor-pointer"
              >
                <span>View Details</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="space-y-2.5 my-auto">
              {[
                { ep: '/v1/pool/risk', calls: '482,310', pct: '38.6%', width: '78%' },
                { ep: '/v1/quote', calls: '286,504', pct: '22.9%', width: '52%' },
                { ep: '/v1/signal', calls: '183,927', pct: '14.7%', width: '36%' },
                { ep: '/v1/intent', calls: '146,220', pct: '11.7%', width: '28%' },
                { ep: '/v1/witness', calls: '148,359', pct: '11.9%', width: '30%' },
              ].map((row) => (
                <div key={row.ep} className="grid grid-cols-12 items-center gap-2 text-xs font-mono">
                  <span className="col-span-4 text-slate-200 truncate">{row.ep}</span>
                  <div className="col-span-4 h-2.5 rounded-full bg-slate-900 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-blue-500"
                      style={{ width: row.width }}
                    />
                  </div>
                  <span className="col-span-4 text-right text-slate-300 tabular-nums">
                    {row.calls} <span className="text-slate-400">({row.pct})</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      {/* CREATE USER MODAL */}
      {newUserModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-user-title"
        >
          <form
            onSubmit={handleSubmitNewUser}
            className="molt-card rounded-2xl max-w-md w-full p-6 space-y-4"
          >
            <h3 id="create-user-title" className="font-display font-bold text-lg text-white">
              Create Operator Account
            </h3>
            {userFormError && (
              <div className="rounded-xl bg-rose-500/20 border border-rose-500/40 p-2.5 text-xs text-rose-200">
                {userFormError}
              </div>
            )}
            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1">Operator Handle</label>
                <input
                  type="text"
                  value={newUserHandle}
                  onChange={(e) => setNewUserHandle(e.target.value)}
                  placeholder="e.g., quantnode_09"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white"
                />
              </div>
              <div>
                <label className="block text-slate-300 mb-1">Verified Email</label>
                <input
                  type="email"
                  value={newUserEmail}
                  onChange={(e) => setNewUserEmail(e.target.value)}
                  placeholder="ops@quantnode.sol"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white"
                />
              </div>
              <div>
                <label className="block text-slate-300 mb-1">Initial Tier</label>
                <select
                  value={newUserTier}
                  onChange={(e) => setNewUserTier(e.target.value as PricingTierName)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white"
                >
                  <option value="Micro">Micro (25 queries)</option>
                  <option value="Starter">Starter (150 queries)</option>
                  <option value="Pro">Pro (1,500 queries)</option>
                  <option value="Enterprise">Enterprise (Custom)</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setNewUserModalOpen(false)}
                className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs text-slate-300 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="molt-btn-cyan px-4 py-2 rounded-xl text-xs font-bold cursor-pointer"
              >
                Provision Operator
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ADD CREDITS MODAL */}
      {addCreditsModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-credits-title"
        >
          <form
            onSubmit={handleSubmitAddCredits}
            className="molt-card-purple rounded-2xl max-w-md w-full p-6 space-y-4"
          >
            <h3 id="add-credits-title" className="font-display font-bold text-lg text-white">
              Grant Multi-Rail Prepaid Credits
            </h3>
            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1">Target Operator</label>
                <input
                  type="text"
                  value={creditTargetUser}
                  onChange={(e) => setCreditTargetUser(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white font-mono"
                />
              </div>
              <div>
                <label className="block text-slate-300 mb-1">Credits to Grant</label>
                <input
                  type="number"
                  min={25}
                  max={1000000}
                  value={creditAmount}
                  onChange={(e) => setCreditAmount(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white font-mono"
                />
              </div>
              <div>
                <label className="block text-slate-300 mb-1">Settlement Rail</label>
                <div className="grid grid-cols-3 gap-2">
                  {(['SOL', 'USDC', 'Nano'] as PaymentRail[]).map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setCreditRail(r)}
                      className={`py-2 rounded-xl font-mono font-bold border cursor-pointer ${
                        creditRail === r
                          ? 'bg-cyan-500/25 border-cyan-400 text-cyan-200'
                          : 'bg-slate-900 border-slate-800 text-slate-400'
                      }`}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setAddCreditsModalOpen(false)}
                className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs text-slate-300 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="molt-btn-gradient px-4 py-2 rounded-xl text-xs font-bold cursor-pointer"
              >
                Verify &amp; Credit Account
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

const LayersIcon: React.FC = () => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    className="w-5 h-5 text-cyan-400 shrink-0"
  >
    <polygon points="12 2 2 7 12 12 22 7 12 2" />
    <polyline points="2 17 12 22 22 17" />
    <polyline points="2 12 12 17 22 12" />
  </svg>
);
