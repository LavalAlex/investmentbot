FROM python:3.11-slim

WORKDIR /app

# Install deps first — cached layer unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source only — no .env, no data/, no logs/, no venv/
COPY config.py fetch_history.py paper_engine_breakout.py reset_paper_logs.py ./
COPY core/    core/
COPY backtest/ backtest/
COPY api/     api/

# Runtime directories — will be bind-mounted on GCE for persistence
RUN mkdir -p logs data

# Non-root user
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Cloud Run injects $PORT; GCE default is 8080
ENV PORT=8080
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
