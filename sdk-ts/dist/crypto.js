import crypto from "node:crypto";

const BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const BASE58_MAP = {};
for (let i = 0; i < BASE58_ALPHABET.length; i++) {
  BASE58_MAP[BASE58_ALPHABET[i]] = i;
}

export function decodeBase58(str) {
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

  for (let i = 0; i < str.length && str[i] === "1"; i++) {
    bytes.push(0);
  }

  return new Uint8Array(bytes.reverse());
}

export function encodeBase58(bytes) {
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

export function canonicalizeJson(obj) {
  if (obj === null || typeof obj !== "object") {
    return JSON.stringify(obj);
  }

  if (Array.isArray(obj)) {
    const items = obj.map((item) => canonicalizeJson(item));
    return `[${items.join(",")}]`;
  }

  const sortedKeys = Object.keys(obj).sort();
  const entries = [];
  for (const k of sortedKeys) {
    const val = obj[k];
    if (val !== undefined && typeof val !== "function") {
      entries.push(`${JSON.stringify(k)}:${canonicalizeJson(val)}`);
    }
  }
  return `{${entries.join(",")}}`;
}

function createEd25519SpkiDer(rawPubKey) {
  if (rawPubKey.length !== 32) {
    throw new Error(`Expected 32-byte Ed25519 public key, got ${rawPubKey.length}`);
  }
  const prefix = Buffer.from("302a300506032b6570032100", "hex");
  return Buffer.concat([prefix, Buffer.from(rawPubKey)]);
}

export function verifyEd25519Signature(data, signatureBase58, publicKeyBase58) {
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

export function verifyWitnessOffline(witness, publicKeyBase58) {
  try {
    const pubKey = publicKeyBase58 || witness.public_key_base58;
    const sigBase58 = witness.signature_base58;

    if (!pubKey || !sigBase58) {
      return { valid: false, error: "Missing public key or signature in witness payload" };
    }

    const toCanonical = {};
    for (const [k, v] of Object.entries(witness)) {
      if (k !== "signature_base58" && k !== "public_key_base58" && k !== "verified" && k !== "valid") {
        toCanonical[k] = v;
      }
    }

    const canonicalStr = canonicalizeJson(toCanonical);
    const isValid = verifyEd25519Signature(canonicalStr, sigBase58, pubKey);

    return {
      valid: isValid,
      witness_id: witness.witness_id,
      error: isValid ? undefined : "Signature verification failed",
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { valid: false, error: `Verification exception: ${msg}` };
  }
}
