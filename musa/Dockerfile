# MUSA Corridor platform: website + business portal + admin + WhatsApp bot + background agents.
#   docker build -t musa .
#   docker run -d -p 8080:8080 --env-file .env -v musa-data:/data musa
FROM python:3.12-slim
WORKDIR /app
COPY musa_sentinel ./musa_sentinel
COPY musa_platform ./musa_platform
COPY data ./data
# Optional: Claude-powered concierge answers (falls back to rules without it)
RUN pip install --no-cache-dir "anthropic>=1,<2" || echo "anthropic SDK not installed; concierge runs in rules mode"
ENV PYTHONUNBUFFERED=1 PORT=8080 MUSA_DB=/data/musa.db MUSA_LEADS_FILE=/data/leads.jsonl
RUN useradd --system musa && mkdir -p /data && chown -R musa /data
USER musa
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
CMD ["python", "-m", "musa_platform", "serve"]
