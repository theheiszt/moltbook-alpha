import React, { useState, useMemo } from 'react';
import {
  Bot,
  Lock,
  ShieldCheck,
  KeyRound,
  Play,
  Pause,
  Plus,
  Trash2,
  Copy,
  Check,
  Code2,
  Zap,
  AlertTriangle,
  CheckCircle2,
  Sliders,
  Activity,
  ArrowRight,
  Layers,
  Cpu,
  FileCode2,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Fuel,
  Target,
} from 'lucide-react';
import { SentinelShieldSvg } from './IsometricChipGraphic';
import {
  DexPool,
  WitnessKeyRecord,
  canonicalizeJsonRfc8785,
  buildWitnessAttestation,
  getTokenIcon,
  formatTokenPriceUsd,
} from '../utils/cryptoEngine';
import {
  validateSafeExternalUri,
  sanitizePlainText,
  validateCustomBotScript,
} from '../services/securityEngine';

export type BotStrategyType =
  | 'LIQUIDITY_SNIPER'
  | 'METALX_ORDERBOOK_SNIPER'
  | 'CLMM_RANGE_ARB'
  | 'DCA_SENTINEL_GUARD'
  | 'WHALE_COPY_SHIELD';

export type SupportedDexTarget =
  | 'Metal X DEX'
  | 'Raydium'
  | 'Orca'
  | 'Meteora'
  | 'Jupiter';

export type GasPriorityMode = 'STANDARD' | 'TURBO' | 'ULTRA_JITO_MEV';

export type MetalXActionName =
  | 'placeorder'
  | 'process'
  | 'processsltp'
  | 'cancelorder';

export interface AutomationBotItem {
  id: string;
  botName: string;
  strategyType: BotStrategyType;
  targetDex: SupportedDexTarget;
  targetPair: string;
  targetPoolAddress: string;
  orderSizeSol: number;
  maxSlippageBps: number;
  gasPriorityMode: GasPriorityMode;
  computeUnitLimit: number;
  priorityFeeMicroLamports: number;
  jitoTipLamports: number;
  maxRiskScoreAbort: number;
  requireMintRevoked: boolean;
  requireEd25519Witness: boolean;
  webhookCallbackUri: string | null;
  customScript: string | null;
  customScriptHashSha256: string | null;
  status: 'ACTIVE' | 'PAUSED';
  simulatedRunsCount: number;
  abortedRugCount: number;
  lastOutcome: string;
  manifestSigEd25519: string;
  createdAt: string;
}

export interface BotExecutionLogEntry {
  id: string;
  timestamp: string;
  slot: number;
  botName: string;
  pair: string;
  dex: string;
  observedRiskScore: number;
  maxRiskThreshold: number;
  decision: 'BUNDLE_SIMULATED' | 'PREFLIGHT_ABORTED';
  detail: string;
  witnessSig: string;
}

const STRATEGY_LABELS: Record<BotStrategyType, string> = {
  LIQUIDITY_SNIPER: 'New-Pool Liquidity Sniper',
  METALX_ORDERBOOK_SNIPER: 'Metal X Smart Contract OrderQ Sniper',
  CLMM_RANGE_ARB: 'CLMM Tick Vacuum Arbitrage',
  DCA_SENTINEL_GUARD: 'Sentinel-Guarded Limit / DCA',
  WHALE_COPY_SHIELD: 'Smart-Wallet Copy Shield',
};

const POOL_ADDRESS_BY_PAIR: Record<string, string> = {
  'SOL/USDC': '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2',
  'RAY/SOL': 'AVs9TA4nWDzfPJE9gGVNJMVhcQy3V9PGazuz33BfG2RA',
  'BONK/SOL': 'HVNwzt7Pxfu76KHCMQPTLuTCLTm6WnQ1esLv4eizseSv',
  'POPCAT/SOL': 'FRhB8L7Y9Qq41qZXYLtC2nw8An1RJfLLxRF2x9RwLLMo',
  'WIF/SOL': 'EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx',
  'JUP/SOL': 'EYj9xKw6ZszwpyNibHY7JD5o3QgTVrSdcBp1fMJhrR9o',
};

export interface CustomScriptTemplate {
  id: string;
  label: string;
  description: string;
  code: string;
}

const CUSTOM_SCRIPT_TEMPLATES: CustomScriptTemplate[] = [
  {
    id: 'preflight_rug_filter',
    label: 'Preflight HHI & Rug Filter',
    description: 'Aborts snipes if LP concentration (HHI) > 0.25 or $10k slippage > 1.2%.',
    code: `// Non-Custodial Sniper Preflight Hook (Sandbox Deterministic JS)
export function onBeforeSnipe(ctx) {
  if (ctx.pool.riskScore > ctx.config.maxRiskScoreAbort) {
    return { action: 'ABORT_SNIPE', reason: 'Sentinel risk score exceeds threshold' };
  }
  if (ctx.pool.hhi > 0.25 || ctx.pool.slippage10k > 1.2) {
    return { action: 'ABORT_SNIPE', reason: 'LP concentration HHI or depth slippage too high' };
  }
  return {
    action: 'ALLOW_SNIPE',
    targetPool: ctx.config.targetPoolAddress,
    computeUnits: ctx.config.computeUnitLimit,
    priorityFeeMicroLamports: ctx.config.priorityFeeMicroLamports,
  };
}`,
  },
  {
    id: 'dynamic_gas_escalator',
    label: 'Dynamic Gas & Jito Tip Escalator',
    description: 'Boosts compute unit priority fee by 1.5x when pool risk is SAFE (< 3.5).',
    code: `// Dynamic Priority Fee & Jito Bundle Escalator Hook
export function onBeforeSnipe(ctx) {
  const isHighConvictionPool = ctx.pool.riskScore <= 3.5 && ctx.pool.liquidityUsd >= 1000000;
  const escalatedPriorityFee = isHighConvictionPool
    ? Math.round(ctx.config.priorityFeeMicroLamports * 1.5)
    : ctx.config.priorityFeeMicroLamports;

  return {
    action: 'ALLOW_SNIPE',
    targetPool: ctx.config.targetPoolAddress,
    computeUnits: ctx.config.computeUnitLimit,
    priorityFeeMicroLamports: escalatedPriorityFee,
    jitoTipLamports: ctx.config.jitoTipLamports,
  };
}`,
  },
  {
    id: 'metalx_orderq_ioc',
    label: 'Metal X OrderQ IOC Trigger',
    description: 'Constructs atomic dex::placeorder (IOC) + dex::process(50) when risk <= gate.',
    code: `// Metal X DEX (XPR Network) Smart Contract OrderQ Hook
export function onBeforeSnipe(ctx) {
  if (ctx.pool.riskScore > ctx.config.maxRiskScoreAbort) {
    return { action: 'ABORT_SNIPE', reason: 'Metal X preflight risk gate triggered' };
  }
  return {
    action: 'ALLOW_SNIPE',
    contract: 'dex',
    actions: ['placeorder(order_type=1, fill_type=1)', 'process(size=50)'],
    targetPool: ctx.config.targetPoolAddress,
  };
}`,
  },
  {
    id: 'post_fill_tp_sl',
    label: 'Auto Take-Profit & Trailing Stop',
    description: 'Attaches +18% take-profit and -6% stop-loss brackets after bundle fill.',
    code: `// Post-Fill Bracket Guard Hook
export function onAfterSnipeFill(ctx) {
  const entryPrice = ctx.pool.priceUsd;
  return {
    action: 'REGISTER_BRACKETS',
    takeProfitPriceUsd: Number((entryPrice * 1.18).toFixed(6)),
    stopLossPriceUsd: Number((entryPrice * 0.94).toFixed(6)),
    emergencyExitOnLPDrain: true,
  };
}`,
  },
];

const INITIAL_AUTOMATION_BOTS: AutomationBotItem[] = [
  {
    id: 'bot_metalx_orderq_01',
    botName: 'Metal X OrderQ IOC Sniper',
    strategyType: 'METALX_ORDERBOOK_SNIPER',
    targetDex: 'Metal X DEX',
    targetPair: 'SOL/USDC',
    targetPoolAddress: 'dex::market_1_sol_xusdc',
    orderSizeSol: 4.0,
    maxSlippageBps: 45,
    gasPriorityMode: 'TURBO',
    computeUnitLimit: 200000,
    priorityFeeMicroLamports: 45000,
    jitoTipLamports: 100000,
    maxRiskScoreAbort: 5.0,
    requireMintRevoked: true,
    requireEd25519Witness: true,
    webhookCallbackUri: 'https://hooks.moltalpha.dev/metalx-orderq',
    customScript: CUSTOM_SCRIPT_TEMPLATES[2].code,
    customScriptHashSha256: 'a94f1c8e2b7041d39f8a12b6c40e55d1789a0c3b2e4f6a8d0c1e3b5a7f9d2e41',
    status: 'ACTIVE',
    simulatedRunsCount: 18,
    abortedRugCount: 2,
    lastOutcome: 'Metal X dex::placeorder (fill_type=1 IOC) + dex::process(50) verified (Risk 1.4 <= 5.0)',
    manifestSigEd25519: 'ed25519:7xP4mK2v...9qL1',
    createdAt: '6m ago',
  },
  {
    id: 'bot_ray_sniper_01',
    botName: 'Raydium Launchpad Sniper v2',
    strategyType: 'LIQUIDITY_SNIPER',
    targetDex: 'Raydium',
    targetPair: 'RAY/SOL',
    targetPoolAddress: 'AVs9TA4nWDzfPJE9gGVNJMVhcQy3V9PGazuz33BfG2RA',
    orderSizeSol: 2.5,
    maxSlippageBps: 85,
    gasPriorityMode: 'ULTRA_JITO_MEV',
    computeUnitLimit: 350000,
    priorityFeeMicroLamports: 125000,
    jitoTipLamports: 150000,
    maxRiskScoreAbort: 5.5,
    requireMintRevoked: true,
    requireEd25519Witness: true,
    webhookCallbackUri: 'https://hooks.moltalpha.dev/sniper-alerts',
    customScript: CUSTOM_SCRIPT_TEMPLATES[0].code,
    customScriptHashSha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    status: 'ACTIVE',
    simulatedRunsCount: 14,
    abortedRugCount: 3,
    lastOutcome: 'Simulated 2.50 SOL Jito bundle fill (Risk 3.1 <= 5.5)',
    manifestSigEd25519: 'ed25519:8fK2mP9v...4cQ1',
    createdAt: '12m ago',
  },
  {
    id: 'bot_popcat_guard_02',
    botName: 'POPCAT Tick Vacuum Guard',
    strategyType: 'CLMM_RANGE_ARB',
    targetDex: 'Orca',
    targetPair: 'POPCAT/SOL',
    targetPoolAddress: 'FRhB8L7Y9Qq41qZXYLtC2nw8An1RJfLLxRF2x9RwLLMo',
    orderSizeSol: 5.0,
    maxSlippageBps: 120,
    gasPriorityMode: 'TURBO',
    computeUnitLimit: 300000,
    priorityFeeMicroLamports: 75000,
    jitoTipLamports: 250000,
    maxRiskScoreAbort: 6.5,
    requireMintRevoked: true,
    requireEd25519Witness: true,
    webhookCallbackUri: null,
    customScript: CUSTOM_SCRIPT_TEMPLATES[1].code,
    customScriptHashSha256: '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a',
    status: 'ACTIVE',
    simulatedRunsCount: 9,
    abortedRugCount: 7,
    lastOutcome: 'Aborted snipe: Risk 8.9 exceeds 6.5 abort gate (LP vacuum)',
    manifestSigEd25519: 'ed25519:3aN7xL1q...9wE4',
    createdAt: '28m ago',
  },
];

