import sqlite3
import os

DB_PATH = 'site.db'

def migrate_database():
    
    if not os.path.exists(DB_PATH):
        print(f"❌ База данных {DB_PATH} не найдена!")
        print("ℹ️  Просто запустите app.py и она создастся автоматически")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("🔄 Начинаем миграцию базы данных...")
    
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [column[1] for column in cursor.fetchall()]
    
    changes_made = False
    
    if 'description' not in columns:
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN description TEXT")
            print("✅ Добавлен столбец 'description'")
            changes_made = True
        except sqlite3.OperationalError as e:
            print(f"⚠️  Ошибка при добавлении 'description': {e}")
    else:
        print("ℹ️  Столбец 'description' уже существует")
    
    if 'priority' not in columns:
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'")
            print("✅ Добавлен столбец 'priority'")
            changes_made = True
        except sqlite3.OperationalError as e:
            print(f"⚠️  Ошибка при добавлении 'priority': {e}")
    else:
        print("ℹ️  Столбец 'priority' уже существует")
    
    if changes_made:
        conn.commit()
        print("\n✨ Миграция успешно завершена!")
        print("🚀 Теперь можете запустить приложение: python app.py")
    else:
        print("\n✨ База данных уже обновлена, миграция не требуется")
    
    conn.close()

if __name__ == '__main__':
    print("=" * 60)
    print("  DATABASE MIGRATION TOOL")
    print("=" * 60)
    migrate_database()
    print("=" * 60)