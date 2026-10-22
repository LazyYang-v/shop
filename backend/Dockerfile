FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir . alembic

EXPOSE 8000
CMD ["uvicorn", "shop_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
