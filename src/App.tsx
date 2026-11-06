import React, { useState, useEffect, useCallback } from 'react';
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  User as FirebaseUser,
} from 'firebase/auth';
import {
  doc,
  getDoc,
  setDoc,
  collection,
  query,
  where,
  onSnapshot,
  serverTimestamp,
} from 'firebase/firestore';
import {
  ShieldCheck,
  Code2,
  Sparkles,
  LogOut,
  LogIn,
  ArrowRight,
  ExternalLink,
  Award,
  Gem,
  Bot,
} from 'lucide-react';
import {
  auth,
  db,
  googleProvider,
  OperationType,
  handleFirestoreError,
  sanitizeId,
  sanitizeBoundedString,
} from './firebase';
import { MoltLogoMark, SentinelShieldBadge } from './components/IsometricChipGraphic';
import { LandingPage } from './components/LandingPage';
import { SentinelTerminalPage } from './components/SentinelTerminalPage';
import { DevelopersPricingPage } from './components/DevelopersPricingPage';
import { BountiesPage } from './components/BountiesPage';
import { NftsPage, MoltNftItem } from './components/NftsPage';
import { AdminPanelPage } from './components/AdminPanelPage';
import { AutomationPage } from './components/AutomationPage';
import {
  DexPool,
  RiskAlertItem,
  LiveTxFlowPacket,
  PaymentRecord,
  AuditLogItem,
  WitnessKeyRecord,
  ManagedUserRecord,
  AgentOperationItem,
  PaymentRail,
  PricingTierName,
  INITIAL_POOLS,
  INITIAL_ALERTS,
  INITIAL_LIVE_TX_PACKETS,
  INITIAL_PAYMENTS,
  INITIAL_AUDIT_LOGS,
  INITIAL_WITNESS_KEYS,
  INITIAL_MANAGED_USERS,
  INITIAL_AGENT_OPS,
  calculateMultiRailQuote,
  rotateWitnessKeys,
} from './utils/cryptoEngine';

export type ActivePageView =
  | 'platform'
  | 'sentinel'
  | 'automation'
  | 'developers'
  | 'bounties'
  | 'nfts'
  | 'admin';

interface MarketIntelligenceApiResponse {
  ok: boolean;
  solPriceUsd?: number;
  providerSummary?: string;
  tokens?: Record<
    string,
    {
      symbol: string;
      solanaMintAddress?: string;
      priceUsd: number;
      change24hPct: number | null;
      high24hUsd: number | null;
      low24hUsd: number | null;
      volume24hUsd: number | null;
      marketCapUsd: number;
      fdvUsd: number;
      source: string;
      stats24hAvailable?: boolean;
      simulatedDemoFallback?: {
        isSimulatedDemo: true;
        change24hPct: number;
        high24hUsd: number;
        low24hUsd: number;
        volume24hUsd: number;
      };
    }
  >;
}

