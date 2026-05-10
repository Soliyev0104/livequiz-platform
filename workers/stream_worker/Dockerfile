# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd -r app && useradd --no-log-init -r -g app app
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY . /app
RUN chown -R app:app /app
USER app
CMD ["python", "-m", "app.main"]
