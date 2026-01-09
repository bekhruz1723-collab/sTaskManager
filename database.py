import os
import sqlite3

DATABASE_URL = os.environ.get('postgres://koyeb-adm:npg_wWzuVoM3q5pB@ep-odd-hill-ag044kvz.c-2.eu-central-1.pg.koyeb.app/koyebdb', 'sqlite:///site.db')
USE_POSTGRESQL = DATABASE_URL.startswith('postgres://koyeb-adm:npg_wWzuVoM3q5pB@ep-odd-hill-ag044kvz.c-2.eu-central-1.pg.koyeb.app/koyebdb')

print(f"[Database Config]")
print(f"  DATABASE_URL: {DATABASE_URL[:50]}...")
print(f"  Type: {'PostgreSQL' if USE_POSTGRESQL else 'SQLite'}")

if USE_POSTGRESQL:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        HAS_PSYCOPG2 = True
        print(f"  psycopg2: Available")
    except ImportError:
        print("  psycopg2: NOT INSTALLED - Falling back to SQLite")
        HAS_PSYCOPG2 = False
        USE_POSTGRESQL = False
        DATABASE_URL = 'sqlite:///site.db'
else:
    HAS_PSYCOPG2 = False
    print(f"  psycopg2: Not needed")


class DatabaseHandler:
    def __init__(self, database_url=None):
        self.database_url = database_url or DATABASE_URL
        self.use_postgresql = USE_POSTGRESQL and HAS_PSYCOPG2

    def get_connection(self):
        if self.use_postgresql:
            db_url = self.database_url.replace('postgresql://', '')
            return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)
        else:
            db_path = self.database_url.replace('sqlite:///', '')
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def init_db(self, conn):
        cursor = conn.cursor()

        if self.use_postgresql:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status VARCHAR(20) DEFAULT 'not_started',
                    priority VARCHAR(20) DEFAULT 'medium',
                    deadline DATE,
                    user_id INTEGER NOT NULL,
                    parent_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (parent_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'not_started',
                    priority TEXT DEFAULT 'medium',
                    deadline TEXT,
                    user_id INTEGER NOT NULL,
                    parent_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (parent_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            ''')

        conn.commit()
        cursor.close()
        print(f"✓ Database initialized ({'PostgreSQL' if self.use_postgresql else 'SQLite'})")

    def execute(self, conn, query, params=None):
        cursor = conn.cursor()

        if self.use_postgresql:
            formatted_query = query
        else:
            formatted_query = query.replace('%s', '?')

        if params:
            cursor.execute(formatted_query, params)
        else:
            cursor.execute(formatted_query)

        return cursor

    def fetchone(self, cursor):
        return cursor.fetchone()

    def fetchall(self, cursor):
        return cursor.fetchall()

    def commit(self, conn):
        conn.commit()

    def close(self, conn):
        conn.close()

    def get_lastrowid(self, cursor, conn=None):
        if self.use_postgresql:
            return cursor.fetchone()['id']
        else:
            return cursor.lastrowid


db_handler = DatabaseHandler()