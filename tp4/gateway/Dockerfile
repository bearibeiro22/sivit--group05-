FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 GATEWAY_DIR=/data
WORKDIR /app
COPY gateway.py .
VOLUME /data
ENTRYPOINT ["python", "gateway.py"]