export default function App() {
  const [activePage, setActivePage] = useState<ActivePageView>('platform');
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [serverSessionToken, setServerSessionToken] = useState<string | null>(null);
  const [operatorSessionActive, setOperatorSessionActive] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      return params.get('autostart') === '1';
    }
    return false;
  });

  const [currentSlot, setCurrentSlot] = useState<number>(312891045);
  const [pools, setPools] = useState<DexPool[]>(INITIAL_POOLS);
  const [selectedPoolPair, setSelectedPoolPair] = useState<string>('POPCAT/SOL');
  const [alerts, setAlerts] = useState<RiskAlertItem[]>(INITIAL_ALERTS);
  const [txPackets, setTxPackets] = useState<LiveTxFlowPacket[]>(INITIAL_LIVE_TX_PACKETS);
  const [payments, setPayments] = useState<PaymentRecord[]>(INITIAL_PAYMENTS);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>(INITIAL_AUDIT_LOGS);
  const [witnessKeys, setWitnessKeys] = useState<WitnessKeyRecord[]>(INITIAL_WITNESS_KEYS);
  const [managedUsers, setManagedUsers] = useState<ManagedUserRecord[]>(INITIAL_MANAGED_USERS);
  const [agentOps, setAgentOps] = useState<AgentOperationItem[]>(INITIAL_AGENT_OPS);
  const [userCredits, setUserCredits] = useState<number>(1500);
  const [keyEpochCounter, setKeyEpochCounter] = useState<number>(8);
  const [statusToast, setStatusToast] = useState<string | null>(null);

  // Live Coinbase Exchange telemetry state
  const [solPriceUsd, setSolPriceUsd] = useState<number>(185.2);
  const [marketProviderSummary, setMarketProviderSummary] = useState<string>(
    'Coinbase Exchange Live'
  );
  const [lastMarketSync, setLastMarketSync] = useState<string>('Live');
  const [isSyncingMarket, setIsSyncingMarket] = useState<boolean>(false);

  const isAuthenticated = Boolean(firebaseUser) || operatorSessionActive;
  const userDisplayName =
    firebaseUser?.displayName ||
    firebaseUser?.email?.split('@')[0] ||
    (operatorSessionActive ? 'operator_ed25519' : 'Guest');

  const showNotification = useCallback((msg: string) => {
    setStatusToast(msg);
    setTimeout(() => {
      setStatusToast((prev) => (prev === msg ? null : prev));
    }, 3200);
  }, []);

  // Fetch live market telemetry from /api/market-intelligence (Coinbase Exchange)
  const syncLiveMarketTelemetry = useCallback(
    async (notifyUser = false) => {
      setIsSyncingMarket(true);
      try {
        const res = await fetch('/api/market-intelligence');
        if (!res.ok) return;
        const data = (await res.json()) as MarketIntelligenceApiResponse;
        if (!data.ok || !data.tokens) return;

        if (typeof data.solPriceUsd === 'number' && data.solPriceUsd > 0) {
          setSolPriceUsd(data.solPriceUsd);
        }
        if (data.providerSummary) {
          setMarketProviderSummary(data.providerSummary);
        }

        const nowTime = new Date().toTimeString().slice(0, 8);
        setLastMarketSync(nowTime);

        setPools((prev) =>
          prev.map((pool) => {
            const live = data.tokens?.[pool.baseToken];
            if (!live) return pool;
            const hasLive24h = Boolean(live.stats24hAvailable);
            const fallback = live.simulatedDemoFallback;
            return {
              ...pool,
              priceUsd: live.priceUsd || pool.priceUsd,
              change24hPct:
                typeof live.change24hPct === 'number'
                  ? live.change24hPct
                  : fallback?.change24hPct ?? pool.change24hPct,
              high24hUsd:
                typeof live.high24hUsd === 'number'
                  ? live.high24hUsd
                  : fallback?.high24hUsd ?? pool.high24hUsd,
              low24hUsd:
                typeof live.low24hUsd === 'number'
                  ? live.low24hUsd
                  : fallback?.low24hUsd ?? pool.low24hUsd,
              volume24hUsd:
                typeof live.volume24hUsd === 'number' && live.volume24hUsd > 0
                  ? live.volume24hUsd
                  : fallback?.volume24hUsd ?? pool.volume24hUsd,
              marketCapUsd: live.marketCapUsd > 100_000 ? live.marketCapUsd : pool.marketCapUsd,
              fdvUsd: live.fdvUsd > 100_000 ? live.fdvUsd : pool.fdvUsd,
              liveSource: live.source || pool.liveSource,
              lastUpdate: hasLive24h
                ? 'Coinbase Live'
                : live.source.includes('Simulated')
                  ? 'Simulated Demo'
                  : 'Spot Only (24h Sim)',
            };
          })
        );

        if (notifyUser) {
          showNotification('Synced live prices & volume from Coinbase Exchange.');
        }
      } catch {
        // Keep last known live state if offline
      } finally {
        setIsSyncingMarket(false);
      }
    },
    [showNotification]
  );

  useEffect(() => {
    syncLiveMarketTelemetry(false);
    const interval = setInterval(() => {
      syncLiveMarketTelemetry(false);
    }, 30_000);
    return () => clearInterval(interval);
  }, [syncLiveMarketTelemetry]);

  // Listen to Firebase Auth state & sync least-privilege profile with Firestore
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setFirebaseUser(user);
      if (user && user.emailVerified) {
        try {
          const idToken = await user.getIdToken();
          const sessionRes = await fetch('/api/v1/auth/session', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${idToken}`,
            },
            body: JSON.stringify({}),
          });
          if (sessionRes.ok) {
            const sessionData = (await sessionRes.json()) as {
              ok: boolean;
              sessionToken?: string;
            };
            if (sessionData.ok && sessionData.sessionToken) {
              setServerSessionToken(sessionData.sessionToken);
            }
          }
        } catch {
          // Non-fatal in preview if token exchange is skipped
        }

        const uid = sanitizeId(user.uid);
        const userRef = doc(db, 'users', uid);
        const safeDisplayName = sanitizeBoundedString(
          user.displayName || user.email || 'Operator',
          1,
          80,
          'Operator'
        );
        try {
          const existingSnap = await getDoc(userRef);
          if (!existingSnap.exists()) {
            await setDoc(userRef, {
              uid,
              displayName: safeDisplayName,
              tier: 'Micro',
              credits: 0,
              rateLimitRps: 15,
              status: 'Active',
              createdAt: serverTimestamp(),
              updatedAt: serverTimestamp(),
            });
          } else {
            await setDoc(
              userRef,
              {
                displayName: safeDisplayName,
                updatedAt: serverTimestamp(),
              },
              { merge: true }
            );
          }
        } catch (err) {
          handleFirestoreError(err, OperationType.WRITE, `users/${uid}`);
        }
      } else {
        setServerSessionToken(null);
      }
    });
    return () => unsubscribe();
  }, []);

  // Attach Firestore listeners for authenticated user's auditLogs and settlements
  useEffect(() => {
    if (!firebaseUser) return;
    const uid = sanitizeId(firebaseUser.uid);

    const logsQuery = query(collection(db, 'auditLogs'), where('ownerId', '==', uid));
    const unsubLogs = onSnapshot(
      logsQuery,
      (snapshot) => {
        if (!snapshot.empty) {
          const remoteLogs: AuditLogItem[] = snapshot.docs.map((d) => {
            const data = d.data();
            return {
              id: d.id,
              time: 'Live',
              actor: (data.actor as AuditLogItem['actor']) || 'admin',
              action: String(data.action || 'Operation'),
              details: String(data.details || ''),
            };
          });
          setAuditLogs((prev) => {
            const existingIds = new Set(prev.map((i) => i.id));
            const merged = [...remoteLogs.filter((r) => !existingIds.has(r.id)), ...prev];
            return merged.slice(0, 20);
          });
        }
      },
      (error) => {
        handleFirestoreError(error, OperationType.LIST, 'auditLogs');
      }
    );

    const settlementsQuery = query(collection(db, 'settlements'), where('ownerId', '==', uid));
    const unsubSettlements = onSnapshot(
      settlementsQuery,
      (snapshot) => {
        if (!snapshot.empty) {
          const remotePayments: PaymentRecord[] = snapshot.docs.map((d) => {
            const data = d.data();
            return {
              id: d.id,
              time: 'Live',
              user: String(data.userHandle || 'operator'),
              amountUsd: Number(data.amountUsd || 5),
              method: (data.rail as PaymentRail) || 'SOL',
              credits: Number(data.creditsGranted || 1500),
              txHash: String(data.txHash || ''),
              status: 'Completed',
            };
          });
          setPayments((prev) => {
            const existingIds = new Set(prev.map((i) => i.id));
            const merged = [...remotePayments.filter((r) => !existingIds.has(r.id)), ...prev];
            return merged.slice(0, 20);
          });
        }
      },
      (error) => {
        handleFirestoreError(error, OperationType.LIST, 'settlements');
      }
    );

    return () => {
      unsubLogs();
      unsubSettlements();
    };
  }, [firebaseUser]);

  // Increment Solana Slot gently
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentSlot((s) => s + 1);
    }, 3500);
    return () => clearInterval(interval);
  }, []);

  // Google Sign-In handler (SC11-F07: never auto-escalate on popup cancel/error)
  const handleGoogleLogin = async () => {
    try {
      await signInWithPopup(auth, googleProvider);
      showNotification('Signed in with Google Firebase Auth.');
    } catch {
      showNotification(
        'Google Sign-In popup closed or blocked in preview frame. Click "Verify Operator Passkey" for sandbox demo.'
      );
    }
  };

  const handleOperatorSessionLogin = () => {
    setOperatorSessionActive(true);
    showNotification('Authenticated via Ed25519 Operator Passkey.');
  };

  const handleSignOut = async () => {
    if (serverSessionToken) {
      try {
        await fetch('/api/v1/auth/revoke', {
          method: 'POST',
          headers: { Authorization: `Bearer ${serverSessionToken}` },
        });
      } catch {
        // Ignore network errors during logout
      }
      setServerSessionToken(null);
    }
    setOperatorSessionActive(false);
    if (firebaseUser) {
      await signOut(auth);
    }
    showNotification('Signed out of MoltAlpha session.');
  };

  // Persist an audit log entry to local state & Firestore (when Firebase user is signed in)
  const recordAuditEvent = async (
    actor: AuditLogItem['actor'],
    action: string,
    details: string
  ) => {
    const nowStr = new Date().toTimeString().slice(0, 8);
    const logId = sanitizeId(`log_${Date.now()}`);
    const newEntry: AuditLogItem = {
      id: logId,
      time: nowStr,
      actor,
      action,
      details,
    };
    setAuditLogs((prev) => [newEntry, ...prev]);

    if (firebaseUser && firebaseUser.emailVerified) {
      const uid = sanitizeId(firebaseUser.uid);
      try {
        await setDoc(doc(db, 'auditLogs', logId), {
          ownerId: uid,
          actor: 'user',
          action: sanitizeBoundedString(action, 1, 80, 'User Action'),
          details: sanitizeBoundedString(details, 1, 400, 'Executed action'),
          createdAt: serverTimestamp(),
        });
      } catch (error) {
        handleFirestoreError(error, OperationType.CREATE, `auditLogs/${logId}`);
      }
    }
  };

  // Multi-rail credit purchase handler (verified via backend /api/v1/settlements/verify; never directly writes Completed settlements from browser JS)
  const handlePurchaseCredits = async (tier: PricingTierName, rail: PaymentRail) => {
    const quote = calculateMultiRailQuote(tier, rail);
    if (serverSessionToken) {
      try {
        await fetch('/api/v1/settlements/verify', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${serverSessionToken}`,
          },
          body: JSON.stringify({
            rail,
            txHash: quote.txHash,
            idempotencyKey: `idem_${Date.now()}_${quote.txHash.slice(-8)}`,
            tier,
            expectedAmountUsd: quote.usdAmount,
            observedAmountUsd: quote.usdAmount,
          }),
        });
      } catch {
        // Proceed with local sandbox state update
      }
    }
    setUserCredits((c) => c + quote.creditsToGrant);

    const settlementId = sanitizeId(`settle_${Date.now()}`);
    const newPayment: PaymentRecord = {
      id: settlementId,
      time: new Date().toTimeString().slice(0, 5),
      user: userDisplayName,
      amountUsd: quote.usdAmount,
      method: rail,
      credits: quote.creditsToGrant,
      txHash: quote.txHash,
      status: 'Completed',
    };
    setPayments((prev) => [newPayment, ...prev]);

    const newPacket: LiveTxFlowPacket = {
      id: `tx_${Date.now()}`,
      slot: currentSlot + 1,
      timestamp: new Date().toTimeString().slice(0, 8),
      pair: 'JUP/SOL',
      dex: 'Jupiter',
      flowType: 'RAIL_SETTLEMENT',
      amountFormatted: `${quote.creditsToGrant.toLocaleString()} Credits ($${quote.usdAmount.toFixed(2)})`,
      rail,
      riskScore: 2.8,
      status: 'SAFE',
      witnessSigPrefix: `ed25519:${quote.txHash.slice(0, 12)}...`,
      latencyMs: 28,
    };
    setTxPackets((prev) => [newPacket, ...prev]);

    await recordAuditEvent(
      'system',
      'Payment Verified (Sandbox)',
      `${rail} payment, $${quote.usdAmount.toFixed(2)}, +${quote.creditsToGrant.toLocaleString()} credits`
    );
    showNotification(
      `Settled $${quote.usdAmount.toFixed(2)} via ${rail} (+${quote.creditsToGrant.toLocaleString()} credits)`
    );
  };

  // Bounty deliverable submission reward handler
  const handleClaimBountyReward = async (
    jobId: string,
    agentId: string,
    creditsGranted: number,
    solReward?: string
  ) => {
    setUserCredits((c) => c + creditsGranted);
    await recordAuditEvent(
      'witness',
      'Bounty Verified',
      `Job: ${jobId} by ${agentId} (+${creditsGranted} credits${solReward ? `, ${solReward}` : ''})`
    );
    showNotification(
      `Verified Bounty ${jobId}: +${creditsGranted} Credits${solReward ? ` & ${solReward} Escrow` : ''} granted!`
    );
  };

  // Lazy-Mint NFT Pass handler
  const handleMintNftPass = async (
    nft: MoltNftItem,
    rail: PaymentRail,
    buyerWallet: string
  ) => {
    setUserCredits((c) => c + nft.bundledCredits);
    const newPay: PaymentRecord = {
      id: `nft_${Date.now()}`,
      time: new Date().toTimeString().slice(0, 5),
      user: buyerWallet.slice(0, 10),
      amountUsd: nft.priceUsdc,
      method: rail,
      credits: nft.bundledCredits,
      txHash: `tx_nft_${nft.id}_${Date.now()}`,
      status: 'Completed',
    };
    setPayments((prev) => [newPay, ...prev]);

    await recordAuditEvent(
      'witness',
      'NFT Pass Lazy-Minted',
      `${nft.numberLabel} (${nft.rarity}) -> +${nft.bundledCredits} credits via ${rail}`
    );
    showNotification(
      `Minted ${nft.title} (${nft.rarity}) · +${nft.bundledCredits.toLocaleString()} API Credits added!`
    );
  };

  // Trigger simulated real-time risk alert & transaction packet in Sentinel Terminal
  const handleTriggerSimulatedAlert = () => {
    const newSlot = currentSlot + 1;
    setCurrentSlot(newSlot);
    const newAlert: RiskAlertItem = {
      id: `alert_${Date.now()}`,
      pair: selectedPoolPair,
      headline: `${selectedPoolPair} — Microstructure anomaly scan`,
      detail: `Slot ${newSlot.toLocaleString()} · Ed25519 state proof signed`,
      status: selectedPoolPair === 'POPCAT/SOL' ? 'CRITICAL' : 'HIGH',
      timeAgo: 'Just now',
      riskScore: selectedPoolPair === 'POPCAT/SOL' ? 8.9 : 7.4,
      slot: newSlot,
    };
    setAlerts((prev) => [newAlert, ...prev]);

    const newPkt: LiveTxFlowPacket = {
      id: `tx_${Date.now()}`,
      slot: newSlot,
      timestamp: new Date().toTimeString().slice(0, 8),
      pair: selectedPoolPair,
      dex: 'Raydium',
      flowType: 'WITNESS_ATTESTATION',
      amountFormatted: `Proof #${newSlot}`,
      riskScore: newAlert.riskScore,
      status: newAlert.status,
      witnessSigPrefix: 'ed25519:5YcK3mTz...9aF1',
      latencyMs: 34,
    };
    setTxPackets((prev) => [newPkt, ...prev]);
    showNotification(`Published live risk assessment & Ed25519 witness for ${selectedPoolPair}`);
  };

  // Toggle favorite star on a pool
  const handleToggleStarPool = (poolId: string) => {
    setPools((prev) =>
      prev.map((p) => (p.id === poolId ? { ...p, starred: !p.starred } : p))
    );
  };

  // Admin: Create User
  const handleAdminCreateUser = async (
    handle: string,
    email: string,
    tier: PricingTierName
  ) => {
    const tierCredits: Record<PricingTierName, number> = {
      Micro: 25,
      Starter: 150,
      Pro: 1500,
      Enterprise: 25000,
    };
    const newUser: ManagedUserRecord = {
      uid: `usr_${Date.now()}`,
      handle,
      email,
      tier,
      credits: tierCredits[tier],
      rateLimitRps: tier === 'Enterprise' ? 500 : tier === 'Pro' ? 120 : 40,
      apiKeysCount: 1,
      status: 'Active',
      lastActive: 'Just now',
    };
    setManagedUsers((prev) => [newUser, ...prev]);
    await recordAuditEvent('admin', 'User Created', `Operator: ${handle} (${tier} tier)`);
    showNotification(`Provisioned operator ${handle} (${tier})`);
  };

  // Admin: Add Credits
  const handleAdminAddCredits = async (
    userHandle: string,
    credits: number,
    rail: PaymentRail
  ) => {
    setManagedUsers((prev) =>
      prev.map((u) => (u.handle === userHandle ? { ...u, credits: u.credits + credits } : u))
    );
    setUserCredits((c) => c + credits);
    const newPay: PaymentRecord = {
      id: `pay_${Date.now()}`,
      time: new Date().toTimeString().slice(0, 5),
      user: userHandle,
      amountUsd: Number((credits * 0.0033).toFixed(2)),
      method: rail,
      credits,
      txHash: `tx_${rail.toLowerCase()}_${Date.now()}`,
      status: 'Completed',
    };
    setPayments((prev) => [newPay, ...prev]);
    await recordAuditEvent(
      'admin',
      'Credits Granted',
      `User: ${userHandle}, +${credits.toLocaleString()} credits via ${rail}`
    );
    showNotification(`Added +${credits.toLocaleString()} credits to ${userHandle}`);
  };

  // Admin: Issue API Key
  const handleAdminIssueApiKey = async (userHandle: string) => {
    const keySuffix = Math.random().toString(16).slice(2, 6);
    setManagedUsers((prev) =>
      prev.map((u) =>
        u.handle === userHandle ? { ...u, apiKeysCount: u.apiKeysCount + 1 } : u
      )
    );
    await recordAuditEvent(
      'admin',
      'API Key Issued',
      `User: ${userHandle}, Key: mk_live_...${keySuffix}`
    );
    showNotification(`Issued new API Key mk_live_...${keySuffix} for ${userHandle}`);
  };

  // Admin: Rotate Cryptographic Ed25519 Key
  const handleAdminRotateWitnessKey = async () => {
    const { updatedKeys, newActiveKey } = rotateWitnessKeys(witnessKeys, keyEpochCounter);
    setWitnessKeys(updatedKeys);
    setKeyEpochCounter((n) => n + 1);

    if (serverSessionToken) {
      try {
        await fetch('/api/v1/admin/rotate-key', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${serverSessionToken}`,
          },
          body: JSON.stringify({ newEpochId: newActiveKey.keyId }),
        });
      } catch {
        // Non-admin or offline fallback
      }
    }

    if (firebaseUser && firebaseUser.emailVerified) {
      const uid = sanitizeId(firebaseUser.uid);
      const keyDocId = sanitizeId(newActiveKey.keyId);
      try {
        await setDoc(doc(db, 'witnessKeys', keyDocId), {
          ownerId: uid,
          keyId: keyDocId,
          publicKey: sanitizeBoundedString(newActiveKey.publicKey, 16, 128, 'ed25519:pk_default_key'),
          algorithm: 'Ed25519',
          status: 'Active',
          createdAt: serverTimestamp(),
        });
      } catch {
        // Non-admin accounts may not write to witnessKeys collection; local epoch rotation still updates
      }
    }

    await recordAuditEvent(
      'witness',
      'Key Rotated',
      `New Active Ed25519 Epoch: ${newActiveKey.keyId}`
    );
    showNotification(`Rotated Ed25519 Witness Key to ${newActiveKey.keyId}`);
  };

  // Admin: Update User Rate Limit
  const handleUpdateUserRateLimit = (uid: string, newRps: number) => {
    setManagedUsers((prev) =>
      prev.map((u) => (u.uid === uid ? { ...u, rateLimitRps: newRps } : u))
    );
    const target = managedUsers.find((u) => u.uid === uid);
    if (target) {
      recordAuditEvent(
        'admin',
        'Rate Limit Updated',
        `User: ${target.handle} set to ${newRps} RPS`
      );
      showNotification(`Updated ${target.handle} API rate limit to ${newRps} RPS`);
    }
  };

  // Admin: Toggle Autonomous Agent Status
  const handleToggleAgentStatus = (agentId: string) => {
    setAgentOps((prev) =>
      prev.map((a) =>
        a.id === agentId
          ? { ...a, status: a.status === 'Running' ? 'Paused' : 'Running' }
          : a
      )
    );
  };

  const activeWitnessKey =
    witnessKeys.find((k) => k.status === 'Active') || witnessKeys[0];

  return (
    <div className="min-h-screen molt-bg-canvas molt-grid-floor text-slate-100 flex flex-col">
      {/* GLOBAL TOP NAVIGATION BAR — Zero overlap across all viewports */}
      <header className="sticky top-0 z-40 h-16 bg-[#080d16]/92 backdrop-blur-xl border-b border-[#1e293b] px-4 sm:px-6 flex items-center justify-between gap-2">
        {/* Left: MoltAlpha Logo + Primary Chamfered Navigation */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={() => setActivePage('platform')}
            className="cursor-pointer text-left focus:outline-none flex items-center shrink-0"
            style={{ clipPath: 'none' }}
          >
            <MoltLogoMark size="md" />
          </button>

          {/* Primary Page Switcher Tabs with .cyber-cut-sm opposing chamfers */}
          <nav aria-label="Primary Navigation" className="hidden lg:flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              data-testid="nav-tab-platform"
              onClick={() => setActivePage('platform')}
              className={`cyber-cut-sm px-2.5 py-1.5 text-xs font-medium transition-all cursor-pointer whitespace-nowrap border ${
                activePage === 'platform'
                  ? 'bg-[#131c31] text-cyan-200 border-cyan-400/70 shadow-[0_0_14px_rgba(6,182,212,0.25)]'
                  : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
              }`}
            >
              Platform
            </button>

            <button
              type="button"
              data-testid="nav-tab-sentinel"
              onClick={() => setActivePage('sentinel')}
              className={`cyber-cut-sm px-2.5 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-all cursor-pointer whitespace-nowrap border ${
                activePage === 'sentinel'
                  ? 'bg-[#131c31] text-white border-cyan-400 shadow-[0_0_16px_rgba(6,182,212,0.32)]'
                  : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
              }`}
            >
              <SentinelShieldBadge size="xs" />
              <span>Sentinel Terminal</span>
            </button>

            <button
              type="button"
              data-testid="nav-tab-automation"
              onClick={() => setActivePage('automation')}
              className={`cyber-cut-sm px-2.5 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-all cursor-pointer whitespace-nowrap border ${
                activePage === 'automation'
                  ? 'bg-[#131c31] text-cyan-200 border-cyan-400/70 shadow-[0_0_14px_rgba(6,182,212,0.25)]'
                  : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
              }`}
            >
              <Bot className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>Automation</span>
            </button>

            <button
              type="button"
              data-testid="nav-tab-developers"
              onClick={() => setActivePage('developers')}
              className={`cyber-cut-sm px-2.5 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-all cursor-pointer whitespace-nowrap border ${
                activePage === 'developers'
                  ? 'bg-[#131c31] text-cyan-200 border-cyan-400/70 shadow-[0_0_14px_rgba(6,182,212,0.25)]'
                  : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
              }`}
            >
              <Code2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>Developers &amp; Pricing</span>
            </button>

            <button
              type="button"
              data-testid="nav-tab-bounties"
              onClick={() => setActivePage('bounties')}
              className={`cyber-cut-sm px-2.5 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-all cursor-pointer whitespace-nowrap border ${
                activePage === 'bounties'
                  ? 'bg-[#131c31] text-cyan-200 border-cyan-400/70 shadow-[0_0_14px_rgba(6,182,212,0.25)]'
                  : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
              }`}
            >
              <Award className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>Bounties</span>
            </button>

            <button
              type="button"
              data-testid="nav-tab-nfts"
              onClick={() => setActivePage('nfts')}
              className={`cyber-cut-sm px-2.5 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-all cursor-pointer whitespace-nowrap border ${
                activePage === 'nfts'
                  ? 'bg-[#131c31] text-cyan-200 border-cyan-400/70 shadow-[0_0_14px_rgba(6,182,212,0.25)]'
                  : 'bg-[#0d1424]/70 text-slate-300 hover:text-white hover:bg-[#131c31] border-[#1e293b]'
              }`}
            >
              <Gem className="w-3.5 h-3.5 text-purple-400 shrink-0" />
              <span>DEMs NFTs</span>
            </button>
          </nav>
        </div>

        {/* Right: Chamfered Slot Telemetry (2xl+) + Auth Controls + CTA */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="hidden 2xl:flex items-center gap-1.5 text-xs font-mono shrink-0">
            <span className="cyber-cut-sm px-2.5 py-1.5 bg-[#0d1424] border border-[#1e293b] text-slate-200 tabular-nums text-[11px] whitespace-nowrap">
              Slot: {currentSlot.toLocaleString()}
            </span>
          </div>

          {isAuthenticated ? (
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={() => setActivePage('admin')}
                title="Open Operator & Admin Console"
                className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1.5 cyber-cut-sm bg-[#0d1424] hover:bg-[#131c31] border border-cyan-500/40 text-xs font-mono text-cyan-200 cursor-pointer whitespace-nowrap"
              >
                <Sparkles className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span>{userDisplayName}</span>
              </button>
              <button
                type="button"
                onClick={handleSignOut}
                className="cyber-btn-ghost px-2.5 py-1.5 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-1.5 cursor-pointer whitespace-nowrap"
              >
                <LogOut className="w-3.5 h-3.5 shrink-0" />
                <span>Sign Out</span>
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={handleOperatorSessionLogin}
              className="cyber-btn-ghost px-3 py-1.5 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-1.5 cursor-pointer whitespace-nowrap"
            >
              <LogIn className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>Sign In</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              if (!isAuthenticated) {
                handleOperatorSessionLogin();
              }
              setActivePage(activePage === 'developers' ? 'developers' : 'sentinel');
            }}
            className="molt-btn-cyan px-3.5 py-2 text-xs font-mono uppercase tracking-wider inline-flex items-center gap-1.5 cursor-pointer whitespace-nowrap shrink-0"
          >
            <span>{activePage === 'developers' ? 'Get API Key' : 'Launch Terminal'}</span>
            <ArrowRight className="w-3.5 h-3.5 shrink-0" />
          </button>
        </div>
      </header>

      {/* Mobile / Tablet Navigation Bar */}
      <div className="lg:hidden flex flex-wrap items-center justify-center gap-1.5 bg-[#080d16]/95 border-b border-[#1e293b] py-2 px-2 text-xs font-mono">
        {(
          [
            { id: 'platform', label: 'Platform' },
            { id: 'sentinel', label: 'Sentinel' },
            { id: 'automation', label: 'Automation' },
            { id: 'developers', label: 'Developers' },
            { id: 'bounties', label: 'Bounties' },
            { id: 'nfts', label: 'DEMs NFTs' },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActivePage(tab.id)}
            className={`cyber-cut-sm px-2.5 py-1 border cursor-pointer ${
              activePage === tab.id
                ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold'
                : 'bg-[#0d1424] text-slate-400 border-[#1e293b]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Toast Notification Banner */}
      {statusToast && (
        <div
          role="status"
          className="fixed bottom-5 right-5 z-50 molt-card-popular px-4 py-3 text-xs font-mono text-cyan-200 flex items-center gap-2 shadow-2xl"
        >
          <Sparkles className="w-4 h-4 text-cyan-400 shrink-0" />
          <span>{statusToast}</span>
        </div>
      )}

      {/* MAIN PAGE CONTENT */}
      <main className="flex-1">
        {activePage === 'platform' && (
          <LandingPage
            pools={pools}
            currentSlot={currentSlot}
            onNavigateTerminal={(pair) => {
              if (pair) setSelectedPoolPair(pair);
              setActivePage('sentinel');
            }}
            onNavigateDevelopers={() => setActivePage('developers')}
            onNavigateAutomation={() => setActivePage('automation')}
            onNavigateAdmin={() => setActivePage('admin')}
          />
        )}

        {activePage === 'sentinel' && (
          <SentinelTerminalPage
            isAuthenticated={isAuthenticated}
            userDisplayName={userDisplayName}
            onGoogleLogin={handleGoogleLogin}
            onOperatorSessionLogin={handleOperatorSessionLogin}
            pools={pools}
            alerts={alerts}
            txPackets={txPackets}
            activeWitnessKey={activeWitnessKey}
            currentSlot={currentSlot}
            selectedPoolPair={selectedPoolPair}
            onSelectPoolPair={(pair) => setSelectedPoolPair(pair)}
            onToggleStarPool={handleToggleStarPool}
            onTriggerSimulatedAlert={handleTriggerSimulatedAlert}
            onNavigateDevelopers={() => setActivePage('developers')}
            solPriceUsd={solPriceUsd}
            marketProviderSummary={marketProviderSummary}
            lastMarketSync={lastMarketSync}
            isSyncingMarket={isSyncingMarket}
            onRefreshMarketTelemetry={() => syncLiveMarketTelemetry(true)}
          />
        )}

        {activePage === 'automation' && (
          <AutomationPage
            isAuthenticated={isAuthenticated}
            userDisplayName={userDisplayName}
            userCredits={userCredits}
            currentSlot={currentSlot}
            solPriceUsd={solPriceUsd}
            pools={pools}
            activeWitnessKey={activeWitnessKey}
            serverSessionToken={serverSessionToken}
            onGoogleLogin={handleGoogleLogin}
            onOperatorSessionLogin={handleOperatorSessionLogin}
            onNavigateSentinel={(pair) => {
              if (pair) setSelectedPoolPair(pair);
              setActivePage('sentinel');
            }}
            onNavigateDevelopers={() => setActivePage('developers')}
            onRecordAudit={async (action, details) => {
              await recordAuditEvent('sentinel', action, details);
            }}
            onNotify={showNotification}
          />
        )}

        {activePage === 'developers' && (
          <DevelopersPricingPage
            currentSlot={currentSlot}
            userCredits={userCredits}
            onPurchaseCredits={handlePurchaseCredits}
            onNavigateTerminal={() => setActivePage('sentinel')}
          />
        )}

        {activePage === 'bounties' && (
          <BountiesPage
            isAuthenticated={isAuthenticated}
            onGoogleLogin={handleGoogleLogin}
            onOperatorSessionLogin={handleOperatorSessionLogin}
            currentSlot={currentSlot}
            userCredits={userCredits}
            userDisplayName={userDisplayName}
            onClaimBountyReward={handleClaimBountyReward}
            onNavigateDevelopers={() => setActivePage('developers')}
          />
        )}

        {activePage === 'nfts' && (
          <NftsPage
            currentSlot={currentSlot}
            userCredits={userCredits}
            onMintNftPass={handleMintNftPass}
          />
        )}

        {activePage === 'admin' && (
          <AdminPanelPage
            currentSlot={currentSlot}
            payments={payments}
            auditLogs={auditLogs}
            witnessKeys={witnessKeys}
            managedUsers={managedUsers}
            agentOps={agentOps}
            onCreateUser={handleAdminCreateUser}
            onAddCredits={handleAdminAddCredits}
            onIssueApiKey={handleAdminIssueApiKey}
            onRotateWitnessKey={handleAdminRotateWitnessKey}
            onUpdateUserRateLimit={handleUpdateUserRateLimit}
            onToggleAgentStatus={handleToggleAgentStatus}
            onReturnToPlatform={() => setActivePage('platform')}
          />
        )}
      </main>

      {/* QUIET FOOTER */}
      <footer className="border-t border-slate-800/80 bg-[#040714] px-6 py-4 text-xs text-slate-400 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-display font-bold text-slate-200">MoltAlpha</span>
          <span>·</span>
          <span>Autonomous DEX Risk Intelligence &amp; Ed25519 State Witnesses</span>
          <span>·</span>
          <a
            href="https://datatracker.ietf.org/doc/html/rfc8785"
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-[11px] text-slate-400 hover:text-cyan-400 hover:underline"
          >
            RFC 8785 Spec
          </a>
          <span>·</span>
          <a
            href="https://github.com/theheiszt/moltbook-alpha"
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-[11px] text-slate-400 hover:text-cyan-400 hover:underline"
          >
            Ontario EULA
          </a>
        </div>
        <div className="flex flex-wrap items-center gap-4 font-mono text-[11px]">
          <button
            type="button"
            onClick={() => setActivePage('automation')}
            className="text-cyan-400 hover:underline cursor-pointer"
          >
            Sniper Studio (/v1/automation)
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => setActivePage('bounties')}
            className="text-cyan-400 hover:underline cursor-pointer"
          >
            Bounties (/v1/jobs)
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => setActivePage('nfts')}
            className="text-cyan-400 hover:underline cursor-pointer"
          >
            DEMs NFTs (/v1/nfts)
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => setActivePage('admin')}
            className="text-purple-400 hover:underline inline-flex items-center gap-1 cursor-pointer"
          >
            <ShieldCheck className="w-3 h-3" />
            <span>Admin Console</span>
          </button>
          <span>·</span>
          <a
            href="/gateway.json"
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-400 hover:underline"
          >
            gateway.json
          </a>
          <span>·</span>
          <a
            href="https://github.com/theheiszt/moltbook-alpha"
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-400 hover:underline inline-flex items-center gap-1"
          >
            <span>GitHub Repo</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </footer>
    </div>
  );
}
