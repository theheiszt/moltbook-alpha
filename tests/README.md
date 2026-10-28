# Test Suite for Moltbook Alpha API

This test suite provides automated unit and integration tests for:
- API health and service status (`test_health.py`)
- Authentication, API key validation, and credit deduction (`test_auth.py`)
- Solana on-chain payment verification with synthetic fixtures (`test_payments.py`)
- Transactional SQLite storage, atomic operations, and concurrency (`test_storage.py`)
- Cross-platform configuration and path resolution (`test_config.py`)

All tests execute offline using synthetic mocks and fixtures. No external network requests or real blockchain funds are used.
