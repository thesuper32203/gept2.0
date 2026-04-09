FROM python:3.12-slim
LABEL authors="Thesu"

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY pyproject.toml poetry.lock* ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --only main --no-root

# Copy source code
COPY packages/collector ./packages/collector

# Run the collector entry point
CMD ["python", "-m", "packages.collector.main"]