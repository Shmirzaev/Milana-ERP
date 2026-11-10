# Pricing schema0156 recovery candidate

User explicitly authorized deployment of the variant pricing workflow and a
separate Excel price import with USD0.30 added once. Initial verified production:
blue20261110_070607, manifest7bf0a59c139cf8a46fc6af7a3a0c5457795ba7b1de7fe57e70c76b31481fac32,
application843adaf3bda1b1f2d234e68b6763bbc649d3b72a, schema0155_eco_gate_merge.
Base clone_main8ae2429cbd39c5f33ba17aab75d36949180e0c19 has documentation only
after that application. Both live source manifests match; retained rollback is
green20261109_163130. No production migration or price mutation has run.

The strict startup head check makes an old unmodified image unsuitable at0156.
Metadata alone is insufficient: legacy pricing routes could mutate managed
approvals or publish drafts. Recovery preserves ordinary application behavior,
adds the exact reviewed0156migration and blocks all /api/price-calculation HTTP
routes with503 in production. Sales continues reading existing attached variant
prices; saved orders and all manufacturing stages remain independent. New pricing
tasks pause during recovery and require preview-first reconciliation afterward.
The final feature release removes this guard wiring and includes this commit in
its ancestry. No runtime feature flag or schema/security bypass is introduced.

The inherited create-user test collection error is repaired by explicitly declaring
its already-indirect creation_database fixture argument; no assertion/case removed.
Native collection27 succeeds;18 focused recovery/create-user SQLite tests pass,
9 PostgreSQL cases deliberately deselected in that local focused invocation.
Ruff and single Alembic head0156 pass. Reviewer /root/pricing_review independently
approved all five code/migration/test files; working-source aggregate SHA256
9881d66bd4a0a26e53f6f4c862a68b0b40cf33fa44b0626b985d4b1e47b6274e.

Required before promotion: full exact-source CI/security scan/publication, immutable
production-mode default CMD, two fresh workers, child replacement, restart,
health/readiness and denial of pricing operations on managed draft/approved data.
Keep STARTUP_SCHEMA_SYNC and RUN_SEED_ON_STARTUP disabled. Back up PostgreSQL before
0156 migration, then activate recovery and final through DEPLOYMENT.md's two phases.
Keep the running compatible recovery slot, source/image identities and previous
price evidence. Application rollback never reverses imported business prices.
AI source approval is not human/QA-master acceptance or a production deployment.
