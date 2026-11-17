FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY runtime/ /app/runtime/
RUN useradd --system --uid 10001 wf
USER wf
EXPOSE 8080
CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
