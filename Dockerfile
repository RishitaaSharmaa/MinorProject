FROM python:3.11-slim

WORKDIR /workspace
COPY pyproject.toml ./
COPY app ./app
COPY llm ./llm
COPY scripts ./scripts
COPY data_generator/output ./data_generator/output
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]