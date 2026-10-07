# angi-reco

Recommendation service (FastAPI) for the ANGI capstone project. The backend calls it over HTTP; its endpoints are in sheet "Reco API (nội bộ)" of `ANGI_API_Design_Ver1.7`, its tables in schema `recommendation` of `ANGI_Data_Dictionary_Ver1.1`.

## Development

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request to `dev` or `main` and on every push to them, on Python 3.12. A pull request can be merged only when the `lint-test` check is green.

Run the same checks locally before pushing:

```bash
ruff check .            # lint (ruff check --fix . fixes most issues)
ruff format --check .   # format (ruff format . rewrites the files)
pytest
```
