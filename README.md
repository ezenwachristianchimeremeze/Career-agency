# Career Agency

Career Agency is a career-management application for organising job-search activity and related workflows.

## Run locally

1. Use Python 3.10 or newer.
2. Install the dependencies listed in `requirements.txt`.
3. Ensure the repository's `v25_engine.py` module is present alongside `app.py` (the current application imports it).
4. Set a persistent session secret before deployment:

   ```bash
   export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   ```

5. Start the application:

   ```bash
   python app.py
   ```

The server listens on port 5000 by default. Set `PORT` to change it. Debug mode is disabled by default; set `FLASK_DEBUG=true` only for local development.

## Configuration

- `SECRET_KEY` (recommended) or `CAREER_AGENCY_SECRET`: persistent random value used to sign Flask sessions. Keep it private and do not commit it.
- `PORT`: optional HTTP port; defaults to `5000`.
- `FLASK_DEBUG`: optional development flag; defaults to disabled.

For a production deployment, configure secrets in the hosting platform's environment settings, use HTTPS, and run behind a production WSGI server and reverse proxy. Do not commit API keys, database files, user uploads, or local environment files.

## Tests

Install the dependencies, then run:

```bash
pytest -q
```

Test results should be checked in the target environment before treating a release as production-ready.
