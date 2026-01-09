import multiprocessing
import os
import sys
from pathlib import Path
from database import db_handler
try:
    conn = db_handler.get_connection()
    db_handler.init_db(conn)
    db_handler.close(conn)
    print("✓ База данных успешно инициализирована")
except Exception as e:
    print(f"Ошибка инициализации БД: {e}")

def run_flask_app():
    from app import app, init_db
    
    with app.app_context():
        init_db()
    
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)

def run_telegram_bot():
    from bot import main as bot_main
    bot_main()

def main():
    print("Starting Task Manager Application...")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {Path.cwd()}")
    
    flask_process = multiprocessing.Process(target=run_flask_app, name="FlaskApp")
    bot_process = multiprocessing.Process(target=run_telegram_bot, name="TelegramBot")
    
    flask_process.start()
    print("✓ Flask web application started")
    
    bot_process.start()
    print("✓ Telegram bot started")
    
    try:
        flask_process.join()
        bot_process.join()
    except KeyboardInterrupt:
        print("\nShutting down...")
        flask_process.terminate()
        bot_process.terminate()
        flask_process.join()
        bot_process.join()
        print("Application stopped")

if __name__ == '__main__':
    multiprocessing.set_start_method('spawn', force=True)
    main()