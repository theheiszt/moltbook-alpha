import { test, describe } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";

import {
  decodeBase58,
  encodeBase58,
  canonicalizeJson,
  verifyEd25519Signature,
  verifyWitnessOffline,
  MoltbookIntelClient,
  MoltbookApiError,
} from "../dist/index.js";

describe("@moltbook/intel-sdk — TypeScript / Node SDK Tests", () => {
  test("Base58 encode and decode roundtrip", () => {
    const raw = Buffer.from("Hello Moltbook Alpha On-Chain Intel!", "utf-8");
    const encoded = encodeBase58(raw);
    assert.ok(typeof encoded === "string");
    assert.ok(encoded.length > 0);

    const decoded = decodeBase58(encoded);
    assert.deepEqual(Buffer.from(decoded), raw);
  });

  test("RFC 8785 JSON canonicalization sorts keys and removes whitespace", () => {
    const obj = {
      zeta: 1,
      alpha: "test",
      beta: [3, 2, 1],
      nested: { delta: true, gamma: null },
    };
    const canonical = canonicalizeJson(obj);
    assert.equal(
      canonical,
      '{"alpha":"test","beta":[3,2,1],"nested":{"delta":true,"gamma":null},"zeta":1}'
    );
  });

  test("Ed25519 digital signature verification offline", () => {
    const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
    const rawPub = publicKey.export({ type: "spki", format: "der" }).subarray(12);
    const pubBase58 = encodeBase58(rawPub);

    const message = "Moltbook_State_Witness_Assertion_2026";
    const sig = crypto.sign(null, Buffer.from(message, "utf-8"), privateKey);
    const sigBase58 = encodeBase58(sig);

    // Verify valid signature
    const isValid = verifyEd25519Signature(message, sigBase58, pubBase58);
    assert.equal(isValid, true);

    // Verify tampered message fails
    const isTampered = verifyEd25519Signature(message + "_tampered", sigBase58, pubBase58);
    assert.equal(isTampered, false);
  });

  test("Full offline State Witness verification", () => {
    const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
    const rawPub = publicKey.export({ type: "spki", format: "der" }).subarray(12);
    const pubBase58 = encodeBase58(rawPub);

    const witnessPayload = {
      witness_id: "wit_test_9999",
      action: "QUOTA_DEDUCTED",
      actor: "test_agent",
      credit_delta: -1,
      post_balance: 49,
      timestamp: "2026-10-18T16:00:00Z",
      request_id: "req_test_001",
      environmental_anchor: { block_hash: "0x123abc" },
    };

    const canonicalStr = canonicalizeJson(witnessPayload);
    const sig = crypto.sign(null, Buffer.from(canonicalStr, "utf-8"), privateKey);
    const sigBase58 = encodeBase58(sig);

    const fullWitness = {
      ...witnessPayload,
      public_key_base58: pubBase58,
      signature_base58: sigBase58,
    };

    const result = verifyWitnessOffline(fullWitness);
    assert.equal(result.valid, true);
    assert.equal(result.witness_id, "wit_test_9999");
  });

  test("MoltbookIntelClient initialization and error mapping", () => {
    const client = new MoltbookIntelClient({
      baseUrl: "https://api.moltbook.test",
      apiKey: "molt_intel_api_testkey123",
      timeoutMs: 5000,
      maxRetries: 2,
    });

    assert.equal(client.baseUrl, "https://api.moltbook.test");
    assert.equal(client.apiKey, "molt_intel_api_testkey123");
    assert.equal(client.maxRetries, 2);

    const err = new MoltbookApiError(
      {
        error: {
          code: "CHALLENGE_ALREADY_CONSUMED",
          message: "This challenge can no longer be used.",
          retryable: false,
          outcome: "not_committed",
          state_effect: "challenge_consumed",
          recovery: {
            action: "request_new_challenge",
          },
          request_id: "req_ch_001",
        },
        code: "CHALLENGE_ALREADY_CONSUMED",
        message: "This challenge can no longer be used.",
        retryable: false,
        outcome: "not_committed",
        state_effect: "challenge_consumed",
        recovery: {
          action: "request_new_challenge",
        },
        request_id: "req_ch_001",
      },
      410
    );
    assert.equal(err.code, "CHALLENGE_ALREADY_CONSUMED");
    assert.equal(err.statusCode, 410);
    assert.equal(err.retryable, false);
    assert.equal(err.requestId, "req_ch_001");
    assert.equal(err.outcome, "not_committed");
    assert.equal(err.stateEffect, "challenge_consumed");
    assert.equal(err.recoveryAction, "request_new_challenge");
    assert.equal(err.recovery?.action, "request_new_challenge");
  });
});
