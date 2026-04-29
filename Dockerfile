FROM python:3.11-slim

WORKDIR /app

# Установка необходимых пакетов
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Установка Bore (без регистрации)
RUN wget -q https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz \
    && tar -xzf bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz \
    && mv bore /usr/local/bin/ \
    && rm bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p music pending data

# Скрипт запуска
COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]