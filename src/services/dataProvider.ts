import {
  DexPool,
  RiskAlertItem,
  LiveTxFlowPacket,
  WitnessKeyRecord,
  AgentDossierRecord,
  INITIAL_POOLS,
  INITIAL_ALERTS,
  INITIAL_LIVE_TX_PACKETS,
  INITIAL_WITNESS_KEYS,
  lookupAgentDossier,
} from '../utils/cryptoEngine';

export type DataSourceMode = 'SIMULATED_DEMO' | 'AUTHENTICATED_PRODUCTION_API';

export interface DataProvenanceEnvelope<T> {
  mode: DataSourceMode;
  isAuthoritative: boolean;
  scoringEngineVersion: string;
  generatedAtIso: string;
  provenanceLabel: string;
  data: T;
}

export interface IMoltAlphaDataProvider {
  readonly mode: DataSourceMode;
  getSentinelPools(): Promise<DataProvenanceEnvelope<DexPool[]>>;
  getRiskAlerts(): Promise<DataProvenanceEnvelope<RiskAlertItem[]>>;
  getTxFlowStream(): Promise<DataProvenanceEnvelope<LiveTxFlowPacket[]>>;
  getWitnessKeyEpochs(): Promise<DataProvenanceEnvelope<WitnessKeyRecord[]>>;
  getAgentDossier(agentHandle: string): Promise<DataProvenanceEnvelope<AgentDossierRecord>>;
}

/**
 * Development / Demonstration Data Provider.
 * Explicitly tags all Sentinel risk scores, pool telemetry, witness proofs, and
 * Agent Credit Bureau dossiers as SIMULATED_DEMO (isAuthoritative: false) so
 * frontend-generated values can never be mistaken for authoritative production state.
 */
export class SimulatedDemoDataProvider implements IMoltAlphaDataProvider {
  public readonly mode: DataSourceMode = 'SIMULATED_DEMO';
  private readonly engineVersion = 'sentinel-sim-v2.4.0-dev';

  async getSentinelPools(): Promise<DataProvenanceEnvelope<DexPool[]>> {
    return {
      mode: this.mode,
      isAuthoritative: false,
      scoringEngineVersion: this.engineVersion,
      generatedAtIso: new Date().toISOString(),
      provenanceLabel: 'SIMULATED DEMO · DEV SANDBOX',
      data: INITIAL_POOLS,
    };
  }

  async getRiskAlerts(): Promise<DataProvenanceEnvelope<RiskAlertItem[]>> {
    return {
      mode: this.mode,
      isAuthoritative: false,
      scoringEngineVersion: this.engineVersion,
      generatedAtIso: new Date().toISOString(),
      provenanceLabel: 'SIMULATED DEMO · DEV SANDBOX',
      data: INITIAL_ALERTS,
    };
  }

  async getTxFlowStream(): Promise<DataProvenanceEnvelope<LiveTxFlowPacket[]>> {
    return {
      mode: this.mode,
      isAuthoritative: false,
      scoringEngineVersion: this.engineVersion,
      generatedAtIso: new Date().toISOString(),
      provenanceLabel: 'SIMULATED DEMO · DEV SANDBOX',
      data: INITIAL_LIVE_TX_PACKETS,
    };
  }

  async getWitnessKeyEpochs(): Promise<DataProvenanceEnvelope<WitnessKeyRecord[]>> {
    return {
      mode: this.mode,
      isAuthoritative: false,
      scoringEngineVersion: this.engineVersion,
      generatedAtIso: new Date().toISOString(),
      provenanceLabel: 'SIMULATED DEMO · DEV SANDBOX',
      data: INITIAL_WITNESS_KEYS,
    };
  }

  async getAgentDossier(agentHandle: string): Promise<DataProvenanceEnvelope<AgentDossierRecord>> {
    return {
      mode: this.mode,
      isAuthoritative: false,
      scoringEngineVersion: this.engineVersion,
      generatedAtIso: new Date().toISOString(),
      provenanceLabel: 'SIMULATED DEMO · OFFLINE SNAPSHOT',
      data: lookupAgentDossier(agentHandle),
    };
  }
}

export const defaultDataProvider: IMoltAlphaDataProvider = new SimulatedDemoDataProvider();
