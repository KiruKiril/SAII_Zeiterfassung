# --- Build-Stage: Abhaengigkeiten getrennt, damit das Runtime-Image schlank bleibt
FROM python:3.12-slim AS build
WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install/out -r requirements.txt

# --- Runtime-Stage
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

# Unprivilegierter Benutzer - der Container laeuft nie als root
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin zeiterfassung \
 && mkdir -p /data && chown 10001:10001 /data

COPY --from=build /install/out /usr/local
WORKDIR /app
COPY --chown=10001:10001 app.py hashpw.py ./

USER 10001:10001
EXPOSE 8080
VOLUME ["/data"]

# Gunicorn statt Flask-Entwicklungsserver; 2 Worker, Requests laufen kurz.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
