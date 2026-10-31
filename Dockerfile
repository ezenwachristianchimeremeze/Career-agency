FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    FLASK_DEBUG=0 \
    CAREER_AGENCY_ENV=production \
    CAREER_AGENCY_CORE_DB=/data/career_agency_core.db

WORKDIR /app

RUN addgroup --system career && adduser --system --ingroup career --home /app career

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=career:career . .

RUN mkdir -p /data && chown -R career:career /data /app

USER career

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
