FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir "httpx==0.27.*"
COPY gateway.py .

ENTRYPOINT ["python", "-u", "gateway.py"]
