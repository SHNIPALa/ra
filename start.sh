#!/bin/bash

echo "========================================="
echo "🎵 RADIO BOT STARTING"
echo "========================================="

# Запускаем Bore туннель в фоне
echo "🔄 Запуск Bore туннеля..."
bore local 8080 --to bore.pub > /tmp/bore.log 2>&1 &
BORE_PID=$!

# Ждем запуска Bore
sleep 3

# Получаем публичный URL из логов
PUBLIC_URL=""
for i in {1..10}; do
    if [ -f /tmp/bore.log ]; then
        URL=$(grep -o 'https\?://[a-zA-Z0-9.-]*\.bore\.pub:[0-9]*' /tmp/bore.log | head -1)
        if [ ! -z "$URL" ]; then
            PUBLIC_URL="$URL"
            break
        fi
    fi
    sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
    # Альтернатива: используем локальный IP
    PUBLIC_URL="http://localhost:8080"
    echo "⚠️ Не удалось получить URL от Bore, используем localhost"
else
    echo "✅ Bore туннель: $PUBLIC_URL"
fi

export PUBLIC_URL="$PUBLIC_URL"

# Запускаем бота
echo "🚀 Запуск бота..."
python bot.py

# Останавливаем Bore при завершении
kill $BORE_PID