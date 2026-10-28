/**
 * Moltbook Alpha TypeScript SDK — Cryptographic Verification.
 * Implements pure Base58 decoding, RFC 8785 JSON Canonicalization (JCS),
 * and offline Ed25519 digital signature verification via Node.js crypto.
 */

import crypto from "node:crypto";

const BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const BASE58_MAP: Record<string, number> = {};
for (let i = 0; i < BASE58_ALPHABET.length; i++) {
  BASE58_MAP[BASE58_ALPHABET[i]] = i;
}

/**
 * Decodes a Base58 string into a Uint8Array.
 */
export function decodeBase58(str: string): Uint8Array {
  if (!str || typeof str !== "string") {
    return new Uint8Array(0);
  }

  const bytes = [0];
  for (let i = 0; i < str.length; i++) {
    const char = str[i];
    const val = BASE58_MAP[char];
    if (val === undefined) {
      throw new Error(`Invalid Base58 character: ${char}`);
    }

    let carry = val;
    for (let j = 0; j < bytes.length; j++) {
      carry += bytes[j] * 58;
      bytes[j] = carry & 0xff;
      carry >>= 8;
    }
    while (carry > 0) {
      bytes.push(carry & 0xff);
      carry >>= 8;
    }
  }

  // Handle leading zeros
  for (let i = 0; i < str.length && str[i] === "1"; i++) {
    bytes.push(0);
  }

  return new Uint8Array(bytes.reverse());
}

/**
 * Encodes a Uint8Array to a Base58 string.
 */
export function encodeBase58(bytes: Uint8Array): string {
  const digits = [0];
  for (let i = 0; i < bytes.length; i++) {
    let carry = bytes[i];
    for (let j = 0; j < digits.length; j++) {
      carry += digits[j] << 8;
      digits[j] = carry % 58;
      carry = (carry / 58) | 0;
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = (carry / 58) | 0;
    }
  }

  let str = "";
  for (let i = 0; i < bytes.length && bytes[i] === 0; i++) {
    str += "1";
  }
  for (let i = digits.length - 1; i >= 0; i--) {
    str += BASE58_ALPHABET[digits[i]];
  }
  return str;
}

/**
 * Produces deterministic canonical JSON string per RFC 8785.
 */
export function canonicalizeJson(obj: unknown): string {
  if (obj === null || typeof obj !== "object") {
    return JSON.stringify(obj);
  }

  if (Array.isArray(obj)) {
    const items = obj.map((item) => canonicalizeJson(item));
    return `[${items.join(",")}]`;
  }

  const sortedKeys = Object.keys(obj as Record<string, unknown>).sort();
  const entries: string[] = [];
  for (const k of sortedKeys) {
    const val = (obj as Record<string, unknown>)[k];
    if (val !== undefined && typeof val !== "function") {
      entries.push(`${JSON.stringify(k)}:${canonicalizeJson(val)}`);
    }
  }
  return `{${entries.join(",")}}`;
}

/**
 * Wraps a raw 32-byte Ed25519 public key in standard SPKI DER format.
 * Header: 302a300506032b6570032100 (12 bytes)
 */
function createEd25519SpkiDer(rawPubKey: Uint8Array): Buffer {
  if (rawPubKey.length !== 32) {
    throw new Error(`Expected 32-byte Ed25519 public key, got ${rawPubKey.length}`);
  }
  const prefix = Buffer.from("302a300506032b6570032100", "hex");
  return Buffer.concat([prefix, Buffer.from(rawPubKey)]);
}

/**
 * Verifies an Ed25519 signature over arbitrary data offline.
 */
export function verifyEd25519Signature(
  data: Uint8Array | string,
  signatureBase58: string,
  publicKeyBase58: string
): boolean {
  try {
    const rawPub = decodeBase58(publicKeyBase58);
    const rawSig = decodeBase58(signatureBase58);

    if (rawPub.length !== 32 || rawSig.length !== 64) {
      return false;
    }

    const spkiDer = createEd25519SpkiDer(rawPub);
    const pubKeyObj = crypto.createPublicKey({
      key: spkiDer,
      format: "der",
      type: "spki",
    });

    const dataBuffer = typeof data === "string" ? Buffer.from(data, "utf-8") : Buffer.from(data);
    return crypto.verify(null, dataBuffer, pubKeyObj, Buffer.from(rawSig));
  } catch {
    return false;
  }
}

/**
 * Performs complete offline verification of a Moltbook Alpha State Witness.
 */
export function verifyWitnessOffline(
  witness: Record<string, unknown>,
  publicKeyBase58?: string
): { valid: boolean; witness_id?: string; error?: string } {
  try {
    const pubKey = publicKeyBase58 || (witness.public_key_base58 as string);
    const sigBase58 = witness.signature_base58 as string;

    if (!pubKey || !sigBase58) {
      return { valid: false, error: "Missing public key or signature in witness payload" };
    }

    // Clone and strip non-canonical witness fields
    const toCanonical: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(witness)) {
      if (k !== "signature_base58" && k !== "public_key_base58" && k !== "verified" && k !== "valid") {
        toCanonical[k] = v;
      }
    }

    const canonicalStr = canonicalizeJson(toCanonical);
    const isValid = verifyEd25519Signature(canonicalStr, sigBase58, pubKey);

    return {
      valid: isValid,
      witness_id: witness.witness_id as string,
      error: isValid ? undefined : "Signature verification failed",
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return { valid: false, error: `Verification exception: ${msg}` };
  }
}
