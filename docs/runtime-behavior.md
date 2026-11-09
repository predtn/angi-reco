# Runtime behavior

What the service does in the background and how its write endpoints behave. Algorithm and formulas: [Recommendation_System_Design_Ver1.1.docx](Recommendation_System_Design_Ver1.1.docx).

## Dish vectors

RECO-01 answers at once with the dish `pending`; its vector is generated right after in a background task. A loop started with the app retries `pending` / `failed` dishes every 5 minutes, at most 5 times per content (`attempt_count`), so a dish still `failed` after 5 tries keeps its `last_error` for inspection (Design §2.4).

The backend's outbox worker sends every dish change from then on. Dishes that were already in `core.dishes` before reco first ran can be sent once with the backfill script (rerunning is harmless):

```bash
python scripts/backfill_dishes.py --core-database-url postgresql://angi_backend:backend_dev@localhost:5432/angi --reco-url http://127.0.0.1:8000
```

The script is the only code that reads schema `core`, with the backend role; the service never does.

## Feedback

RECO-04 (`POST /feedback`, sent by the outbox worker for each like / dislike) applies Design §5.2 in one transaction that locks the user's row:

- A known `event_uuid` answers `duplicate` and changes nothing, also when the same event arrives twice at once.
- A dish reco never received is 404 `DISH_NOT_FOUND` (the worker marks the event dead). A dish whose vector is `pending` or `failed` is 503 `DISH_VECTOR_NOT_READY` with `Retry-After: 60`, so the worker retries; the user's later events wait behind it. A deactivated dish that has a vector still counts.
- `occurred_at` needs a time zone: the latest `occurred_at` is the vote counted in `dish_stats`. An older event that arrives late still adds to r, n, the user vector and m.

## Log retention

RECO-05 logs every candidate it ranks in `recommendation_items` (up to 2000 rows per call). A background task (`app/services/log_retention.py`, started with the app, every hour) deletes the rows that were not returned to the user (`is_returned = false`) once their log is older than 30 days, in batches of 5000 per transaction. `recommendation_logs` and returned items are kept: they are what the evaluation (Design §6.2: like-rate of top-k, replay) reads.

## Algorithm configuration

Every recommendation uses the one row of `algorithm_configs` with `is_active = true` and logs its `config_version`. Migrations add configurations; they never switch the active one silently.

| `config_version` | Parameters | State |
|---|---|---|
| 1 | Design §3.5, γ = 0 (no exploration) | active |
| 2 | same as 1, γ = 0.1 (UCB, Design §3.4) | added inactive (migration 0003) |

UCB only changes the ranking once the app reports impressions (IMP-01 → RECO-06): until then N_total = 0 and every Exploration score is 0. Switch versions in one transaction, the old one off first (the unique index on `is_active` is checked row by row):

```sql
BEGIN;
UPDATE recommendation.algorithm_configs SET is_active = false WHERE is_active;
UPDATE recommendation.algorithm_configs SET is_active = true WHERE config_version = 2;  -- 1 to go back
COMMIT;
```

The backend caches a ranked DISH-01 list for 30 minutes, so lists ranked with the previous version can still be paged for that long.