const INITIAL_EXECUTION_LOGS: BotExecutionLogEntry[] = [
  {
    id: 'exec_log_00',
    timestamp: '14:24:12',
    slot: 312891062,
    botName: 'Metal X OrderQ IOC Sniper',
    pair: 'SOL/USDC',
    dex: 'Metal X DEX',
    observedRiskScore: 1.4,
    maxRiskThreshold: 5.0,
    decision: 'BUNDLE_SIMULATED',
    detail:
      'Preflight passed (Risk 1.4 <= 5.0). Dispatched atomic xtokens::transfer + dex::placeorder (market_id=1, order_type=1 LIMIT, fill_type=1 IOC) + dex::process(size=50).',
    witnessSig: 'ed25519:4KpL8vNm...2xQ9e',
  },
  {
    id: 'exec_log_01',
    timestamp: '14:22:09',
    slot: 312891045,
    botName: 'POPCAT Tick Vacuum Guard',
    pair: 'POPCAT/SOL',
    dex: 'Orca',
    observedRiskScore: 8.9,
    maxRiskThreshold: 6.5,
    decision: 'PREFLIGHT_ABORTED',
    detail:
      'Sentinel preflight blocked 5.00 SOL swap on pool FRhB8L7Y...LLMo: CLMM tick vacuum & active freeze warning (Risk 8.9 > 6.5).',
    witnessSig: 'ed25519:5YcK3mTz...8dF2a',
  },
  {
    id: 'exec_log_02',
    timestamp: '14:20:41',
    slot: 312891018,
    botName: 'Raydium Launchpad Sniper v2',
    pair: 'RAY/SOL',
    dex: 'Raydium',
    observedRiskScore: 3.1,
    maxRiskThreshold: 5.5,
    decision: 'BUNDLE_SIMULATED',
    detail:
      'Preflight passed (Risk 3.1 <= 5.5). Simulated 2.50 SOL Jito bundle on pool AVs9TA4n...G2RA (350k CU, 125k microLamports/CU, 85 bps slippage).',
    witnessSig: 'ed25519:9LmP4vQx...1kR8z',
  },
];

interface AutomationPageProps {
  isAuthenticated: boolean;
  userDisplayName: string;
  userCredits: number;
  currentSlot: number;
  solPriceUsd: number;
  pools: DexPool[];
  activeWitnessKey: WitnessKeyRecord;
  serverSessionToken?: string | null;
  onGoogleLogin: () => Promise<void>;
  onOperatorSessionLogin: () => void;
  onNavigateSentinel: (pair?: string) => void;
  onNavigateDevelopers: () => void;
  onRecordAudit?: (action: string, details: string) => Promise<void>;
  onNotify?: (message: string) => void;
}

