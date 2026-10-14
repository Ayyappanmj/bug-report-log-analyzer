FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && useradd --create-home --uid 10001 app
COPY --chown=app:app . .
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
# Bind to localhost on the host when you run it:  docker run -p 127.0.0.1:8501:8501 --env-file .env <image>
# For a shared/public server add: -e PUBLIC_DEMO=true -e MAX_LOG_SIZE_MB=10   (no local paths, history, Jira or LLM)
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
