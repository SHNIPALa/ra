import os
import time
import threading
import sqlite3
import random
import subprocess
import requests
import signal
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from mutagen.mp3 import MP3

# ===== КОНФИГУРАЦИЯ =====
PORT = 8080
MUSIC_FOLDER = "music"
PENDING_FOLDER = "pending"
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]
PUBLIC_URL = os.getenv('PUBLIC_URL', f'http://localhost:{PORT}')

# Создаем папки
os.makedirs(MUSIC_FOLDER, exist_ok=True)
os.makedirs(PENDING_FOLDER, exist_ok=True)
os.makedirs("data", exist_ok=True)

# Глобальные переменные
playlist = []
current_song = None
current_file = None
current_position = 0
listeners = 0
bore_process = None


# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('data/radio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, approved INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_songs
                 (id INTEGER PRIMARY KEY, filename TEXT, user_id INTEGER, user_name TEXT, date TEXT)''')
    conn.commit()
    conn.close()


init_db()


# ===== РАДИО ПЛЕЙЛИСТ =====
def load_playlist():
    global playlist, current_song
    playlist = []
    for mp3 in Path(MUSIC_FOLDER).rglob("*.mp3"):
        playlist.append(mp3)
    if playlist:
        random.shuffle(playlist)
        current_song = playlist[0]
        print(f"📀 Загружено {len(playlist)} песен")
    else:
        print(f"⚠️ Нет MP3 в папке '{MUSIC_FOLDER}'")


def next_song():
    global current_song, current_file, current_position
    if not playlist:
        return
    if current_file:
        current_file.close()
        current_file = None
    if current_song in playlist:
        idx = playlist.index(current_song)
        current_song = playlist[(idx + 1) % len(playlist)]
    else:
        current_song = playlist[0]
    current_position = 0
    print(f"🎵 Сейчас: {current_song.name}")


def approve_song(filename):
    src = Path(PENDING_FOLDER) / filename
    dst = Path(MUSIC_FOLDER) / filename
    if src.exists():
        src.rename(dst)
        load_playlist()
        return True
    return False


def reject_song(filename):
    src = Path(PENDING_FOLDER) / filename
    if src.exists():
        src.unlink()
        return True
    return False


def get_song_info():
    if current_song and current_song.exists():
        try:
            audio = MP3(current_song)
            return {
                'title': current_song.stem,
                'duration': int(audio.info.length),
                'duration_str': f"{int(audio.info.length) // 60}:{int(audio.info.length) % 60:02d}"
            }
        except:
            pass
    return {'title': 'Нет песен', 'duration': 0, 'duration_str': '0:00'}


# ===== HTTP РАДИО СЕРВЕР =====
class RadioHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        global listeners, current_file, current_position, current_song, playlist

        if self.path == '/stream.mp3' or self.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Disposition', 'attachment; filename="stream.mp3"')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            listeners += 1
            print(f"🔊 Слушатель: {self.client_address[0]} (всего: {listeners})")

            try:
                while True:
                    if not playlist:
                        time.sleep(1)
                        continue

                    if not current_song and playlist:
                        current_song = playlist[0]

                    if not current_file and current_song:
                        current_file = open(current_song, 'rb')
                        current_position = 0
                        print(f"▶️ Играет: {current_song.name}")

                    if current_file:
                        current_file.seek(current_position)
                        data = current_file.read(8192)

                        if data:
                            current_position += len(data)
                            self.wfile.write(data)
                            self.wfile.flush()
                        else:
                            current_file.close()
                            current_file = None
                            next_song()

                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                listeners -= 1
                print(f"🔇 Слушатель ушел (всего: {listeners})")

        elif self.path == '/':
            info = get_song_info()
            stream_url = f"{PUBLIC_URL}/stream.mp3"
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🎵 Мое Радио</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{{font-family:Arial;text-align:center;padding:50px;background:linear-gradient(135deg,#667eea,#764ba2);color:white}}
        .player{{background:rgba(255,255,255,0.1);padding:30px;border-radius:20px;max-width:500px;margin:0 auto}}
        audio{{width:100%;margin:20px 0}}
        button{{background:#ff6b6b;color:white;border:none;padding:10px 20px;margin:5px;border-radius:5px;cursor:pointer}}
        .download-btn{{background:#4ecdc4}}
        .info{{margin-top:20px}}
        .url{{background:rgba(0,0,0,0.3);padding:10px;border-radius:10px;margin-top:15px;word-break:break-all}}
    </style>
</head>
<body>
    <div class="player">
        <h1>🎵 Мое Радио</h1>
        <audio controls autoplay><source src="/stream" type="audio/mpeg"></audio>
        <br>
        <a href="/stream.mp3" download><button class="download-btn">📥 СКАЧАТЬ STREAM.MP3</button></a>
        <div class="info">
            🎵 {info['title']}<br>
            👥 {listeners} слушателей<br>
            📀 {len(playlist)} песен
        </div>
        <div class="url">
            🔗 Ссылка для друзей:<br>
            <small>{stream_url}</small>
        </div>
    </div>
</body>
</html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())

        elif self.path == '/status':
            import json
            info = get_song_info()
            data = {
                'title': info['title'],
                'listeners': listeners,
                'songs': len(playlist)
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/next':
            next_song()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()


def run_radio_server():
    server = HTTPServer(('0.0.0.0', PORT), RadioHandler)
    print(f"✅ Радио сервер: http://0.0.0.0:{PORT}")
    server.serve_forever()


# ===== TELEGRAM БОТ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"

    conn = sqlite3.connect('data/radio.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

    stream_url = f"{PUBLIC_URL}/stream.mp3"
    info = get_song_info()

    keyboard = [
        [InlineKeyboardButton("🎵 Слушать радио", url=stream_url)],
        [InlineKeyboardButton("📥 Скачать поток", url=stream_url)],
        [InlineKeyboardButton("📤 Отправить трек", callback_data="upload")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")]
    ]

    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔧 Админ панель", callback_data="admin")])
        keyboard.append([InlineKeyboardButton("🔄 Обновить URL", callback_data="refresh_url")])

    await update.message.reply_text(
        f"🎵 *РАДИО БОТ*\n\n"
        f"🌍 *ССЫЛКА ДЛЯ ДРУЗЕЙ:*\n"
        f"`{stream_url}`\n\n"
        f"📊 *Сейчас в эфире:*\n"
        f"🎵 {info['title']}\n"
        f"👥 {listeners} слушателей\n"
        f"📀 {len(playlist)} песен\n\n"
        f"💡 *Как добавить трек:*\n"
        f"Нажмите 'Отправить трек' и загрузите MP3\n\n"
        f"⚠️ *Важно:* Ссылка может меняться при перезапуске",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "refresh_url" and user_id in ADMIN_IDS:
        # Обновляем URL (нужно перезапустить Bore)
        await query.edit_message_text(
            "🔄 Перезапуск туннеля...\n"
            "Новая ссылка появится через минуту",
            parse_mode='Markdown'
        )
        # Перезапускаем контейнер
        os.system("pkill bore")
        time.sleep(2)
        os.system("bore local 8080 --to bore.pub &")
        await query.edit_message_text("✅ Туннель перезапущен! Нажмите /start для обновления ссылки")
        return

    elif query.data == "upload":
        await query.edit_message_text(
            "📤 *Отправьте MP3 файл*\n\n"
            "Просто отправьте MP3 файл, он уйдет на модерацию.\n"
            "После одобрения появится в эфире!\n\n"
            "✅ Максимальный размер: 50MB",
            parse_mode='Markdown'
        )

    elif query.data == "status":
        info = get_song_info()
        stream_url = f"{PUBLIC_URL}/stream.mp3"
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"🎵 Сейчас играет: *{info['title']}*\n"
            f"⏱️ Длительность: {info['duration_str']}\n"
            f"👥 Слушателей онлайн: *{listeners}*\n"
            f"📀 Песен в плейлисте: *{len(playlist)}*\n"
            f"🎚️ Статус: ✅ Активен\n\n"
            f"🔗 Ссылка для друзей:\n`{stream_url}`",
            parse_mode='Markdown'
        )

    elif query.data == "admin" and user_id in ADMIN_IDS:
        await show_admin_panel(update, context)

    elif query.data.startswith("approve_"):
        song_id = int(query.data.split("_")[1])
        conn = sqlite3.connect('data/radio.db')
        c = conn.cursor()
        c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
        song = c.fetchone()
        if song:
            approve_song(song[0])
            c.execute("DELETE FROM pending_songs WHERE id = ?", (song_id,))
            await query.edit_message_text(f"✅ Трек одобрен! Он уже в эфире")
        else:
            await query.edit_message_text(f"❌ Трек не найден")
        conn.commit()
        conn.close()
        await show_admin_panel(update, context)

    elif query.data.startswith("reject_"):
        song_id = int(query.data.split("_")[1])
        conn = sqlite3.connect('data/radio.db')
        c = conn.cursor()
        c.execute("SELECT filename FROM pending_songs WHERE id = ?", (song_id,))
        song = c.fetchone()
        if song:
            reject_song(song[0])
            c.execute("DELETE FROM pending_songs WHERE id = ?", (song_id,))
            await query.edit_message_text(f"❌ Трек отклонен")
        else:
            await query.edit_message_text(f"❌ Трек не найден")
        conn.commit()
        conn.close()
        await show_admin_panel(update, context)

    elif query.data == "back":
        await start(update, context)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    conn = sqlite3.connect('data/radio.db')
    c = conn.cursor()
    c.execute("SELECT id, filename, user_name, date FROM pending_songs ORDER BY date DESC")
    pending = c.fetchall()
    conn.close()

    keyboard = []

    if pending:
        keyboard.append([InlineKeyboardButton("📀 ТРЕКИ НА МОДЕРАЦИИ:", callback_data="none")])
        for song_id, filename, user_name, date in pending:
            keyboard.append([
                InlineKeyboardButton(f"✅ {filename[:25]}", callback_data=f"approve_{song_id}"),
                InlineKeyboardButton(f"❌", callback_data=f"reject_{song_id}")
            ])
    else:
        keyboard.append([InlineKeyboardButton("✅ Нет треков на модерации", callback_data="none")])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])

    await query.edit_message_text(
        "🔧 *АДМИН ПАНЕЛЬ*\n\n"
        f"📀 Треков ожидают: {len(pending)}\n\n"
        "Управление треками:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"

    if update.message.audio:
        file = update.message.audio
        file_name = file.file_name

        if file.file_size > 50 * 1024 * 1024:
            await update.message.reply_text("❌ Файл слишком большой! Максимум 50MB")
            return

        status_msg = await update.message.reply_text(f"📥 Загружаю {file_name}...")

        try:
            new_file = await context.bot.get_file(file.file_id)
            file_path = Path(PENDING_FOLDER) / file_name
            await new_file.download_to_drive(file_path)

            conn = sqlite3.connect('data/radio.db')
            c = conn.cursor()
            c.execute("INSERT INTO pending_songs (filename, user_id, user_name, date) VALUES (?, ?, ?, ?)",
                      (file_name, user_id, username, datetime.now().isoformat()))
            conn.commit()
            conn.close()

            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📀 *НОВЫЙ ТРЕК!*\n\n"
                        f"От: {username}\n"
                        f"Файл: {file_name}\n"
                        f"Размер: {file.file_size / 1024 / 1024:.2f} MB",
                        parse_mode='Markdown'
                    )
                except:
                    pass

            await status_msg.edit_text(
                f"✅ *Трек отправлен на модерацию!*\n\n"
                f"📀 {file_name}\n"
                f"После одобрения трек появится в эфире",
                parse_mode='Markdown'
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_url = f"{PUBLIC_URL}/stream.mp3"
    await update.message.reply_text(
        f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
        f"📥 *Скачать/слушать поток:*\n"
        f"`{stream_url}`\n\n"
        f"💡 *Инструкция:*\n"
        f"1. Отправьте эту ссылку другу\n"
        f"2. Он откроет ее в браузере\n"
        f"3. Начнется прослушивание\n\n"
        f"🎵 Поток бесконечный!\n\n"
        f"⚠️ При перезапуске бота ссылка может измениться",
        parse_mode='Markdown'
    )


def main():
    # Запускаем радио сервер в отдельном потоке
    radio_thread = threading.Thread(target=run_radio_server, daemon=True)
    radio_thread.start()

    time.sleep(2)
    load_playlist()

    # Запускаем бота
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("link", get_link))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))

    print("\n" + "=" * 50)
    print("✅ БОТ ЗАПУЩЕН!")
    print("=" * 50)
    print(f"\n🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ:")
    print(f"   {PUBLIC_URL}/stream.mp3")
    print(f"\n🤖 Telegram бот: @{TOKEN.split(':')[0]}")
    print("\n📀 Админ панель: /start в боте")
    print("=" * 50 + "\n")

    application.run_polling()


if __name__ == '__main__':
    main()