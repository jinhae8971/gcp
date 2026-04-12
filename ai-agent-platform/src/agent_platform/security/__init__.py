"""Security hardening primitives (Phase 4).

Modules:
- auth: JWT token issuance and role-based access control
- rate_limit: Token-bucket rate limiting per principal
- budget: Cost budgets and alert thresholds
- sandbox_policy: Execution sandbox profiles (gVisor / Firecracker)
"""
