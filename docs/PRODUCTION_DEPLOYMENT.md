# Career Agency — Production Container and Deployment Baseline

## Container

The rebuild branch includes:
- Python 3.12 slim runtime.
- Gunicorn WSGI server.
- Non-root runtime user.
- 20 MB request-body limit.
- Persistent SQLite database path at /data/career_agency_core.db.
- One Gunicorn worker with eight threads. This is a conservative single-instance SQLite deployment profile, not a horizontal scaling configuration.

## Required runtime secrets and configuration

Set these in the deployment platform's secret/environment manager:
- CAREER_AGENCY_ENV=production
- CAREER_AGENCY_SECRET_KEY: at least 48 high-entropy characters, unique and private.
- CAREER_AGENCY_COOKIE_SECURE=1
- CAREER_AGENCY_PUBLIC_URL: canonical HTTPS URL.
- CAREER_AGENCY_TRUSTED_HOSTS: comma-separated allowed hostnames.
- CAREER_AGENCY_AUTH_EMAIL_ENDPOINT and CAREER_AGENCY_AUTH_EMAIL_API_KEY.
- PAYSTACK_SECRET_KEY when payment checkout is enabled.
- CAREER_AGENCY_LLM_ENDPOINT and CAREER_AGENCY_LLM_API_KEY when AI execution is enabled.

Do not place real secrets in the repository, image layers, frontend code or logs.

## Persistent data

Mount a persistent volume at /data. Without a persistent volume, account, payment, CV and application data can be lost when a container is replaced.

Back up the database with an application-consistent SQLite backup process. Do not copy a live WAL database file without its WAL state. Test restore procedures before accepting real users.

## Build and run

Build:

    docker build -t career-agency:latest .

Run locally with a persistent volume and environment file stored outside the repository:

    docker run --rm -p 8000:8000 --env-file /secure/path/career-agency.env -v career-agency-data:/data career-agency:latest

The service listens on port 8000. Put it behind a TLS-terminating reverse proxy and set trusted hosts correctly.

## Scaling and database limitation

The current core implementation uses SQLite and is configured conservatively for a single application instance. It is not approved for multi-instance horizontal scaling or high write concurrency. The approved architecture specifies PostgreSQL for production scale; a tested PostgreSQL repository/transaction migration is still required before scaling.

## Deployment gates still required

- Verify transactional email sender identity and delivery in production-like staging.
- Complete Paystack sandbox and webhook replay tests.
- Configure AI provider and test output quality, timeouts, quotas and refund behavior.
- Add external monitoring, structured log shipping, alerting, uptime checks and backup/restore drills.
- Complete TLS, DNS, reverse proxy, firewall, secrets rotation and incident response setup.
- Run the full legacy feature regression suite and independent security review.
- Approve legal terms and privacy notice.
