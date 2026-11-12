"""Application services: business logic and transaction boundaries (services commit;
repositories only flush). Present: auth (P-6), dashboard queries (P-9, read-only, never
commits). Later: transaction (sole owner of the state machine), decision engine,
notification and audit."""
