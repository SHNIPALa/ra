FROM python:3.11-slim

WORKDIR /app

# Установка Bore
RUN apt-get update && apt-get install -y \
    wget \
    && wget -q https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz \
    && tar -xzf bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz \
    && mv bore /usr/local/bin/ \
    && rm bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz \
    && apt-get remove -y wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
RUN mkdir -p music pending data

# Запускаем бота напрямую
CMD ["python", "bot.py"]
