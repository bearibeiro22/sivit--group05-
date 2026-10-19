FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# requirements primeiro: o pip install fica em cache enquanto as dependencias nao mudam
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# remove CRLF caso o Git do Windows os tenha introduzido
RUN sed -i 's/\r$//' arranque.sh && chmod +x arranque.sh
EXPOSE 8000
CMD ["./arranque.sh"]
