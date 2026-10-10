FROM python:3.11-slim

WORKDIR /workspace
COPY pyproject.toml ./
COPY app ./app
COPY llm ./llm
COPY scripts ./scripts
COPY data_generator/output ./data_generator/output
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
RUN pip install --no-cache-dir . \
    && sed -i 's/\r$//' docker-entrypoint.sh \
    && chmod +x docker-entrypoint.sh

EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
