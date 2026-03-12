FROM python:3.11-slim

WORKDIR /app

COPY ux_job_hunter_web/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ux_job_hunter_web/backend/ /app/backend/
COPY ux_job_hunter_web/frontend/ /app/frontend/

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
