# MoltAlpha Security Specification (Phase 0 TDD)

## 1. Data Invariants
1. **Global Default-Deny**: All paths not explicitly matched in `/databases/{database}/documents` are strictly rejected (`allow read, write: if false;`).
2. **Verified Identity & Admin Isolation**: All writes require `request.auth != null` and `request.auth.token.email_verified == true`. Admin privilege is determined strictly via `exists(/databases/$(database)/documents/admins/$(request.auth.uid))` or the bootstrapped verified runtime owner (`request.auth.token.email == 'syntheticinquiry@gmail.com' && request.auth.token.email_verified == true`).
3. **PII Split Collection Isolation**: User email PII is isolated in `/users/{userId}/private/{docId}` where `{docId}` must be `'info'` and parent `/users/{userId}` must exist (Master Gate). Only the owner or verified admin can read/create it.
4. **Strict Validation Blueprints & Anti-Update-Gap**: Every `create` and `update` invokes `isValid[Entity](incoming())`, enforcing exact key allowlists (`hasAll` + `hasOnly`), bounded string lengths, regex ID checks (`^[a-zA-Z0-9_\-]+$`), and server timestamps (`request.time`).
5. **Secure List Queries**: Every `allow list` rule enforces `resource.data.ownerId == request.auth.uid || isAdmin()` without calling `get()` or `exists()` inside `list`.
6. **Terminal State Locking**: Once a `PaymentSettlement` has `status == 'Completed'` or a `CryptographicKeyEpoch` has `status == 'Revoked'`, no further updates are permitted (except admin override where applicable).

## 2. The "Dirty Dozen" Adversarial Payloads
1. **Payload 1 (Shadow Field Injection)**: `POST /users/u1` with `{ ..., "isAdmin": true }` -> Rejected by `hasOnly()`.
2. **Payload 2 (Unverified Email Spoofing)**: Auth token with `email: "syntheticinquiry@gmail.com"`, `email_verified: false` -> Rejected by `isVerifiedUser()` / `isAdmin()`.
3. **Payload 3 (ID Poisoning / 2KB String)**: `POST /auditLogs/<2000-char-id>` -> Rejected by `isValidId()`.
4. **Payload 4 (Cross-User Identity Spoofing)**: `POST /settlements/s1` with `ownerId: "victim_uid"` while signed in as `"attacker_uid"` -> Rejected by `incoming().ownerId == request.auth.uid`.
5. **Payload 5 (Forged Client Timestamp)**: `POST /auditLogs/l1` with `createdAt: Timestamp(2020, 1, 1)` -> Rejected by `incoming().createdAt == request.time`.
6. **Payload 6 (PII Blanket Read)**: Authenticated user `u2` calls `GET /users/u1/private/info` -> Rejected by `isOwner(userId) || isAdmin()`.
7. **Payload 7 (Orphaned Subcollection Write)**: `POST /users/u1/private/info` when `/users/u1` does not exist -> Rejected by Master Gate `exists(/databases/$(database)/documents/users/$(userId))`.
8. **Payload 8 (Update-Gap Value Poisoning)**: `PATCH /users/u1` updating `displayName` to a 5,000-character string -> Rejected by `isValidUserProfile(incoming())` inside `allow update`.
9. **Payload 9 (Immortal Field Mutation)**: `PATCH /users/u1` attempting to mutate `createdAt` or `uid` -> Rejected by `affectedKeys().hasOnly(...)` and `incoming().createdAt == existing().createdAt`.
10. **Payload 10 (Terminal State Mutation)**: `PATCH /settlements/s1` when `existing().status == 'Completed'` -> Rejected by terminal state lock.
11. **Payload 11 (Unauthorized List Scraping)**: `LIST /auditLogs` without filtering by `ownerId == request.auth.uid` as non-admin -> Rejected by `resource.data.ownerId == request.auth.uid`.
12. **Payload 12 (Invalid Enum Injection)**: `POST /settlements/s1` with `rail: "DOGE"` -> Rejected by `incoming().rail in ['SOL', 'USDC', 'Nano']`.
