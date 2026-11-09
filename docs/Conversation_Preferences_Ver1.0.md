# Conversation preferences, version 1

This extension preserves ontology version 1, scoring formulas and cold-start.

- Internal `GET /users/{user_id}/preferences` requires X-Api-Key and returns user_id,
  ontology_version, nullable vec and nullable updated_at. Missing rows are not inserted.
- RECO-05 accepts vector_source (profile by default, or conversation) and nullable
  user_vector_override. A conversation requires user_id. Its 12 finite values replace
  only the request vector. Inherited feedback components may be negative or above 1.
  Profile requests cannot override. Zero becomes null; conversation null does not fall
  back to the profile. Responses echo the source and logs snapshot the actual vector.
- Session targets and inheritance are managed by the backend, never persisted to the
  long-term profile. m, implicit, Wilson and exploration remain based on existing data.
- RECO-06 accepts an internal positive agent_proposal_id. For conversation-source
  requests it is required; missing references return 409 AGENT_COMMIT_REQUIRED.
  Backend queues all committed dishes in a transactional outbox and sends after commit.
  The public backend impression DTO never forwards a client commit reference.
- First impressions store the proposal reference; repeated (request_id,dish_id) pairs
  do not increment counters again. Impressions never increment m or update implicit.
- Migration 0004 adds recommendation_logs.vector_source/effective_vector and
  recommendation_items.agent_proposal_id (soft reference, no cross-schema FK).
- Apply reco migration and deploy reco before backend. Old callers keep profile behavior;
  backend verifies source support and uses rating fallback if an old reco ignores it.
