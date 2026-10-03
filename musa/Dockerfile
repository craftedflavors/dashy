# MUSA WhatsApp Scam Shield bot — build from the musa/ directory:
#   docker build -t musa-whatsapp .
#   docker run -p 8088:8088 --env-file .env -v musa-data:/app/data musa-whatsapp
FROM python:3.12-slim
WORKDIR /app
COPY musa_sentinel ./musa_sentinel
COPY data ./data
ENV PYTHONUNBUFFERED=1 PORT=8088
EXPOSE 8088
RUN useradd --system musa && chown -R musa /app/data
USER musa
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
CMD ["python", "-m", "musa_sentinel", "whatsapp-serve"]
