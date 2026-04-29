import os
import time
import threading
import sqlite3
import random
import subprocess
import re
import requests
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
TOKEN = "8726694308:AAF5_WwE1Tu9csG7ZKjwgG50n-1A5nByM4Q"
ADMIN_IDS = []  # Добавьте ваш Telegram ID сюда

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
public_url = None
tunnel_process = None

# ===== ЗАПУСК LOCAL TUNNEL =====
def start_localtunnel():
    global public_url, tunnel_process
    try:
        # Запускаем LocalTunnel в фоне с уникальным субдоменом
        import time
        unique_name = f"radio{int(time.time())}"
        
        tunnel_process = subprocess.Popen(
            ['lt', '--port', str(PORT), '--subdomain', unique_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        print(f"🔄 Запуск LocalTunnel с субдоменом: {unique_name}")
        
        # Ждем и читаем вывод для получения URL
        for i in range(20):
            if tunnel_process.stdout:
                line = tunnel_process.stdout.readline()
                print(f"LT: {line}")
                # LocalTunnel выводит URL в stdout
                url_match = re.search(r'https?://[a-zA-Z0-9\-]+\.loca\.lt', line)
                if url_match:
                    public_url = url_match.group(0)
                    print(f"✅ LocalTunnel URL: {public_url}")
                    return True
            time.sleep(1)
        
        # Если не нашли в stdout, пробуем через stderr
        for i in range(10):
            if tunnel_process.stderr:
                line = tunnel_process.stderr.readline()
                print(f"LT stderr: {line}")
                url_match = re.search(r'https?://[a-zA-Z0-9\-]+\.loca\.lt', line)
                if url_match:
                    public_url = url_match.group(0)
                    print(f"✅ LocalTunnel URL: {public_url}")
                    return True
            time.sleep(1)
        
        print("⚠️ Не удалось получить URL от LocalTunnel")
        return False
        
    except Exception as e:
        print(f"❌ Ошибка LocalTunnel: {e}")
        return False

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
                'duration_str': f"{int(audio.info.length)//60}:{int(audio.info.length)%60:02d}"
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
            except:
                pass
            finally:
                listeners -= 1
                print(f"🔇 Слушатель ушел (всего: {listeners})")
        
        elif self.path == '/':
            info = get_song_info()
            stream_url = f"{public_url}/stream.mp3" if public_url else f"http://localhost:{PORT}/stream.mp3"
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
    
    info = get_song_info()
    
    keyboard = [
        [InlineKeyboardButton("📤 Отправить трек", callback_data="upload")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("🔗 Получить ссылку", callback_data="get_link")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔧 Админ панель", callback_data="admin")])
    
    await update.message.reply_text(
        f"🎵 *РАДИО БОТ*\n\n"
        f"📊 *Сейчас в эфире:*\n"
        f"🎵 {info['title']}\n"
        f"👥 {listeners} слушателей\n"
        f"📀 {len(playlist)} песен\n\n"
        f"💡 *Как слушать:*\n"
        f"Нажмите 'Получить ссылку' для получения адреса потока\n\n"
        f"💡 *Как добавить трек:*\n"
        f"Нажмите 'Отправить трек' и загрузите MP3",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global public_url
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "get_link":
        if public_url:
            stream_url = f"{public_url}/stream.mp3"
            await query.edit_message_text(
                f"🔗 *ССЫЛКА ДЛЯ ДРУЗЕЙ*\n\n"
                f"📥 *Прямая ссылка (скачивание/прослушивание):*\n"
                f"`{stream_url}`\n\n"
                f"🌐 *Веб-плеер:*\n"
                f"{public_url}\n\n"
                f"💡 *Инструкция:*\n"
                f"1. Отправьте ссылку другу\n"
                f"2. Он откроет в браузере или VLC\n"
                f"3. Начнется прослушивание\n\n"
                f"🎵 Поток бесконечный!",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "⏳ *Ссылка еще не готова*\n\n"
                "Подождите 1-2 минуты, пока настроится туннель.\n"
                "Затем нажмите 'Получить ссылку' снова.\n\n"
                "Если проблема повторяется, проверьте логи:\n"
                "`docker logs radio-bot`",
                parse_mode='Markdown'
            )
    
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
        await query.edit_message_text(
            f"📊 *СТАТУС РАДИО*\n\n"
            f"🎵 Сейчас играет: *{info['title']}*\n"
            f"⏱️ Длительность: {info['duration_str']}\n"
            f"👥 Слушателей онлайн: *{listeners}*\n"
            f"📀 Песен в плейлисте: *{len(playlist)}*\n"
            f"🚀 Туннель: {'✅ Активен' if public_url else '⏳ Запускается...'}\n",
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

def main():
    global public_url
    
    # Запускаем LocalTunnel
    print("🔄 Запуск LocalTunnel...")
    success = start_localtunnel()
    
    if success:
        print(f"✅ Публичный URL: {public_url}")
    else:
        print("⚠️ Не удалось получить URL от LocalTunnel")
        print("💡 Попробуйте запустить вручную в другом терминале:")
        print("   npx localtunnel --port 8080")
    
    # Запускаем радио сервер
    radio_thread = threading.Thread(target=run_radio_server, daemon=True)
    radio_thread.start()
    
    time.sleep(2)
    load_playlist()
    
    # Запускаем бота
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("\n" + "=" * 50)
    print("✅ БОТ ЗАПУЩЕН!")
    print("=" * 50)
    if public_url:
        print(f"\n🔗 ССЫЛКА ДЛЯ ДРУЗЕЙ:")
        print(f"   {public_url}/stream.mp3")
    else:
        print("\n⚠️ URL НЕ ПОЛУЧЕН!")
        print("   Запустите туннель вручную:")
        print("   1. Откройте новый терминал")
        print("   2. Выполните: npx localtunnel --port 8080")
        print("   3. Скопируйте полученную ссылку")
        print("   4. Отправьте друзьям: ССЫЛКА/stream.mp3")
    print("\n🤖 Бот готов к работе в Telegram")
    print("=" * 50 + "\n")
    
    application.run_polling()

if __name__ == '__main__':
    main()
