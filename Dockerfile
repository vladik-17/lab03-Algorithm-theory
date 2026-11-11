FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN sed -e '/^PySide6/d' -e '/^pytest/d' requirements.txt > /tmp/requirements-web.txt \
    && pip install --no-cache-dir -r /tmp/requirements-web.txt \
    && rm /tmp/requirements-web.txt

COPY pet_registry ./pet_registry
COPY web_app ./web_app

USER 10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "web_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