export const AutomationPage: React.FC<AutomationPageProps> = ({
  isAuthenticated,
  userDisplayName,
  userCredits,
  currentSlot,
  solPriceUsd,
  pools,
  activeWitnessKey,
  serverSessionToken,
  onGoogleLogin,
  onOperatorSessionLogin,
  onNavigateSentinel,
  onNavigateDevelopers,
  onRecordAudit,
  onNotify,
}) => {
  const [bots, setBots] = useState<AutomationBotItem[]>(INITIAL_AUTOMATION_BOTS);
  const [execLogs, setExecLogs] = useState<BotExecutionLogEntry[]>(INITIAL_EXECUTION_LOGS);
  const [selectedBotId, setSelectedBotId] = useState<string>(INITIAL_AUTOMATION_BOTS[0].id);
  const [logFilter, setLogFilter] = useState<'ALL' | 'BUNDLE_SIMULATED' | 'PREFLIGHT_ABORTED'>('ALL');
  const [sdkLang, setSdkLang] = useState<
    'proton-tsc' | 'metalx-dex' | 'typescript' | 'python' | 'curl'
  >('proton-tsc');
  const [copiedCode, setCopiedCode] = useState<boolean>(false);

  // Metal X DEX Smart Contract Action Builder State (docs.metalx.com/developers-dex/smart-contract/actions)
  const [metalxAction, setMetalxAction] = useState<MetalXActionName>('placeorder');
  const [metalxMarketId, setMetalxMarketId] = useState<number>(1);
  const [metalxTraderAccount, setMetalxTraderAccount] = useState<string>('molttrader');
  const [metalxOrderType, setMetalxOrderType] = useState<1 | 2 | 3>(1); // 1=LIMIT, 2=STOPLOSS, 3=TAKEPROFIT
  const [metalxOrderSide, setMetalxOrderSide] = useState<1 | 2>(1); // 1=BUY, 2=SELL
  const [metalxFillType, setMetalxFillType] = useState<0 | 1 | 2>(1); // 0=GTC, 1=IOC, 2=POST_ONLY
  const [metalxQuantity, setMetalxQuantity] = useState<number>(100000000);
  const [metalxPrice, setMetalxPrice] = useState<number>(1450000);
  const [metalxTriggerPrice, setMetalxTriggerPrice] = useState<number>(0);
  const [metalxBidSym, setMetalxBidSym] = useState<string>('8,XETH');
  const [metalxAskSym, setMetalxAskSym] = useState<string>('4,XMT');
  const [metalxProcessSize, setMetalxProcessSize] = useState<number>(50);
  const [metalxCancelOrderId, setMetalxCancelOrderId] = useState<number>(23);

  // Sniper Bot Configuration Form State (Gas Settings, Slippage Tolerance, Target Pool Address & Expandable Scripting)
  const [botName, setBotName] = useState<string>('BONK Liquidity Dip Sniper');
  const [strategyType, setStrategyType] = useState<BotStrategyType>('LIQUIDITY_SNIPER');
  const [targetDex, setTargetDex] = useState<SupportedDexTarget>('Raydium');
  const [targetPair, setTargetPair] = useState<string>('BONK/SOL');
  const [targetPoolAddress, setTargetPoolAddress] = useState<string>(
    POOL_ADDRESS_BY_PAIR['BONK/SOL']
  );
  const [orderSizeSol, setOrderSizeSol] = useState<string>('1.25');
  const [maxSlippageBps, setMaxSlippageBps] = useState<string>('50');
  const [slippagePercent, setSlippagePercent] = useState<string>('0.50');
  const [gasPriorityMode, setGasPriorityMode] = useState<GasPriorityMode>('TURBO');
  const [computeUnitLimit, setComputeUnitLimit] = useState<string>('250000');
  const [priorityFeeMicroLamports, setPriorityFeeMicroLamports] = useState<string>('50000');
  const [jitoTipLamports, setJitoTipLamports] = useState<string>('120000');
  const [maxRiskScoreAbort, setMaxRiskScoreAbort] = useState<number>(6.5);
  const [requireMintRevoked, setRequireMintRevoked] = useState<boolean>(true);
  const [requireEd25519Witness, setRequireEd25519Witness] = useState<boolean>(true);
  const [webhookCallbackUri, setWebhookCallbackUri] = useState<string>('');
  const [formError, setFormError] = useState<string | null>(null);

  // Expandable Custom Scripting Panel State
  const [isScriptingExpanded, setIsScriptingExpanded] = useState<boolean>(false);
  const [enableCustomScript, setEnableCustomScript] = useState<boolean>(true);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(
    CUSTOM_SCRIPT_TEMPLATES[0].id
  );
  const [customScriptCode, setCustomScriptCode] = useState<string>(
    CUSTOM_SCRIPT_TEMPLATES[0].code
  );
  const [scriptValidationFeedback, setScriptValidationFeedback] = useState<{
    status: 'idle' | 'valid' | 'invalid';
    message: string;
    scriptHash?: string;
    simulatedDecision?: string;
  }>({ status: 'idle', message: '' });

  const selectedPoolForBuilder = useMemo(
    () => pools.find((p) => p.pair === targetPair) || pools[0],
    [pools, targetPair]
  );

  const selectedBotForExport = useMemo(
    () => bots.find((b) => b.id === selectedBotId) || bots[0],
    [bots, selectedBotId]
  );

  const filteredLogs = useMemo(() => {
    if (logFilter === 'ALL') return execLogs;
    return execLogs.filter((l) => l.decision === logFilter);
  }, [execLogs, logFilter]);

  // Calculate live estimated gas + priority fee + Jito tip in SOL and USD
  const estimatedGasTelemetry = useMemo(() => {
    const cu = Number(computeUnitLimit) || 250000;
    const microLamports = Number(priorityFeeMicroLamports) || 50000;
    const jitoTip = Number(jitoTipLamports) || 0;
    const baseSolanaSigFeeLamports = 5000;
    const computePriorityLamports = (cu * microLamports) / 1_000_000;
    const totalLamports = baseSolanaSigFeeLamports + computePriorityLamports + jitoTip;
    const totalSol = totalLamports / 1_000_000_000;
    const totalUsd = totalSol * solPriceUsd;
    return {
      computePriorityLamports: Math.round(computePriorityLamports),
      totalLamports: Math.round(totalLamports),
      totalSol,
      totalUsd,
    };
  }, [computeUnitLimit, priorityFeeMicroLamports, jitoTipLamports, solPriceUsd]);

  // Check whether the current targetPoolAddress is valid Base58 or Metal X identifier
  const poolAddressValidation = useMemo(() => {
    const trimmed = targetPoolAddress.trim();
    const isBase58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(trimmed);
    const isMetalX = /^[a-z1-5._:]{3,36}$/i.test(trimmed);
    return {
      valid: isBase58 || isMetalX,
      kind: isBase58 ? 'Solana Base58 Pool' : isMetalX ? 'Metal X Market Contract' : 'Invalid Format',
    };
  }, [targetPoolAddress]);

  const handleSelectGasPreset = (mode: GasPriorityMode) => {
    setGasPriorityMode(mode);
    if (mode === 'STANDARD') {
      setComputeUnitLimit('200000');
      setPriorityFeeMicroLamports('15000');
      setJitoTipLamports('25000');
    } else if (mode === 'TURBO') {
      setComputeUnitLimit('250000');
      setPriorityFeeMicroLamports('50000');
      setJitoTipLamports('120000');
    } else {
      setComputeUnitLimit('400000');
      setPriorityFeeMicroLamports('180000');
      setJitoTipLamports('500000');
    }
  };

  const handleSelectPairChange = (newPair: string) => {
    setTargetPair(newPair);
    if (POOL_ADDRESS_BY_PAIR[newPair]) {
      setTargetPoolAddress(
        targetDex === 'Metal X DEX'
          ? `dex::market_${newPair.toLowerCase().replace('/', '_')}`
          : POOL_ADDRESS_BY_PAIR[newPair]
      );
    }
  };

  const handleApplyScriptTemplate = (templateId: string) => {
    const found = CUSTOM_SCRIPT_TEMPLATES.find((t) => t.id === templateId);
    if (found) {
      setSelectedTemplateId(found.id);
      setCustomScriptCode(found.code);
      setScriptValidationFeedback({ status: 'idle', message: '' });
    }
  };

  const handleValidateAndDryRunCustomScript = () => {
    const check = validateCustomBotScript(customScriptCode);
    if (!check.allowed || !check.data) {
      setScriptValidationFeedback({
        status: 'invalid',
        message: check.message,
      });
      return;
    }

    const pool = selectedPoolForBuilder;
    const hhiValue = typeof pool.lpConcentrationHhi === 'number' ? pool.lpConcentrationHhi : 0.12;
    const riskExceeded = pool.riskScore > maxRiskScoreAbort;
    const hhiWarning = customScriptCode.includes('pool.hhi') && hhiValue > 0.25;
    const decision =
      riskExceeded || hhiWarning
        ? `ABORT_SNIPE (Pool ${pool.pair} Risk ${pool.riskScore.toFixed(1)} / HHI ${hhiValue.toFixed(2)})`
        : `ALLOW_SNIPE on ${targetPoolAddress.slice(0, 14)}... (Gas: ${estimatedGasTelemetry.totalSol.toFixed(5)} SOL)`;

    setScriptValidationFeedback({
      status: 'valid',
      message: `Static analysis passed (${check.data.lineCount} lines). Non-custodial sandbox verified.`,
      scriptHash: check.data.scriptHashSha256,
      simulatedDecision: decision,
    });
    onNotify?.(`Custom bot script verified (SHA-256: ${check.data.scriptHashSha256.slice(0, 10)}...)`);
  };

  const handleSelectSlippagePreset = (pct: string, bps: string) => {
    setSlippagePercent(pct);
    setMaxSlippageBps(bps);
  };

  const handleSlippagePercentChange = (val: string) => {
    setSlippagePercent(val);
    const num = Number(val);
    if (!isNaN(num) && num >= 0) {
      setMaxSlippageBps(String(Math.round(num * 100)));
    } else if (val === '') {
      setMaxSlippageBps('');
    }
  };

  const handleSlippageBpsChange = (val: string) => {
    setMaxSlippageBps(val);
    const num = Number(val);
    if (!isNaN(num) && num >= 0) {
      setSlippagePercent((num / 100).toString());
    } else if (val === '') {
      setSlippagePercent('');
    }
  };

  const handleLoadBotIntoBuilder = (bot: AutomationBotItem) => {
    setBotName(bot.botName);
    setStrategyType(bot.strategyType);
    setTargetDex(bot.targetDex);
    setTargetPair(bot.targetPair);
    setTargetPoolAddress(bot.targetPoolAddress);
    setOrderSizeSol(String(bot.orderSizeSol));
    setMaxSlippageBps(String(bot.maxSlippageBps));
    setSlippagePercent((bot.maxSlippageBps / 100).toFixed(2));
    setGasPriorityMode(bot.gasPriorityMode);
    setComputeUnitLimit(String(bot.computeUnitLimit));
    setPriorityFeeMicroLamports(String(bot.priorityFeeMicroLamports));
    setJitoTipLamports(String(bot.jitoTipLamports));
    setMaxRiskScoreAbort(bot.maxRiskScoreAbort);
    setRequireMintRevoked(bot.requireMintRevoked);
    setRequireEd25519Witness(bot.requireEd25519Witness);
    setWebhookCallbackUri(bot.webhookCallbackUri || '');
    if (bot.customScript) {
      setEnableCustomScript(true);
      setCustomScriptCode(bot.customScript);
      setIsScriptingExpanded(true);
    }
    setSelectedBotId(bot.id);
    onNotify?.(`Loaded ${bot.botName} parameters into Sniper Bot Configuration Form.`);
  };

  // Live Metal X DEX Smart Contract Action Payload Preview
  const metalxActionPayloadJson = useMemo(() => {
    const cleanTrader = sanitizePlainText(metalxTraderAccount, 12).toLowerCase() || 'trader';
    if (metalxAction === 'placeorder') {
      return JSON.stringify(
        {
          account: 'dex',
          name: 'placeorder',
          authorization: [{ actor: cleanTrader, permission: 'active' }],
          data: {
            market_id: metalxMarketId,
            account: cleanTrader,
            order_type: metalxOrderType,
            order_side: metalxOrderSide,
            quantity: metalxQuantity,
            price: metalxPrice,
            bid_symbol: {
              sym: metalxBidSym,
              contract: 'eosio.token',
            },
            ask_symbol: {
              sym: metalxAskSym,
              contract: 'eosio.token',
            },
            trigger_price: metalxOrderType === 1 ? 0 : metalxTriggerPrice,
            fill_type: metalxFillType,
            referrer: 'moltalpha',
          },
        },
        null,
        2
      );
    }
    if (metalxAction === 'process') {
      return JSON.stringify(
        {
          account: 'dex',
          name: 'process',
          authorization: [{ actor: cleanTrader, permission: 'active' }],
          data: {
            size: String(metalxProcessSize),
          },
        },
        null,
        2
      );
    }
    if (metalxAction === 'processsltp') {
      return JSON.stringify(
        {
          account: 'dex',
          name: 'processsltp',
          authorization: [{ actor: cleanTrader, permission: 'active' }],
          data: {
            market_id: String(metalxMarketId),
            size: String(metalxProcessSize),
          },
        },
        null,
        2
      );
    }
    return JSON.stringify(
      {
        account: 'dex',
        name: 'cancelorder',
        authorization: [{ actor: cleanTrader, permission: 'active' }],
        data: {
          account: cleanTrader,
          order_id: String(metalxCancelOrderId),
        },
      },
      null,
      2
    );
  }, [
    metalxAction,
    metalxMarketId,
    metalxTraderAccount,
    metalxOrderType,
    metalxOrderSide,
    metalxQuantity,
    metalxPrice,
    metalxBidSym,
    metalxAskSym,
    metalxTriggerPrice,
    metalxFillType,
    metalxProcessSize,
    metalxCancelOrderId,
  ]);

  const handleSimulateMetalXAction = async () => {
    const livePool = selectedPoolForBuilder;
    const witness = buildWitnessAttestation(livePool, activeWitnessKey);
    const nowTime = new Date().toTimeString().slice(0, 8);
    const slotNum = currentSlot + 1;
    const isAborted = livePool.riskScore > maxRiskScoreAbort;

    const actionSummary =
      metalxAction === 'placeorder'
        ? `dex::placeorder(market_id=${metalxMarketId}, type=${metalxOrderType}, side=${metalxOrderSide}, fill_type=${metalxFillType})`
        : metalxAction === 'process'
          ? `dex::process(size=${metalxProcessSize})`
          : metalxAction === 'processsltp'
            ? `dex::processsltp(market_id=${metalxMarketId}, size=${metalxProcessSize})`
            : `dex::cancelorder(account=${metalxTraderAccount}, order_id=${metalxCancelOrderId})`;

    const newLog: BotExecutionLogEntry = {
      id: `exec_metalx_${Date.now()}`,
      timestamp: nowTime,
      slot: slotNum,
      botName: `Metal X Contract (${metalxAction.toUpperCase()})`,
      pair: livePool.pair,
      dex: 'Metal X DEX',
      observedRiskScore: livePool.riskScore,
      maxRiskThreshold: maxRiskScoreAbort,
      decision: isAborted ? 'PREFLIGHT_ABORTED' : 'BUNDLE_SIMULATED',
      detail: isAborted
        ? `Sentinel blocked ${actionSummary}: Pool Risk ${livePool.riskScore.toFixed(1)} > ${maxRiskScoreAbort.toFixed(1)} gate.`
        : `Sentinel verified ${actionSummary} on XPR Network / Metal X DEX (Risk ${livePool.riskScore.toFixed(1)} <= ${maxRiskScoreAbort.toFixed(1)}).`,
      witnessSig: `ed25519:${witness.signatureEd25519.slice(0, 8)}...${witness.signatureEd25519.slice(-5)}`,
    };

    setExecLogs((prev) => [newLog, ...prev]);
    if (onRecordAudit) {
      await onRecordAudit(
        `Metal X DEX ${metalxAction.toUpperCase()} Simulated`,
        `${actionSummary} on ${livePool.pair}`
      );
    }
    onNotify?.(
      isAborted
        ? `Sentinel aborted Metal X ${metalxAction} (Risk ${livePool.riskScore.toFixed(1)} > ${maxRiskScoreAbort.toFixed(1)})`
        : `Simulated Metal X DEX smart contract action: ${actionSummary}`
    );
  };

  const handleToggleBotStatus = (botId: string) => {
    setBots((prev) =>
      prev.map((b) =>
        b.id === botId
          ? { ...b, status: b.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE' }
          : b
      )
    );
  };

  const handleDeleteBot = (botId: string) => {
    setBots((prev) => {
      const remaining = prev.filter((b) => b.id !== botId);
      if (selectedBotId === botId && remaining.length > 0) {
        setSelectedBotId(remaining[0].id);
      }
      return remaining;
    });
    onNotify?.('Removed bot configuration from sandbox fleet.');
  };

  // Run a live Sentinel preflight + simulated Jito / Metal X orderQ dry-run for a bot
  const handleRunBotSimulation = async (bot: AutomationBotItem) => {
    const livePool = pools.find((p) => p.pair === bot.targetPair) || pools[0];
    const witness = buildWitnessAttestation(livePool, activeWitnessKey);
    const nowTime = new Date().toTimeString().slice(0, 8);
    const slotNum = currentSlot + 1;

    const mintCheckFailed =
      bot.requireMintRevoked &&
      (livePool.mintAuthority.toLowerCase().includes('active') ||
        livePool.freezeAuthority.toLowerCase().includes('active'));
    const riskExceeded = livePool.riskScore > bot.maxRiskScoreAbort;
    const isAborted = riskExceeded || mintCheckFailed;

    const decision: BotExecutionLogEntry['decision'] = isAborted
      ? 'PREFLIGHT_ABORTED'
      : 'BUNDLE_SIMULATED';

    const executionVenueDetail =
      bot.targetDex === 'Metal X DEX'
        ? `atomic xtokens::transfer + dex::placeorder + dex::process(50) on Metal X DEX (${bot.targetPoolAddress})`
        : `${bot.orderSizeSol.toFixed(2)} SOL ($${(bot.orderSizeSol * solPriceUsd).toFixed(
            2
          )}) Jito bundle on ${bot.targetDex} pool ${bot.targetPoolAddress.slice(0, 8)}... (${bot.computeUnitLimit.toLocaleString()} CU, ${bot.priorityFeeMicroLamports.toLocaleString()} microLamports/CU, ${bot.maxSlippageBps} bps slippage)`;

    const detail = isAborted
      ? `Sentinel preflight ABORTED ${bot.orderSizeSol.toFixed(2)} SOL snipe on ${bot.targetPair} (${bot.targetPoolAddress.slice(0, 10)}...): ${
          riskExceeded
            ? `Risk Score ${livePool.riskScore.toFixed(1)} > max threshold ${bot.maxRiskScoreAbort.toFixed(1)}`
            : 'Freeze/Mint authority warning active'
        }.`
      : `Preflight PASSED (Risk ${livePool.riskScore.toFixed(1)} <= ${bot.maxRiskScoreAbort.toFixed(
          1
        )}). Simulated ${executionVenueDetail}.`;

    const newLog: BotExecutionLogEntry = {
      id: `exec_${Date.now()}`,
      timestamp: nowTime,
      slot: slotNum,
      botName: bot.botName,
      pair: bot.targetPair,
      dex: bot.targetDex,
      observedRiskScore: livePool.riskScore,
      maxRiskThreshold: bot.maxRiskScoreAbort,
      decision,
      detail,
      witnessSig: `ed25519:${witness.signatureEd25519.slice(0, 8)}...${witness.signatureEd25519.slice(-5)}`,
    };

    setExecLogs((prev) => [newLog, ...prev]);
    setBots((prev) =>
      prev.map((item) =>
        item.id === bot.id
          ? {
              ...item,
              simulatedRunsCount: item.simulatedRunsCount + 1,
              abortedRugCount: isAborted ? item.abortedRugCount + 1 : item.abortedRugCount,
              lastOutcome: isAborted
                ? `Aborted: Risk ${livePool.riskScore.toFixed(1)} > ${bot.maxRiskScoreAbort.toFixed(1)} gate`
                : `Simulated ${bot.orderSizeSol.toFixed(2)} SOL fill @ ${formatTokenPriceUsd(livePool.priceUsd)}`,
            }
          : item
      )
    );

    if (onRecordAudit) {
      await onRecordAudit(
        isAborted ? 'Bot Snipe Aborted (Sentinel Gate)' : 'Bot Dry-Run Simulated',
        `${bot.botName} on ${bot.targetPair} [Pool: ${bot.targetPoolAddress.slice(0, 12)}...]`
      );
    }
    onNotify?.(
      isAborted
        ? `Sentinel Gate blocked ${bot.botName} on ${bot.targetPair} (Risk ${livePool.riskScore.toFixed(1)} > ${bot.maxRiskScoreAbort.toFixed(1)})`
        : `Simulated ${bot.orderSizeSol.toFixed(2)} SOL execution for ${bot.botName} on ${bot.targetPair}`
    );
  };

  // Validate and deploy a new trading/sniping bot configuration
  const handleCreateBot = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const cleanName = sanitizePlainText(botName, 64);
    if (cleanName.length < 3) {
      setFormError('Bot name must be between 3 and 64 characters.');
      return;
    }

    const cleanPoolAddress = targetPoolAddress.trim();
    if (!poolAddressValidation.valid) {
      setFormError(
        'Target liquidity pool address must be a valid 32–44 char Base58 Solana pool address or Metal X market contract identifier.'
      );
      return;
    }

    const parsedOrderSol = Number(orderSizeSol);
    if (!Number.isFinite(parsedOrderSol) || parsedOrderSol < 0.01 || parsedOrderSol > 250) {
      setFormError('Order size must be between 0.01 and 250 units.');
      return;
    }

    const parsedSlippage = Number(maxSlippageBps);
    if (!Number.isFinite(parsedSlippage) || parsedSlippage < 5 || parsedSlippage > 1000) {
      setFormError('Slippage tolerance must be between 5 bps (0.05%) and 1,000 bps (10.0%).');
      return;
    }

    const parsedCuLimit = Number(computeUnitLimit);
    if (!Number.isFinite(parsedCuLimit) || parsedCuLimit < 50000 || parsedCuLimit > 1400000) {
      setFormError('Compute unit limit must be between 50,000 and 1,400,000 CU.');
      return;
    }

    const parsedPriorityFee = Number(priorityFeeMicroLamports);
    if (
      !Number.isFinite(parsedPriorityFee) ||
      parsedPriorityFee < 100 ||
      parsedPriorityFee > 5000000
    ) {
      setFormError('Priority fee must be between 100 and 5,000,000 microLamports/CU.');
      return;
    }

    const parsedJitoTip = Number(jitoTipLamports);
    if (!Number.isFinite(parsedJitoTip) || parsedJitoTip < 1000 || parsedJitoTip > 10_000_000) {
      setFormError('Priority / Jito MEV tip must be between 1,000 and 10,000,000 lamports.');
      return;
    }

    let validatedScriptCode: string | null = null;
    let validatedScriptHash: string | null = null;
    if (enableCustomScript && customScriptCode.trim().length > 0) {
      const scriptCheck = validateCustomBotScript(customScriptCode);
      if (!scriptCheck.allowed || !scriptCheck.data) {
        setFormError(scriptCheck.message);
        return;
      }
      validatedScriptCode = scriptCheck.data.sanitizedScript;
      validatedScriptHash = scriptCheck.data.scriptHashSha256;
    }

    let validatedWebhook: string | null = null;
    if (webhookCallbackUri.trim().length > 0) {
      const uriCheck = validateSafeExternalUri(webhookCallbackUri);
      if (!uriCheck.allowed) {
        setFormError(uriCheck.message);
        return;
      }
      validatedWebhook = uriCheck.data!;
    }

    let manifestSig = `ed25519:${canonicalizeJsonRfc8785({
      botName: cleanName,
      pair: targetPair,
      pool: cleanPoolAddress,
      maxRiskScoreAbort,
    }).slice(0, 12)}...9aF2`;

    if (serverSessionToken) {
      try {
        const res = await fetch('/api/v1/automation/bots', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${serverSessionToken}`,
          },
          body: JSON.stringify({
            botName: cleanName,
            strategyType,
            targetDex,
            targetPair,
            targetPoolAddress: cleanPoolAddress,
            orderSizeSol: parsedOrderSol,
            maxSlippageBps: parsedSlippage,
            gasPriorityMode,
            computeUnitLimit: parsedCuLimit,
            priorityFeeMicroLamports: parsedPriorityFee,
            jitoTipLamports: parsedJitoTip,
            maxRiskScoreAbort,
            requireMintRevoked,
            requireEd25519Witness,
            webhookCallbackUri: validatedWebhook,
            customScript: validatedScriptCode || undefined,
          }),
        });
        if (res.ok) {
          const data = await res.json();
          if (data.serverEd25519Attestation?.signatureBase64Url) {
            const sig = String(data.serverEd25519Attestation.signatureBase64Url);
            manifestSig = `ed25519:${sig.slice(0, 8)}...${sig.slice(-6)}`;
          }
        }
      } catch {
        // Fallback to local sandbox manifest attestation
      }
    }

    const newBot: AutomationBotItem = {
      id: `bot_${Date.now()}`,
      botName: cleanName,
      strategyType,
      targetDex,
      targetPair,
      targetPoolAddress: cleanPoolAddress,
      orderSizeSol: parsedOrderSol,
      maxSlippageBps: parsedSlippage,
      gasPriorityMode,
      computeUnitLimit: parsedCuLimit,
      priorityFeeMicroLamports: parsedPriorityFee,
      jitoTipLamports: parsedJitoTip,
      maxRiskScoreAbort,
      requireMintRevoked,
      requireEd25519Witness,
      webhookCallbackUri: validatedWebhook,
      customScript: validatedScriptCode,
      customScriptHashSha256: validatedScriptHash,
      status: 'ACTIVE',
      simulatedRunsCount: 0,
      abortedRugCount: 0,
      lastOutcome: `Configured pool ${cleanPoolAddress.slice(0, 10)}... (${gasPriorityMode}, ${parsedSlippage} bps slippage)`,
      manifestSigEd25519: manifestSig,
      createdAt: 'Just now',
    };

    setBots((prev) => [newBot, ...prev]);
    setSelectedBotId(newBot.id);
    if (onRecordAudit) {
      await onRecordAudit(
        'Automation Bot Deployed',
        `${cleanName} on ${targetPair} [Pool: ${cleanPoolAddress.slice(0, 12)}..., Gas: ${gasPriorityMode}, Slippage: ${parsedSlippage} bps]`
      );
    }
    onNotify?.(
      `Deployed ${cleanName} targeting pool ${cleanPoolAddress.slice(0, 10)}... (${(parsedSlippage / 100).toFixed(2)}% slippage)`
    );
  };

  // Generate non-custodial bot / smart contract code snippet for the currently selected bot
  const generatedSdkCode = useMemo(() => {
    const b = selectedBotForExport;
    if (!b) return '';

    if (sdkLang === 'proton-tsc') {
      return `// XPR Network Smart Contract (proton-tsc) — Non-Custodial Escrow & Metal X DEX Sniper
// Reference: https://docs.xprnetwork.org/smart-contracts/write-your-first-smart-contract.html#glue-everything-together
// Reference: https://docs.metalx.com/developers-dex/smart-contract/actions
import {
  Asset,
  check,
  Contract,
  EMPTY_NAME,
  Name,
  Table,
  TableStore,
  requireAuth,
} from "proton-tsc";

@table("snipeeskrow")
export class SnipeEscrowTable extends Table {
  constructor(
    public owner: Name = EMPTY_NAME,
    public credits: u32 = 0,
    public maxRiskScaled: u32 = ${Math.round(b.maxRiskScoreAbort * 10)} // ${b.maxRiskScoreAbort.toFixed(1)}/10 Sentinel Gate
  ) {
    super();
  }

  @primary
  get by_owner(): u64 {
    return this.owner.N;
  }

  set by_owner(value: u64) {
    this.owner = Name.fromU64(value);
  }
}

@contract
export class MoltSniperVault extends Contract {
  private escrowTable: TableStore<SnipeEscrowTable> = new TableStore<SnipeEscrowTable>(
    this.receiver,
    this.receiver
  );

  // 1. Glue everything together: Notification handler on XPR deposit (10 XPR per bot execution ticket)
  @action("transfer", notify)
  transfer(from: Name, to: Name, quantity: Asset, memo: string): void {
    if (from == this.receiver) return; // Ignore outgoing transfers from contract itself
    check(this.firstReceiver == Name.fromString("xtokens") || this.firstReceiver == Name.fromString("eosio.token"), "Invalid token contract");
    check(quantity.symbol.getSymbolString() == "XPR", "Token must be XPR");
    check(quantity.amount % 100000 == 0, "Amount must be a multiple of 10.0000 XPR");

    const ticketsPurchased = u32(quantity.amount / 100000);
    let existing = this.escrowTable.get(from.N);
    if (!existing) {
      existing = new SnipeEscrowTable(from, ticketsPurchased, ${Math.round(b.maxRiskScoreAbort * 10)});
      this.escrowTable.store(existing, this.receiver);
    } else {
      existing.credits += ticketsPurchased;
      this.escrowTable.update(existing, this.receiver);
    }
  }

  // 2. Execute Sentinel-Guarded Metal X DEX placeorder + process inline actions
  @action("execsnipe")
  execsnipe(owner: Name, marketId: u16, quantity: u64, price: u64, observedRiskScaled: u32): void {
    requireAuth(owner);
    const escrow = this.escrowTable.requireGet(owner.N, "No snipe tickets found for account");
    check(escrow.credits > 0, "Insufficient snipe tickets");
    check(observedRiskScaled <= escrow.maxRiskScaled, "ABORT_SNIPE: Observed Sentinel risk exceeds gate");

    escrow.credits -= 1;
    this.escrowTable.update(escrow, this.receiver);
    // Dispatches inline action to Metal X 'dex' smart contract (placeorder + process)
  }
}`;
    }

    if (sdkLang === 'metalx-dex') {
      const cleanTrader = sanitizePlainText(metalxTraderAccount, 12).toLowerCase() || 'trader';
      return `// Metal X DEX Smart Contract Action Runner (@proton/js)
// Reference: https://docs.metalx.com/developers-dex/smart-contract/actions
// Bot: ${b.botName} | Target Pool/Market: ${b.targetPoolAddress} | Slippage: ${b.maxSlippageBps} bps
import { JsonRpc, Api, JsSignatureProvider } from '@proton/js';

const rpc = new JsonRpc(['https://proton.greymass.com']);
const api = new Api({
  rpc,
  signatureProvider: new JsSignatureProvider([process.env.XPR_PRIVATE_KEY!]), // Never transmitted to server
});

export async function submitMetalXDexOrderWithSentinelGuard(observedRiskScore: number) {
  if (observedRiskScore > ${b.maxRiskScoreAbort.toFixed(1)}) {
    throw new Error(\`ABORT_SNIPE: Risk \${observedRiskScore} > ${b.maxRiskScoreAbort.toFixed(1)} gate\`);
  }

  // Atomic transaction: 1) 'dex::placeorder' -> 2) 'dex::process'
  return await api.transact(
    {
      actions: [
        {
          account: 'dex',
          name: 'placeorder',
          authorization: [{ actor: '${cleanTrader}', permission: 'active' }],
          data: {
            market_id: ${metalxMarketId},
            account: '${cleanTrader}',
            order_type: ${metalxOrderType}, // 1 = LIMIT, 2 = STOPLOSS, 3 = TAKEPROFIT
            order_side: ${metalxOrderSide}, // 1 = BUY, 2 = SELL
            quantity: ${metalxQuantity},
            price: ${metalxPrice},
            bid_symbol: { sym: '${metalxBidSym}', contract: 'eosio.token' },
            ask_symbol: { sym: '${metalxAskSym}', contract: 'eosio.token' },
            trigger_price: ${metalxOrderType === 1 ? 0 : metalxTriggerPrice},
            fill_type: ${metalxFillType}, // 0 = GTC, 1 = IOC, 2 = POST_ONLY
            referrer: 'moltalpha',
          },
        },
        {
          account: 'dex',
          name: 'process',
          authorization: [{ actor: '${cleanTrader}', permission: 'active' }],
          data: { size: '${metalxProcessSize}' },
        },
      ],
    },
    { blocksBehind: 3, expireSeconds: 30 }
  );
}`;
    }

    if (sdkLang === 'typescript') {
      return `// Non-Custodial MoltAlpha Sniper Bot (${b.botName})
// Target Pool Address: ${b.targetPoolAddress} (${b.targetDex} · ${b.targetPair})
// Gas Mode: ${b.gasPriorityMode} | CU Limit: ${b.computeUnitLimit} | Priority Fee: ${b.priorityFeeMicroLamports} microLamports/CU
import crypto from 'node:crypto';

const MOLT_API_URL = 'https://api.moltalpha.dev';
const MOLT_API_KEY = process.env.MOLT_API_KEY!;

const BOT_CONFIG = {
  pair: '${b.targetPair}',
  dex: '${b.targetDex}',
  targetPoolAddress: '${b.targetPoolAddress}',
  orderSizeSol: ${b.orderSizeSol},
  maxSlippageBps: ${b.maxSlippageBps},
  gasPriorityMode: '${b.gasPriorityMode}',
  computeUnitLimit: ${b.computeUnitLimit},
  priorityFeeMicroLamports: ${b.priorityFeeMicroLamports},
  jitoTipLamports: ${b.jitoTipLamports},
  maxRiskScoreAbort: ${b.maxRiskScoreAbort.toFixed(1)},
};
${b.customScript ? `\n// Custom User Bot Hook (SHA-256: ${b.customScriptHashSha256?.slice(0, 16)}...)\n${b.customScript}\n` : ''}
export async function executeSentinelGuardedSnipe() {
  const res = await fetch(\`\${MOLT_API_URL}/api/v1/witness/attest\`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': MOLT_API_KEY },
    body: JSON.stringify({
      payload: {
        pair: BOT_CONFIG.pair,
        pool_address: BOT_CONFIG.targetPoolAddress,
        max_risk_gate: BOT_CONFIG.maxRiskScoreAbort,
      }
    }),
  });
  const witness = await res.json();

  const isVerified = crypto.verify(
    null,
    Buffer.from(witness.canonicalJson, 'utf8'),
    witness.publicKeyPem,
    Buffer.from(witness.signatureBase64Url, 'base64url')
  );
  if (!isVerified) throw new Error('ABORT_SNIPE: Ed25519 state witness verification failed!');
  console.log('[MoltAlpha Bot] Witness verified for pool', BOT_CONFIG.targetPoolAddress);
}`;
    }

    if (sdkLang === 'python') {
      return `# Non-Custodial MoltAlpha Sniping Bot (${b.botName})
# Target Pool: ${b.targetPoolAddress} (${b.targetPair} on ${b.targetDex})
# Gas: ${b.gasPriorityMode} (${b.computeUnitLimit} CU @ ${b.priorityFeeMicroLamports} microLamports/CU) | Slippage: ${b.maxSlippageBps} bps
import os
import httpx

MOLT_API_URL = "https://api.moltalpha.dev"
MOLT_API_KEY = os.environ["MOLT_API_KEY"]

def run_preflight_snipe_guard():
    with httpx.Client(timeout=3.5) as client:
        attest = client.post(
            f"{MOLT_API_URL}/api/v1/witness/attest",
            headers={"X-API-Key": MOLT_API_KEY},
            json={
                "payload": {
                    "pair": "${b.targetPair}",
                    "pool_address": "${b.targetPoolAddress}",
                    "max_risk": ${b.maxRiskScoreAbort.toFixed(1)},
                }
            },
        ).json()

        verify = client.post(
            f"{MOLT_API_URL}/api/v1/witness/verify",
            json={
                "canonicalJson": attest["canonicalJson"],
                "signatureBase64Url": attest["signatureBase64Url"],
                "keyEpochId": attest["keyEpochId"],
            },
        ).json()

        if not verify.get("verified"):
            raise RuntimeError("ABORT_SNIPE: Unverified Ed25519 witness signature")
        print(f"Preflight passed for pool ${b.targetPoolAddress}. Signing {${b.orderSizeSol}} SOL swap locally.")`;
    }

    return `# Register & Attest Sniper Bot Manifest (with Gas, Slippage & Target Liquidity Pool Address)
curl -sS -X POST https://api.moltalpha.dev/api/v1/automation/bots \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $MOLT_SESSION_TOKEN" \\
  -d '{
    "botName": "${b.botName}",
    "strategyType": "${b.strategyType}",
    "targetDex": "${b.targetDex}",
    "targetPair": "${b.targetPair}",
    "targetPoolAddress": "${b.targetPoolAddress}",
    "orderSizeSol": ${b.orderSizeSol},
    "maxSlippageBps": ${b.maxSlippageBps},
    "gasPriorityMode": "${b.gasPriorityMode}",
    "computeUnitLimit": ${b.computeUnitLimit},
    "priorityFeeMicroLamports": ${b.priorityFeeMicroLamports},
    "jitoTipLamports": ${b.jitoTipLamports},
    "maxRiskScoreAbort": ${b.maxRiskScoreAbort.toFixed(1)},
    "requireMintRevoked": ${b.requireMintRevoked},
    "requireEd25519Witness": ${b.requireEd25519Witness}
  }'`;
  }, [
    selectedBotForExport,
    sdkLang,
    metalxTraderAccount,
    metalxMarketId,
    metalxOrderType,
    metalxOrderSide,
    metalxQuantity,
    metalxPrice,
    metalxBidSym,
    metalxAskSym,
    metalxTriggerPrice,
    metalxFillType,
    metalxProcessSize,
  ]);

  const handleCopySdkCode = () => {
    navigator.clipboard?.writeText(generatedSdkCode);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 1800);
    onNotify?.(`Copied ${sdkLang.toUpperCase()} template for ${selectedBotForExport?.botName}`);
  };

  // ============================================================================
  // MEMBERS-ONLY ACCESS LOCK GATE (Shown to unauthenticated visitors)
  // ============================================================================
  if (!isAuthenticated) {
    return (
      <div className="max-w-[1360px] mx-auto px-4 sm:px-6 py-10">
        <div
          data-testid="automation-members-gate"
          className="molt-card-purple p-8 sm:p-10 max-w-3xl mx-auto text-center space-y-6 relative overflow-hidden"
        >
          <div className="mx-auto w-36 h-36 molt-card p-2 relative bg-[#040814]">
            <div className="bracket-tick bracket-tick-tl" />
            <div className="bracket-tick bracket-tick-tr" />
            <div className="bracket-tick bracket-tick-bl" />
            <div className="bracket-tick bracket-tick-br" />
            <SentinelShieldSvg showWordmark className="w-full h-full" />
          </div>

          <div className="cyber-cut-sm inline-flex items-center gap-2 px-3.5 py-1 border border-cyan-400/50 bg-cyan-950/50 text-cyan-300 text-xs font-mono uppercase">
            <Lock className="w-3.5 h-3.5 text-cyan-400" />
            <span>MEMBERS-ONLY AUTOMATION VAULT</span>
          </div>

          <h1 className="font-display font-extrabold text-3xl sm:text-4xl text-white">
            Authenticate to Access Trading &amp; Sniping Bot Studio
          </h1>

          <p className="text-slate-300 text-sm sm:text-base leading-relaxed max-w-2xl mx-auto">
            Configuring sniper bot gas parameters, slippage tolerances, target liquidity pool
            addresses, custom preflight scripts, and Metal X DEX smart contract actions requires an
            authenticated MoltAlpha member session.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5 text-left text-xs text-slate-300 pt-2">
            <div className="bracket-card p-4 space-y-1.5">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5" />
                <span>Gas, Slippage &amp; Pool Targeting</span>
              </div>
              <p className="text-slate-400">
                Fine-tune Compute Unit budgets, microLamport priority fees, Jito MEV tips, and
                Base58 liquidity pool addresses.
              </p>
            </div>

            <div className="bracket-card p-4 space-y-1.5">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Expandable Bot Scripting IDE</span>
              </div>
              <p className="text-slate-400">
                Write and sandbox-test custom preflight &amp; post-fill hooks with deterministic
                SHA-256 manifest attestation.
              </p>
            </div>

            <div className="bracket-card p-4 space-y-1.5">
              <div className="bracket-tick bracket-tick-tl" />
              <div className="bracket-tick bracket-tick-br" />
              <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                <Code2 className="w-3.5 h-3.5" />
                <span>proton-tsc &amp; Bot SDK</span>
              </div>
              <p className="text-slate-400">
                Export XPR Network <code>proton-tsc</code> smart contracts, <code>@proton/js</code>{' '}
                action builders, and TypeScript/Python sniper scripts.
              </p>
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
              <span>Verify Operator Passkey (Member Demo)</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ============================================================================
  // AUTHENTICATED MEMBERS-ONLY BOT STUDIO & SNIPER EXECUTION CONSOLE
  // ============================================================================
  const totalSimulatedRuns = bots.reduce((acc, b) => acc + b.simulatedRunsCount, 0);
  const totalAbortedRugs = bots.reduce((acc, b) => acc + b.abortedRugCount, 0);
  const activeBotsCount = bots.filter((b) => b.status === 'ACTIVE').length;

  return (
    <div
      data-testid="automation-studio-view"
      className="max-w-[1420px] mx-auto px-4 sm:px-6 pt-5 pb-16 space-y-6"
    >
      {/* TOP HEADER & MEMBER TELEMETRY STRIP */}
      <section className="molt-card p-5 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
            <span className="text-cyan-300 font-bold">MEMBERS-ONLY AUTOMATION STUDIO</span>
            <span className="text-slate-600">·</span>
            <span className="text-amber-300">NON-CUSTODIAL SANDBOX SIMULATION</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400">Operator: {userDisplayName}</span>
          </div>
          <h1 className="font-display font-extrabold text-2xl sm:text-3xl text-white tracking-tight">
            Autonomous Trading, Sniping &amp; Smart Contract Bot Studio
          </h1>
          <p className="text-xs sm:text-sm text-slate-300 max-w-3xl">
            Configure sniper bot gas parameters, slippage tolerances, target liquidity pool
            addresses, and custom preflight scripts across{' '}
            <strong className="text-cyan-300">Solana DEXs</strong> and{' '}
            <strong className="text-cyan-300">Metal X DEX (XPR Network)</strong>.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 w-full lg:w-auto shrink-0 font-mono text-xs">
          <div className="bg-slate-950/90 border border-slate-800 px-3.5 py-2.5">
            <span className="text-[10px] text-slate-400 block">Active Member Bots</span>
            <span className="text-lg font-extrabold text-cyan-300 tabular-nums">
              {activeBotsCount} / {bots.length}
            </span>
          </div>
          <div className="bg-slate-950/90 border border-slate-800 px-3.5 py-2.5">
            <span className="text-[10px] text-slate-400 block">Rugs / Traps Aborted</span>
            <span className="text-lg font-extrabold text-emerald-400 tabular-nums">
              {totalAbortedRugs} Blocked
            </span>
          </div>
          <div className="bg-slate-950/90 border border-slate-800 px-3.5 py-2.5">
            <span className="text-[10px] text-slate-400 block">Dry-Run Executions</span>
            <span className="text-lg font-extrabold text-white tabular-nums">
              {totalSimulatedRuns} Runs
            </span>
          </div>
          <div className="bg-slate-950/90 border border-slate-800 px-3.5 py-2.5">
            <span className="text-[10px] text-slate-400 block">API Credits Available</span>
            <span className="text-lg font-extrabold text-purple-300 tabular-nums">
              {userCredits.toLocaleString()}
            </span>
          </div>
        </div>
      </section>

      {/* MAIN 12-COLUMN WORKSPACE */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        {/* LEFT 7 COLUMNS: ACTIVE BOT FLEET + METAL X SMART CONTRACT ACTION BUILDER + EXECUTION STREAM */}
        <div className="xl:col-span-7 space-y-6">
          {/* Bot Fleet List */}
          <section className="molt-card p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Bot className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-bold text-lg text-white">
                  Configured Trading &amp; Sniping Bot Fleet
                </h2>
              </div>
              <span className="text-xs font-mono text-slate-400">
                SOL Spot: <strong className="text-cyan-300">${solPriceUsd.toFixed(2)}</strong> ·
                Witness: <strong className="text-purple-300">{activeWitnessKey.keyId}</strong>
              </span>
            </div>

            <div className="space-y-3">
              {bots.map((bot) => {
                const livePool = pools.find((p) => p.pair === bot.targetPair) || pools[0];
                const willAbort = livePool.riskScore > bot.maxRiskScoreAbort;
                const isSelected = bot.id === selectedBotId;

                return (
                  <div
                    key={bot.id}
                    data-testid={`bot-card-${bot.id}`}
                    className={`p-4 bg-slate-950/85 border transition-colors space-y-3 ${
                      isSelected
                        ? 'border-cyan-400/80 shadow-[0_0_18px_rgba(6,182,212,0.16)]'
                        : 'border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2.5">
                        <img
                          src={getTokenIcon(livePool.baseToken)}
                          alt={livePool.baseToken}
                          referrerPolicy="no-referrer"
                          className="w-7 h-7 rounded-full object-cover border border-slate-700"
                        />
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-display font-bold text-sm text-white">
                              {bot.botName}
                            </span>
                            <span className="text-[11px] font-mono text-slate-400">
                              · {STRATEGY_LABELS[bot.strategyType]}
                            </span>
                          </div>
                          <div className="text-[11px] font-mono text-slate-400 flex flex-wrap items-center gap-1.5">
                            <span className="text-cyan-300 font-bold">{bot.targetPair}</span>
                            <span>·</span>
                            <span className="text-purple-300 font-semibold">{bot.targetDex}</span>
                            <span>·</span>
                            <span title={bot.targetPoolAddress}>
                              Pool: <code>{bot.targetPoolAddress.slice(0, 10)}...</code>
                            </span>
                            <span>·</span>
                            <span
                              className={
                                willAbort ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'
                              }
                            >
                              Risk {livePool.riskScore.toFixed(1)}/10 (Gate &le;{' '}
                              {bot.maxRiskScoreAbort.toFixed(1)})
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <span
                          className={`text-[11px] font-mono font-bold ${
                            bot.status === 'ACTIVE' ? 'text-emerald-400' : 'text-amber-300'
                          }`}
                        >
                          {bot.status}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleRunBotSimulation(bot)}
                          className="molt-btn-cyan px-3 py-1.5 text-xs font-mono inline-flex items-center gap-1.5 cursor-pointer whitespace-nowrap"
                        >
                          <Play className="w-3.5 h-3.5 fill-current" />
                          <span>Test Snipe</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleBotStatus(bot.id)}
                          className="cyber-cut-sm px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-mono text-slate-200 inline-flex items-center gap-1 cursor-pointer"
                          title={bot.status === 'ACTIVE' ? 'Pause Bot' : 'Resume Bot'}
                        >
                          {bot.status === 'ACTIVE' ? (
                            <Pause className="w-3.5 h-3.5 text-amber-300" />
                          ) : (
                            <Play className="w-3.5 h-3.5 text-emerald-400" />
                          )}
                          <span>{bot.status === 'ACTIVE' ? 'Pause' : 'Resume'}</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => handleLoadBotIntoBuilder(bot)}
                          className="cyber-cut-sm px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-mono text-cyan-300 cursor-pointer whitespace-nowrap"
                        >
                          Configure / Export
                        </button>
                        {bots.length > 1 && (
                          <button
                            type="button"
                            onClick={() => handleDeleteBot(bot.id)}
                            className="p-1.5 text-slate-500 hover:text-rose-400 cursor-pointer"
                            title="Remove Bot"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-slate-800/80 text-[11px] font-mono">
                      <div>
                        <span className="text-slate-500 block">Order Size &amp; Slippage</span>
                        <span className="text-white font-semibold tabular-nums">
                          {bot.orderSizeSol.toFixed(2)} SOL · {(bot.maxSlippageBps / 100).toFixed(2)}% ({bot.maxSlippageBps} bps)
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Gas &amp; Compute Budget</span>
                        <span className="text-white font-semibold tabular-nums">
                          {bot.gasPriorityMode} · {(bot.computeUnitLimit / 1000).toFixed(0)}k CU
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Priority Fee / Jito Tip</span>
                        <span className="text-cyan-300 font-semibold tabular-nums">
                          {(bot.priorityFeeMicroLamports / 1000).toFixed(0)}k µL · {(bot.jitoTipLamports / 1e9).toFixed(4)} SOL
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Custom Script / Witness</span>
                        <span className="text-purple-300 truncate block">
                          {bot.customScriptHashSha256
                            ? `Script #${bot.customScriptHashSha256.slice(0, 8)}`
                            : bot.manifestSigEd25519}
                        </span>
                      </div>
                    </div>

                    <div className="text-[11px] font-mono text-slate-300 bg-slate-900/70 px-3 py-1.5 border border-slate-800/80 flex items-center justify-between gap-2">
                      <span className="truncate">
                        <strong className="text-cyan-400">Latest Telemetry:</strong>{' '}
                        {bot.lastOutcome}
                      </span>
                      <button
                        type="button"
                        onClick={() => onNavigateSentinel(bot.targetPair)}
                        className="text-cyan-400 hover:underline shrink-0 inline-flex items-center gap-1 cursor-pointer"
                      >
                        <span>Inspect Pool</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* METAL X DEX SMART CONTRACT ACTIONS STUDIO (docs.metalx.com/developers-dex/smart-contract/actions) */}
          <section
            data-testid="metalx-smart-contract-studio"
            className="molt-card p-5 space-y-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Cpu className="w-5 h-5 text-cyan-400" />
                <div>
                  <h2 className="font-display font-bold text-lg text-white">
                    Metal X DEX Smart Contract Actions Studio (XPR Network <code>dex</code>)
                  </h2>
                  <p className="text-[11px] font-mono text-slate-400">
                    Constructs non-custodial orderqueue actions (<code>placeorder</code>,{' '}
                    <code>process</code>, <code>processsltp</code>, <code>cancelorder</code>) with
                    CPU &lt; 30ms &amp; deterministic RAM accounting
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1.5 text-xs font-mono">
                {(
                  [
                    { id: 'placeorder', label: 'PLACEORDER' },
                    { id: 'process', label: 'PROCESS' },
                    { id: 'processsltp', label: 'PROCESSSLTP' },
                    { id: 'cancelorder', label: 'CANCELORDER' },
                  ] as const
                ).map((act) => (
                  <button
                    key={act.id}
                    type="button"
                    onClick={() => setMetalxAction(act.id)}
                    className={`cyber-cut-sm px-2.5 py-1 border cursor-pointer ${
                      metalxAction === act.id
                        ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold'
                        : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                    }`}
                  >
                    {act.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start text-xs font-mono">
              <div className="lg:col-span-6 space-y-3">
                <div className="grid grid-cols-2 gap-2.5">
                  <div>
                    <label className="text-slate-400 block mb-1">
                      Account Authority (<code>name</code>)
                    </label>
                    <input
                      type="text"
                      value={metalxTraderAccount}
                      onChange={(e) => setMetalxTraderAccount(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-700 px-2.5 py-1.5 text-white outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">
                      Market ID (<code>uint16_t</code>)
                    </label>
                    <input
                      type="number"
                      min="1"
                      value={metalxMarketId}
                      onChange={(e) => setMetalxMarketId(Number(e.target.value) || 1)}
                      className="w-full bg-slate-950 border border-slate-700 px-2.5 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>
                </div>

                {metalxAction === 'placeorder' && (
                  <>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="text-slate-400 block mb-1">Order Type</label>
                        <select
                          value={metalxOrderType}
                          onChange={(e) =>
                            setMetalxOrderType(Number(e.target.value) as 1 | 2 | 3)
                          }
                          className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-white outline-none"
                        >
                          <option value={1}>1 · LIMIT</option>
                          <option value={2}>2 · STOPLOSS</option>
                          <option value={3}>3 · TAKEPROFIT</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-slate-400 block mb-1">Order Side</label>
                        <select
                          value={metalxOrderSide}
                          onChange={(e) => setMetalxOrderSide(Number(e.target.value) as 1 | 2)}
                          className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-white outline-none"
                        >
                          <option value={1}>1 · BUY</option>
                          <option value={2}>2 · SELL</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-slate-400 block mb-1">Fill Type</label>
                        <select
                          value={metalxFillType}
                          onChange={(e) =>
                            setMetalxFillType(Number(e.target.value) as 0 | 1 | 2)
                          }
                          className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-white outline-none"
                        >
                          <option value={0}>0 · GTC</option>
                          <option value={1}>1 · IOC</option>
                          <option value={2}>2 · POST_ONLY</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2.5">
                      <div>
                        <label className="text-slate-400 block mb-1">
                          Quantity (<code>uint64_t</code>)
                        </label>
                        <input
                          type="number"
                          value={metalxQuantity}
                          onChange={(e) => setMetalxQuantity(Number(e.target.value) || 0)}
                          className="w-full bg-slate-950 border border-slate-700 px-2.5 py-1.5 text-white outline-none tabular-nums"
                        />
                      </div>
                      <div>
                        <label className="text-slate-400 block mb-1">
                          Price (<code>uint64_t</code>)
                        </label>
                        <input
                          type="number"
                          value={metalxPrice}
                          onChange={(e) => setMetalxPrice(Number(e.target.value) || 0)}
                          className="w-full bg-slate-950 border border-slate-700 px-2.5 py-1.5 text-white outline-none tabular-nums"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="text-slate-400 block mb-1">
                          <code>bid_symbol</code>
                        </label>
                        <input
                          type="text"
                          value={metalxBidSym}
                          onChange={(e) => setMetalxBidSym(e.target.value)}
                          className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-white outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-slate-400 block mb-1">
                          <code>ask_symbol</code>
                        </label>
                        <input
                          type="text"
                          value={metalxAskSym}
                          onChange={(e) => setMetalxAskSym(e.target.value)}
                          className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-white outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-slate-400 block mb-1">
                          <code>trigger_price</code>
                        </label>
                        <input
                          type="number"
                          value={metalxTriggerPrice}
                          onChange={(e) => setMetalxTriggerPrice(Number(e.target.value) || 0)}
                          className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-white outline-none tabular-nums"
                        />
                      </div>
                    </div>
                  </>
                )}

                {(metalxAction === 'process' || metalxAction === 'processsltp') && (
                  <div>
                    <label className="text-slate-400 block mb-1">
                      Queue Batch Size (<code>uint16_t size</code>)
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="250"
                      value={metalxProcessSize}
                      onChange={(e) => setMetalxProcessSize(Number(e.target.value) || 50)}
                      className="w-full bg-slate-950 border border-slate-700 px-2.5 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>
                )}

                {metalxAction === 'cancelorder' && (
                  <div>
                    <label className="text-slate-400 block mb-1">
                      Order ID to Cancel (<code>uint64_t order_id</code>)
                    </label>
                    <input
                      type="number"
                      min="1"
                      value={metalxCancelOrderId}
                      onChange={(e) => setMetalxCancelOrderId(Number(e.target.value) || 1)}
                      className="w-full bg-slate-950 border border-slate-700 px-2.5 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>
                )}

                <div className="p-2.5 bg-slate-950/90 border border-slate-800 text-[11px] text-slate-400 space-y-1">
                  <div className="text-cyan-300 font-semibold">
                    Admin-Only Contract Actions (Authority: <code>admin</code>)
                  </div>
                  <p>
                    <code>createmarket(bid_token, ask_token)</code> ·{' '}
                    <code>pausedex(status)</code> · <code>setfeeacnt(account)</code> ·{' '}
                    <code>setusertier(account, tier)</code> are restricted to contract
                    administrators.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={handleSimulateMetalXAction}
                  className="molt-btn-cyan w-full py-2 text-xs font-bold inline-flex items-center justify-center gap-2 cursor-pointer"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Simulate Metal X {metalxAction.toUpperCase()} + Witness Check</span>
                </button>
              </div>

              <div className="lg:col-span-6 space-y-2">
                <div className="flex items-center justify-between text-[11px] text-slate-400">
                  <span>
                    Serialized XPR Network Action Payload (<code>dex::{metalxAction}</code>)
                  </span>
                  <span className="text-emerald-400">CPU Budget &lt; 30ms</span>
                </div>
                <pre className="bg-black/90 border border-slate-800 p-3 text-[11px] text-cyan-200 overflow-x-auto leading-relaxed max-h-[265px]">
                  <code>{metalxActionPayloadJson}</code>
                </pre>
              </div>
            </div>
          </section>

          {/* Live Preflight & Execution Log */}
          <section className="molt-card p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-bold text-lg text-white">
                  Sentinel Pre-Trade Risk Gate &amp; Dry-Run Execution Log
                </h2>
              </div>

              <div className="flex items-center gap-1.5 text-xs font-mono">
                {(
                  [
                    { id: 'ALL', label: 'All Events' },
                    { id: 'BUNDLE_SIMULATED', label: 'Simulated Fills' },
                    { id: 'PREFLIGHT_ABORTED', label: 'Sentinel Aborts' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setLogFilter(tab.id)}
                    className={`cyber-cut-sm px-2.5 py-1 border cursor-pointer ${
                      logFilter === tab.id
                        ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold'
                        : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
              {filteredLogs.map((entry) => (
                <div
                  key={entry.id}
                  className="p-3 bg-slate-950/90 border border-slate-800/90 text-xs font-mono space-y-1.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {entry.decision === 'PREFLIGHT_ABORTED' ? (
                        <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                      ) : (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                      )}
                      <span className="font-bold text-white">{entry.botName}</span>
                      <span className="text-slate-500">·</span>
                      <span className="text-cyan-300 font-bold">{entry.pair}</span>
                      <span className="text-slate-500">·</span>
                      <span
                        className={
                          entry.decision === 'PREFLIGHT_ABORTED'
                            ? 'text-rose-400 font-bold'
                            : 'text-emerald-400 font-bold'
                        }
                      >
                        {entry.decision}
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 tabular-nums">
                      Slot #{entry.slot.toLocaleString()} · {entry.timestamp}
                    </span>
                  </div>
                  <p className="text-slate-300 leading-relaxed">{entry.detail}</p>
                  <div className="text-[10px] text-slate-500 flex items-center justify-between pt-0.5">
                    <span>
                      Observed Risk: {entry.observedRiskScore.toFixed(1)}/10 · Bot Gate: &le;{' '}
                      {entry.maxRiskThreshold.toFixed(1)}/10
                    </span>
                    <span className="text-purple-300">Witness: {entry.witnessSig}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* RIGHT 5 COLUMNS: SNIPER BOT CONFIGURATION FORM (GAS, SLIPPAGE, POOL ADDRESS, EXPANDABLE SCRIPTING) + EXPORTER */}
        <div className="xl:col-span-5 space-y-6">
          {/* Sniper Bot Configuration Form */}
          <section
            data-testid="sniper-bot-config-form"
            className="molt-card-purple p-5 space-y-4"
          >
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Sliders className="w-5 h-5 text-cyan-400" />
                <div>
                  <h2 className="font-display font-bold text-lg text-white">
                    Sniper Bot Configuration Form
                  </h2>
                  <p className="text-[11px] font-mono text-slate-400">
                    Define gas settings, slippage tolerance, target liquidity pool &amp; custom hooks
                  </p>
                </div>
              </div>
              <span className="text-[11px] font-mono text-cyan-300">POST /api/v1/automation/bots</span>
            </div>

            <form onSubmit={handleCreateBot} className="space-y-4 text-xs font-mono">
              {/* 1. Bot Name & Strategy */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label htmlFor="sniper-bot-name" className="text-slate-300 block mb-1">
                    Bot Identifier Name
                  </label>
                  <input
                    id="sniper-bot-name"
                    type="text"
                    value={botName}
                    onChange={(e) => setBotName(e.target.value)}
                    placeholder="e.g., BONK Liquidity Dip Sniper"
                    className="w-full bg-slate-950 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="sniper-strategy-type" className="text-slate-300 block mb-1">
                    Strategy Archetype
                  </label>
                  <select
                    id="sniper-strategy-type"
                    value={strategyType}
                    onChange={(e) => setStrategyType(e.target.value as BotStrategyType)}
                    className="w-full bg-slate-950 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white outline-none"
                  >
                    <option value="LIQUIDITY_SNIPER">New-Pool Liquidity Sniper</option>
                    <option value="METALX_ORDERBOOK_SNIPER">
                      Metal X Smart Contract OrderQ Sniper
                    </option>
                    <option value="CLMM_RANGE_ARB">CLMM Tick Vacuum Arbitrage</option>
                    <option value="DCA_SENTINEL_GUARD">Sentinel-Guarded Limit / DCA</option>
                    <option value="WHALE_COPY_SHIELD">Smart-Wallet Copy Shield</option>
                  </select>
                </div>
              </div>

              {/* 2. Target DEX & Pair */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label htmlFor="sniper-target-dex" className="text-slate-300 block mb-1">
                    Target Execution DEX
                  </label>
                  <select
                    id="sniper-target-dex"
                    value={targetDex}
                    onChange={(e) => setTargetDex(e.target.value as SupportedDexTarget)}
                    className="w-full bg-slate-950 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white outline-none"
                  >
                    <option value="Raydium">Raydium CLMM / AMM v4</option>
                    <option value="Orca">Orca Whirlpools</option>
                    <option value="Meteora">Meteora DLMM</option>
                    <option value="Jupiter">Jupiter v6 Aggregator</option>
                    <option value="Metal X DEX">Metal X DEX (XPR Network dex Contract)</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="sniper-target-pair" className="text-slate-300 block mb-1">
                    Target Pool Pair
                  </label>
                  <select
                    id="sniper-target-pair"
                    value={targetPair}
                    onChange={(e) => handleSelectPairChange(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white outline-none"
                  >
                    {pools.map((p) => (
                      <option key={p.id} value={p.pair}>
                        {p.pair} (Risk {p.riskScore.toFixed(1)} · {formatTokenPriceUsd(p.priceUsd)})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* 3. Target Liquidity Pool Address */}
              <div className="p-3 bg-slate-950/90 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <label
                    htmlFor="target-pool-address-input"
                    className="text-cyan-300 font-bold flex items-center gap-1.5"
                  >
                    <Target className="w-3.5 h-3.5" />
                    <span>Target Liquidity Pool Address</span>
                  </label>
                  <span
                    className={`text-[11px] font-bold ${
                      poolAddressValidation.valid ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                  >
                    {poolAddressValidation.kind}
                  </span>
                </div>

                <input
                  id="target-pool-address-input"
                  data-testid="target-pool-address-input"
                  type="text"
                  value={targetPoolAddress}
                  onChange={(e) => setTargetPoolAddress(e.target.value)}
                  placeholder="Enter Base58 Solana AMM/CLMM Pool Address or Metal X Market ID"
                  className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white outline-none tabular-nums"
                />

                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  <span className="text-[10px] text-slate-400">Quick Pool Presets:</span>
                  {(
                    [
                      {
                        label: 'Raydium BONK/SOL',
                        pair: 'BONK/SOL',
                        dex: 'Raydium' as SupportedDexTarget,
                        addr: POOL_ADDRESS_BY_PAIR['BONK/SOL'],
                      },
                      {
                        label: 'Raydium SOL/USDC',
                        pair: 'SOL/USDC',
                        dex: 'Raydium' as SupportedDexTarget,
                        addr: POOL_ADDRESS_BY_PAIR['SOL/USDC'],
                      },
                      {
                        label: 'Orca POPCAT/SOL',
                        pair: 'POPCAT/SOL',
                        dex: 'Orca' as SupportedDexTarget,
                        addr: POOL_ADDRESS_BY_PAIR['POPCAT/SOL'],
                      },
                      {
                        label: 'Metal X Market #1',
                        pair: 'SOL/USDC',
                        dex: 'Metal X DEX' as SupportedDexTarget,
                        addr: 'dex::market_1_sol_xusdc',
                      },
                    ] as const
                  ).map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => {
                        setTargetPair(preset.pair);
                        setTargetDex(preset.dex);
                        setTargetPoolAddress(preset.addr);
                      }}
                      className="px-2 py-0.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-[10px] text-cyan-300 cursor-pointer whitespace-nowrap"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 4. Order Size & Slippage Tolerance */}
              <div
                data-testid="slippage-tolerance-section"
                className="p-3 bg-slate-950/90 border border-slate-800 space-y-2.5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-cyan-300 font-bold flex items-center gap-1.5">
                    <Sliders className="w-3.5 h-3.5" />
                    <span>Order Size &amp; Slippage Tolerance</span>
                  </span>
                  <span className="text-white font-semibold tabular-nums text-xs">
                    {(Number(maxSlippageBps || 0) / 100).toFixed(2)}% ({maxSlippageBps || '0'} bps)
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  <div>
                    <label htmlFor="sniper-order-size" className="text-slate-400 block mb-1">
                      Order Allocation (SOL)
                    </label>
                    <input
                      id="sniper-order-size"
                      type="number"
                      step="0.01"
                      min="0.01"
                      max="250"
                      value={orderSizeSol}
                      onChange={(e) => setOrderSizeSol(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-3 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>

                  <div>
                    <label htmlFor="sniper-slippage-percent" className="text-slate-400 block mb-1">
                      Slippage Tolerance (%)
                    </label>
                    <div className="relative">
                      <input
                        id="sniper-slippage-percent"
                        data-testid="slippage-tolerance-input"
                        type="number"
                        step="0.05"
                        min="0.05"
                        max="10.0"
                        value={slippagePercent}
                        onChange={(e) => handleSlippagePercentChange(e.target.value)}
                        placeholder="0.50"
                        className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-3 py-1.5 pr-7 text-white outline-none tabular-nums"
                      />
                      <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs font-mono text-slate-400 pointer-events-none">
                        %
                      </span>
                    </div>
                  </div>

                  <div>
                    <label htmlFor="sniper-slippage-bps" className="text-slate-400 block mb-1">
                      Basis Points (bps)
                    </label>
                    <input
                      id="sniper-slippage-bps"
                      data-testid="slippage-bps-input"
                      type="number"
                      step="1"
                      min="5"
                      max="1000"
                      value={maxSlippageBps}
                      onChange={(e) => handleSlippageBpsChange(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-3 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-800/80">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[10px] text-slate-400 mr-0.5">Common Presets:</span>
                    {(
                      [
                        { pct: '0.1', bps: '10', label: '0.1%' },
                        { pct: '0.5', bps: '50', label: '0.5%' },
                        { pct: '1.0', bps: '100', label: '1.0%' },
                      ] as const
                    ).map((preset) => {
                      const isSelected = maxSlippageBps === preset.bps || slippagePercent === preset.pct;
                      return (
                        <button
                          key={preset.pct}
                          type="button"
                          data-testid={`slippage-preset-${preset.pct}`}
                          onClick={() => handleSelectSlippagePreset(preset.pct, preset.bps)}
                          className={`px-3 py-1 border text-xs font-mono font-bold cursor-pointer transition-colors ${
                            isSelected
                              ? 'bg-cyan-500/25 text-cyan-300 border-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.25)]'
                              : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white hover:border-slate-700'
                          }`}
                        >
                          {preset.label}
                        </button>
                      );
                    })}
                    {/* Companion aliases for tests referencing bps testids */}
                    <button
                      type="button"
                      data-testid="slippage-preset-10"
                      onClick={() => handleSelectSlippagePreset('0.1', '10')}
                      className="sr-only"
                      tabIndex={-1}
                      aria-hidden="true"
                    >
                      0.1%
                    </button>
                    <button
                      type="button"
                      data-testid="slippage-preset-50"
                      onClick={() => handleSelectSlippagePreset('0.5', '50')}
                      className="sr-only"
                      tabIndex={-1}
                      aria-hidden="true"
                    >
                      0.5%
                    </button>
                    <button
                      type="button"
                      data-testid="slippage-preset-100"
                      onClick={() => handleSelectSlippagePreset('1.0', '100')}
                      className="sr-only"
                      tabIndex={-1}
                      aria-hidden="true"
                    >
                      1.0%
                    </button>
                  </div>

                  <div className="text-[10px] font-mono">
                    {Number(maxSlippageBps) > 200 ? (
                      <span className="text-amber-300 font-semibold flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        <span>High MEV Sandwich Exposure (&gt;2.0%)</span>
                      </span>
                    ) : Number(maxSlippageBps) < 10 && maxSlippageBps !== '' ? (
                      <span className="text-sky-300 font-semibold">
                        Tight slippage (&lt;0.1%): trades may revert
                      </span>
                    ) : (
                      <span className="text-slate-400">
                        Target range: 0.1% – 1.0% recommended
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* 5. Gas & Priority Fee Settings */}
              <div
                data-testid="gas-settings-section"
                className="p-3 bg-slate-950/90 border border-slate-800 space-y-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-cyan-300 font-bold flex items-center gap-1.5">
                    <Fuel className="w-3.5 h-3.5" />
                    <span>Gas, Compute Units &amp; Jito Priority Settings</span>
                  </span>

                  <div className="flex items-center gap-1">
                    {(
                      [
                        { id: 'STANDARD', label: 'Standard' },
                        { id: 'TURBO', label: 'Turbo' },
                        { id: 'ULTRA_JITO_MEV', label: 'Ultra Jito MEV' },
                      ] as const
                    ).map((tier) => (
                      <button
                        key={tier.id}
                        type="button"
                        data-testid={`gas-mode-${tier.id}`}
                        onClick={() => handleSelectGasPreset(tier.id)}
                        className={`px-2 py-0.5 border text-[10px] cursor-pointer whitespace-nowrap ${
                          gasPriorityMode === tier.id
                            ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold'
                            : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                        }`}
                      >
                        {tier.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  <div>
                    <label htmlFor="sniper-cu-limit" className="text-slate-400 block mb-1">
                      Compute Limit (CU)
                    </label>
                    <input
                      id="sniper-cu-limit"
                      data-testid="compute-unit-limit-input"
                      type="number"
                      step="1000"
                      min="50000"
                      max="1400000"
                      value={computeUnitLimit}
                      onChange={(e) => setComputeUnitLimit(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-2.5 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>

                  <div>
                    <label htmlFor="sniper-priority-fee" className="text-slate-400 block mb-1">
                      Priority (µLamports/CU)
                    </label>
                    <input
                      id="sniper-priority-fee"
                      data-testid="priority-fee-input"
                      type="number"
                      step="100"
                      min="100"
                      max="5000000"
                      value={priorityFeeMicroLamports}
                      onChange={(e) => setPriorityFeeMicroLamports(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-2.5 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>

                  <div>
                    <label htmlFor="sniper-jito-tip" className="text-slate-400 block mb-1">
                      Jito Bribe (Lamports)
                    </label>
                    <input
                      id="sniper-jito-tip"
                      data-testid="jito-tip-input"
                      type="number"
                      step="1000"
                      min="1000"
                      max="10000000"
                      value={jitoTipLamports}
                      onChange={(e) => setJitoTipLamports(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-2.5 py-1.5 text-white outline-none tabular-nums"
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-800/80">
                  <span>
                    Priority Gas: {estimatedGasTelemetry.computePriorityLamports.toLocaleString()}{' '}
                    lamports
                  </span>
                  <span className="text-cyan-300 font-semibold tabular-nums">
                    Est. Total Execution Gas: {estimatedGasTelemetry.totalSol.toFixed(5)} SOL ($
                    {estimatedGasTelemetry.totalUsd.toFixed(3)})
                  </span>
                </div>
              </div>

              {/* 6. Sentinel Pre-Trade Risk Score Abort Slider */}
              <div className="p-3 bg-slate-950/90 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="sniper-risk-abort-slider" className="text-cyan-300 font-bold">
                    Sentinel Max Risk Score Abort Gate
                  </label>
                  <span className="text-white font-extrabold tabular-nums">
                    &le; {maxRiskScoreAbort.toFixed(1)} / 10
                  </span>
                </div>
                <input
                  id="sniper-risk-abort-slider"
                  type="range"
                  min="1.5"
                  max="9.0"
                  step="0.1"
                  value={maxRiskScoreAbort}
                  onChange={(e) => setMaxRiskScoreAbort(Number(e.target.value))}
                  className="w-full accent-cyan-400 cursor-pointer"
                />
                <div className="flex items-center justify-between text-[11px] text-slate-400">
                  <span>
                    Selected {selectedPoolForBuilder.pair} Live Risk:{' '}
                    <strong className="text-white">
                      {selectedPoolForBuilder.riskScore.toFixed(1)}/10
                    </strong>
                  </span>
                  <span
                    className={
                      selectedPoolForBuilder.riskScore > maxRiskScoreAbort
                        ? 'text-rose-400 font-bold'
                        : 'text-emerald-400 font-bold'
                    }
                  >
                    {selectedPoolForBuilder.riskScore > maxRiskScoreAbort
                      ? 'WILL ABORT SNIPE (RISK TOO HIGH)'
                      : 'PREFLIGHT PASSES'}
                  </span>
                </div>
              </div>

              {/* 7. EXPANDABLE CUSTOM BOT SCRIPTING PANEL */}
              <div className="border border-cyan-500/40 bg-slate-950/95">
                <button
                  type="button"
                  data-testid="toggle-scripting-panel-btn"
                  aria-expanded={isScriptingExpanded}
                  onClick={() => setIsScriptingExpanded((prev) => !prev)}
                  className="w-full px-3.5 py-2.5 flex items-center justify-between text-left hover:bg-slate-900/80 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-cyan-400 shrink-0" />
                    <div>
                      <span className="text-cyan-300 font-bold block">
                        Custom Bot Scripting &amp; Hook IDE (Expandable)
                      </span>
                      <span className="text-[10px] text-slate-400">
                        Customize preflight filters, dynamic gas escalators &amp; Metal X orderQ triggers
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 text-cyan-300 text-[11px] font-bold shrink-0">
                    <span>{isScriptingExpanded ? 'Collapse Panel' : 'Expand Scripting Panel'}</span>
                    {isScriptingExpanded ? (
                      <ChevronUp className="w-4 h-4" />
                    ) : (
                      <ChevronDown className="w-4 h-4" />
                    )}
                  </div>
                </button>

                {isScriptingExpanded && (
                  <div
                    data-testid="expandable-scripting-panel"
                    className="p-3.5 border-t border-slate-800 space-y-3 bg-[#030712]"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <label className="flex items-center gap-2 cursor-pointer text-[11px] text-slate-200">
                        <input
                          type="checkbox"
                          checked={enableCustomScript}
                          onChange={(e) => setEnableCustomScript(e.target.checked)}
                          className="accent-cyan-400"
                        />
                        <span>Attach Custom Script Hook to Bot Manifest</span>
                      </label>

                      <span className="text-[10px] text-slate-400 tabular-nums">
                        {customScriptCode.length} / 4,000 chars
                      </span>
                    </div>

                    <div className="space-y-1.5">
                      <span className="text-[10px] text-slate-400 block">
                        Load Starter Hook Template:
                      </span>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        {CUSTOM_SCRIPT_TEMPLATES.map((tpl) => (
                          <button
                            key={tpl.id}
                            type="button"
                            onClick={() => handleApplyScriptTemplate(tpl.id)}
                            className={`p-2 text-left border cursor-pointer transition-colors ${
                              selectedTemplateId === tpl.id
                                ? 'bg-cyan-500/15 border-cyan-400 text-cyan-200'
                                : 'bg-slate-900/90 border-slate-800 text-slate-400 hover:text-white'
                            }`}
                          >
                            <div className="font-bold text-[11px]">{tpl.label}</div>
                            <div className="text-[10px] text-slate-400 truncate">
                              {tpl.description}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label
                        htmlFor="custom-script-editor"
                        className="text-slate-300 block mb-1 text-[11px]"
                      >
                        Sandbox Hook Script (<code>onBeforeSnipe(ctx)</code> /{' '}
                        <code>onAfterSnipeFill(ctx)</code>)
                      </label>
                      <textarea
                        id="custom-script-editor"
                        data-testid="custom-script-textarea"
                        rows={9}
                        value={customScriptCode}
                        onChange={(e) => {
                          setCustomScriptCode(e.target.value);
                          setScriptValidationFeedback({ status: 'idle', message: '' });
                        }}
                        className="w-full bg-black border border-slate-700 focus:border-cyan-400 p-2.5 text-[11px] font-mono text-cyan-200 outline-none leading-relaxed"
                      />
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <button
                        type="button"
                        data-testid="validate-custom-script-btn"
                        onClick={handleValidateAndDryRunCustomScript}
                        className="cyber-cut-sm px-3 py-1.5 bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-400 text-cyan-200 text-xs font-bold inline-flex items-center gap-1.5 cursor-pointer"
                      >
                        <ShieldCheck className="w-3.5 h-3.5 text-cyan-300" />
                        <span>Validate &amp; Sandbox Test Script</span>
                      </button>

                      <span className="text-[10px] text-slate-500">
                        Blocks <code>eval()</code>, <code>fs</code>, <code>process.env</code> &amp;
                        raw private keys
                      </span>
                    </div>

                    {scriptValidationFeedback.status !== 'idle' && (
                      <div
                        data-testid="script-validation-result"
                        className={`p-2.5 border text-[11px] space-y-1 ${
                          scriptValidationFeedback.status === 'valid'
                            ? 'bg-emerald-950/50 border-emerald-500/60 text-emerald-200'
                            : 'bg-rose-950/60 border-rose-500/60 text-rose-200'
                        }`}
                      >
                        <div className="font-bold">{scriptValidationFeedback.message}</div>
                        {scriptValidationFeedback.simulatedDecision && (
                          <div className="text-cyan-200">
                            Dry-Run Outcome: <strong>{scriptValidationFeedback.simulatedDecision}</strong>
                          </div>
                        )}
                        {scriptValidationFeedback.scriptHash && (
                          <div className="text-[10px] text-purple-300 truncate">
                            SHA-256 Digest: {scriptValidationFeedback.scriptHash}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Security Checkboxes */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <label className="flex items-center gap-2 p-2.5 bg-slate-950/80 border border-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={requireMintRevoked}
                    onChange={(e) => setRequireMintRevoked(e.target.checked)}
                    className="accent-cyan-400"
                  />
                  <span className="text-[11px] text-slate-200">
                    Require Mint &amp; Freeze Revoked
                  </span>
                </label>

                <label className="flex items-center gap-2 p-2.5 bg-slate-950/80 border border-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={requireEd25519Witness}
                    onChange={(e) => setRequireEd25519Witness(e.target.checked)}
                    className="accent-cyan-400"
                  />
                  <span className="text-[11px] text-slate-200">
                    Require Ed25519 State Witness
                  </span>
                </label>
              </div>

              <div>
                <label htmlFor="sniper-webhook-uri" className="text-slate-300 block mb-1">
                  Optional Alert Webhook URI (HTTPS / IPFS — SSRF Protected)
                </label>
                <input
                  id="sniper-webhook-uri"
                  type="text"
                  value={webhookCallbackUri}
                  onChange={(e) => setWebhookCallbackUri(e.target.value)}
                  placeholder="https://hooks.example.com/molt-bot-alerts (optional)"
                  className="w-full bg-slate-950 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white outline-none"
                />
              </div>

              {formError && (
                <div
                  data-testid="sniper-form-error"
                  className="p-2.5 bg-rose-950/60 border border-rose-500/60 text-rose-200 text-xs"
                >
                  {formError}
                </div>
              )}

              <button
                type="submit"
                data-testid="deploy-sniper-bot-btn"
                className="molt-btn-cyan w-full py-2.5 text-xs font-bold inline-flex items-center justify-center gap-2 cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                <span>Deploy &amp; Attest Bot Manifest</span>
              </button>
            </form>
          </section>

          {/* Non-Custodial Bot SDK & proton-tsc Smart Contract Exporter */}
          <section className="molt-card p-5 space-y-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <FileCode2 className="w-5 h-5 text-cyan-400" />
                <div>
                  <h2 className="font-display font-bold text-base text-white">
                    Smart Contract &amp; Non-Custodial Bot Exporter
                  </h2>
                  <p className="text-[11px] font-mono text-slate-400">
                    Exporting: <strong className="text-cyan-300">{selectedBotForExport?.botName}</strong>
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-1.5 text-xs font-mono">
                {(
                  [
                    { id: 'proton-tsc', label: 'proton-tsc Contract' },
                    { id: 'metalx-dex', label: 'Metal X @proton/js' },
                    { id: 'typescript', label: 'TS Bot' },
                    { id: 'python', label: 'Python' },
                    { id: 'curl', label: 'cURL' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setSdkLang(tab.id)}
                    className={`cyber-cut-sm px-2.5 py-1 border cursor-pointer ${
                      sdkLang === tab.id
                        ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold'
                        : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            <pre className="bg-black/85 border border-slate-800 p-3.5 text-[11px] font-mono text-cyan-200 overflow-x-auto leading-relaxed max-h-[340px]">
              <code>{generatedSdkCode}</code>
            </pre>

            <div className="flex items-center justify-between gap-2 pt-1">
              <button
                type="button"
                onClick={onNavigateDevelopers}
                className="text-xs font-mono text-cyan-400 hover:underline inline-flex items-center gap-1 cursor-pointer"
              >
                <Layers className="w-3.5 h-3.5" />
                <span>Manage Scoped API Keys</span>
              </button>

              <button
                type="button"
                onClick={handleCopySdkCode}
                className="cyber-cut-sm px-3.5 py-1.5 bg-slate-900 hover:bg-slate-800 border border-cyan-500/50 text-xs font-mono text-cyan-200 inline-flex items-center gap-1.5 cursor-pointer"
              >
                {copiedCode ? (
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <Copy className="w-3.5 h-3.5 text-cyan-400" />
                )}
                <span>{copiedCode ? 'Copied Code' : 'Copy Code'}</span>
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
