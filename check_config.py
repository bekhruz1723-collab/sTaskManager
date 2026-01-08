import os
import sys

print("=" * 60)
print("  TASK MANAGER - CONFIGURATION CHECK")
print("=" * 60)
print()

try:
    from dotenv import load_dotenv

    load_dotenv()
    print("✓ .env file loaded")
except ImportError:
    print("⚠ python-dotenv not installed (optional)")

print()
print("Environment Variables:")
print("-" * 60)

SECRET_KEY = os.environ.get('SECRET_KEY', 'NOT SET')
DATABASE_URL = os.environ.get('DATABASE_URL', 'NOT SET')
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'NOT SET')
PORT = os.environ.get('PORT', 'NOT SET')

print(f"SECRET_KEY: {'*' * 20} ({len(SECRET_KEY)} chars)")
print(f"DATABASE_URL: {DATABASE_URL}")
print(f"BOT_TOKEN: {'*' * 20}...{BOT_TOKEN[-10:] if len(BOT_TOKEN) > 10 else 'NOT SET'}")
print(f"PORT: {PORT}")

print()
print("Database Configuration:")
print("-" * 60)

if DATABASE_URL == 'NOT SET':
    print("❌ DATABASE_URL not set!")
    print("   Create .env file and set: DATABASE_URL=sqlite:///site.db")
    sys.exit(1)

if DATABASE_URL.startswith('postgresql'):
    print("📊 Database Type: PostgreSQL")
    print("   ⚠ WARNING: PostgreSQL requires psycopg2-binary")
    print("   For local development, use: DATABASE_URL=sqlite:///site.db")

    try:
        import psycopg2

        print("   ✓ psycopg2 is installed")
    except ImportError:
        print("   ❌ psycopg2 NOT INSTALLED!")
        print("   Install: pip install psycopg2-binary")
        print("   OR change DATABASE_URL to: sqlite:///site.db")
        sys.exit(1)

elif DATABASE_URL.startswith('sqlite'):
    print("📊 Database Type: SQLite")
    print("   ✓ Perfect for local development")
    db_path = DATABASE_URL.replace('sqlite:///', '')
    print(f"   Database file: {db_path}")

    if os.path.exists(db_path):
        print(f"   ✓ Database file exists")
    else:
        print(f"   ℹ Database file will be created on first run")
else:
    print(f"❌ Unknown DATABASE_URL format: {DATABASE_URL}")
    print("   Should be either:")
    print("   - sqlite:///site.db (for local)")
    print("   - postgresql://user:pass@host:5432/db (for production)")
    sys.exit(1)

print()
print("Bot Configuration:")
print("-" * 60)

if BOT_TOKEN == 'NOT SET':
    print("❌ BOT_TOKEN not set!")
    print("   Get token from @BotFather in Telegram")
elif len(BOT_TOKEN) < 40:
    print("❌ BOT_TOKEN seems invalid (too short)")
else:
    print("✓ BOT_TOKEN looks valid")

print()
print("Recommendations:")
print("-" * 60)

if DATABASE_URL.startswith('postgresql') and not os.environ.get('KOYEB_APP_NAME'):
    print("⚠ You're using PostgreSQL locally")
    print("  Consider changing to SQLite for development:")
    print("  DATABASE_URL=sqlite:///site.db")

if SECRET_KEY == 'your_secret_key_here_min_32_chars':
    print("⚠ You're using default SECRET_KEY")
    print("  Generate a new one:")
    print("  python -c \"import secrets; print(secrets.token_urlsafe(32))\"")

print()
print("=" * 60)
print("Configuration check complete!")
print("=" * 60)