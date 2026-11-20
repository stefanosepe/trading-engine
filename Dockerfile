FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY strategies/ strategies/
COPY risk/ risk/
COPY broker/ broker/
COPY journal/ journal/
COPY live/ live/
COPY backtest/ backtest/
COPY data/__init__.py data/feed.py data/generate_sample_data.py data/

# utente non privilegiato: il container non ha bisogno di root
RUN useradd --create-home --uid 10001 trader
USER trader

EXPOSE 8766

CMD ["python", "-m", "journal.run_journal_live", "--host", "0.0.0.0"]
