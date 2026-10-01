# Production readiness and scale plan

Voca currently targets a small, self-hosted deployment: one Python process, Python's threaded HTTP server, SQLite, one background worker, and process-local rate-limit counters. The Docker example binds its port to loopback for a reverse proxy. Do not add multiple application replicas while using the current SQLite job coordination and in-memory limits.

## Before onboarding public customers

- Deploy behind a maintained HTTPS reverse proxy. Restrict direct service access, set request-size/time limits, and ensure the proxy overwrites forwarded-IP headers before enabling `VOCA_TRUST_LOCAL_PROXY`.
- Separate operator access by account and site. Add role checks, MFA or an identity provider, audit events for key changes, connection changes, exports and deletion, plus recovery controls for administrator access.
- Add per-site answer quotas and spend alerts. Rate limits are currently per process; visitors can share one public network address, and limits reset on restart.
- Define customer terms and privacy disclosures. Website text, visitor questions, conversation history and retrieved excerpts are sent to the selected AI provider. Publish provider/retention details and data processing terms before onboarding external businesses.
- Add database backup automation, encrypted off-host copies, and a tested restore procedure. Keep the encryption key separate from the database backup and document rotation/recovery.
- Test provider outage handling, queue recovery after process restart, crawler limits, deletion, tenant isolation and account revocation on staging.

## Before horizontal scaling

1. Move tenant settings, sites, documents, jobs and daily usage data to PostgreSQL with migrations and tenant-scoped constraints.
2. Move ingestion and embedding work to a durable queue with leases, retries, dead-letter handling and idempotency. Run independent worker processes.
3. Replace process-local rate limiting with a shared store and enforce per-site budgets across instances.
4. Use a production application server with health/readiness checks, graceful shutdown, bounded concurrency and structured secret-free logs.
5. Benchmark representative import sizes and question traffic. Tune database indexes and move embeddings to a vector index only when measured query latency or storage warrants it.
6. Add alerting for error rates, queue age, latency, provider usage, sync freshness, disk growth and backup failures.

## Release checks for platform integrations

The Shopify and Webflow implementations still require developer apps and sandbox sites for full testing. For each platform, verify install, consent scopes, domain matching, first import, incremental updates, rate-limit retries, token refresh, widget appearance, app uninstall, data deletion, and clean reinstall. Verify Webflow changes in a staging site and publish only after review. Keep real app credentials in a secret manager; never put them in this repository.

## Content and answer quality evaluation

Before enabling a site for visitors, create a private set of representative questions with expected answers, source URLs, languages, and out-of-scope cases. Run the set after content changes and model/provider changes. Track citation correctness, refusal quality, stale prices/policies, latency and cost. The retrieval cutoff is configurable because a useful value depends on the content and embedding model; calibrate it using this evaluation set instead of assuming the default is universally correct.
