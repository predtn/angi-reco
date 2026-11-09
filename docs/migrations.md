# Migrations


Schema `recommendation` changes only through Alembic (`angi-backend/.agents/commit_guide.md` §4).

```bash
# after changing app/models (pull dev first)
alembic revision --autogenerate --rev-id 0002 -m "add something"
# review the file, then
alembic upgrade head
alembic check            # must print "No new upgrade operations detected."
```

- Number revisions in order (`0002`, `0003`, ...). If two pull requests create the same number, the one merged second regenerates its revision on the new head.
- Autogenerate does not see data, raw SQL or extensions: seed rows and `CREATE EXTENSION` are written by hand (see `0001`).
- `vector` must already exist in schema `public`, because role `angi_reco` cannot create extensions. The backend's init script installs it locally; on Render it is created once with the database's admin user when the environment is set up.

## Conversation preferences (migration 0004)

Conversation taste vectors and commit-only Agent impressions are documented in
[Conversation Preferences v1](Conversation_Preferences_Ver1.0.md).
Deploy reco migration `0004` and this service before the matching backend migration/service.
Existing recommendation requests continue to use the long-term profile by default.
