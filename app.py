import os
import json
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_123')
app.config['DATABASE'] = os.environ.get('DATABASE_PATH', 'site.db')

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    db.execute('''
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
    db.commit()
    
    try:
        cursor = db.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'description' not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN description TEXT")
            print("✅ Добавлен столбец 'description'")
        
        if 'priority' not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'")
            print("✅ Добавлен столбец 'priority'")
        
        db.commit()
    except Exception as e:
        print(f"⚠️  Миграция: {e}")

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        return User(user['id'], user['username'], user['password_hash'])
    return None

def load_translations():
    try:
        with open('translation.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

TRANSLATIONS = load_translations()

@app.context_processor
def inject_conf_var():
    lang = session.get('lang', 'ru')
    theme = session.get('theme', 'dark')
    return dict(
        lang=lang,
        theme=theme,
        t=lambda key: TRANSLATIONS.get(lang, {}).get(key, key),
        translations=TRANSLATIONS.get(lang, {})
    )

@app.route('/api/tasks', methods=['GET'])
@login_required
def api_get_tasks():
    db = get_db()
    tasks_rows = db.execute('''
        SELECT * FROM tasks 
        WHERE user_id = ? AND parent_id IS NULL 
        ORDER BY created_at DESC
    ''', (current_user.id,)).fetchall()
    
    tasks = []
    for task_row in tasks_rows:
        subtasks_rows = db.execute('''
            SELECT * FROM tasks 
            WHERE parent_id = ? 
            ORDER BY id ASC
        ''', (task_row['id'],)).fetchall()
        
        subtasks = [dict(row) for row in subtasks_rows]
        
        task_status = task_row['status']
        if subtasks:
            done_subtasks = sum(1 for st in subtasks if st['status'] == 'done')
            if done_subtasks == 0:
                task_status = 'not_started'
            elif done_subtasks == len(subtasks):
                task_status = 'done'
            else:
                task_status = 'in_progress'
        
        task_dict = dict(task_row)
        task_dict['subtasks'] = subtasks
        task_dict['computed_status'] = task_status
        tasks.append(task_dict)
    
    return jsonify(tasks)

@app.route('/api/stats/<period>', methods=['GET'])
@login_required
def api_get_stats(period):
    db = get_db()
    
    all_tasks = db.execute('''
        SELECT * FROM tasks WHERE user_id = ? AND parent_id IS NULL
    ''', (current_user.id,)).fetchall()
    
    not_started = 0
    in_progress = 0
    done = 0
    
    for task in all_tasks:
        subtasks = db.execute('SELECT * FROM tasks WHERE parent_id = ?', (task['id'],)).fetchall()
        if subtasks:
            done_subs = sum(1 for st in subtasks if st['status'] == 'done')
            if done_subs == 0:
                not_started += 1
            elif done_subs == len(subtasks):
                done += 1
            else:
                in_progress += 1
        else:
            if task['status'] == 'done':
                done += 1
            else:
                not_started += 1
    
    now = datetime.now()
    
    if period == 'hour':
        period_start = now - timedelta(hours=24)
        format_str = '%H:00'
        group_by = "strftime('%Y-%m-%d %H', completed_at)"
    elif period == 'day':
        period_start = now - timedelta(days=7)
        format_str = '%d.%m'
        group_by = "DATE(completed_at)"
    elif period == 'week':
        period_start = now - timedelta(weeks=12)
        format_str = 'W%W'
        group_by = "strftime('%Y-W%W', completed_at)"
    elif period == 'month':
        period_start = now - timedelta(days=365)
        format_str = '%b'
        group_by = "strftime('%Y-%m', completed_at)"
    else:  # year
        period_start = now - timedelta(days=365*3)
        format_str = '%Y'
        group_by = "strftime('%Y', completed_at)"
    
    productivity_query = db.execute(f'''
        SELECT {group_by} as period, COUNT(*) as count
        FROM tasks
        WHERE user_id = ? AND status = 'done' AND completed_at IS NOT NULL 
              AND parent_id IS NULL AND completed_at >= ?
        GROUP BY {group_by}
        ORDER BY period ASC
    ''', (current_user.id, period_start.isoformat())).fetchall()
    
    productivity = [{'period': row['period'], 'count': row['count']} for row in productivity_query]
    
    top_periods_query = db.execute(f'''
        SELECT {group_by} as period, COUNT(*) as count
        FROM tasks
        WHERE user_id = ? AND status = 'done' AND completed_at IS NOT NULL AND parent_id IS NULL
        GROUP BY {group_by}
        ORDER BY count DESC
        LIMIT 5
    ''', (current_user.id,)).fetchall()
    
    top_periods = []
    for row in top_periods_query:
        try:
            if period == 'day':
                date_obj = datetime.strptime(row['period'], '%Y-%m-%d')
                formatted = date_obj.strftime('%d.%m.%Y')
            elif period == 'hour':
                date_obj = datetime.strptime(row['period'], '%Y-%m-%d %H')
                formatted = date_obj.strftime('%d.%m %H:00')
            else:
                formatted = row['period']
        except:
            formatted = row['period']
        top_periods.append({'period': formatted, 'count': row['count']})
    
    priority_stats = db.execute('''
        SELECT priority, COUNT(*) as count
        FROM tasks
        WHERE user_id = ? AND parent_id IS NULL
        GROUP BY priority
    ''', (current_user.id,)).fetchall()
    
    priorities = {row['priority']: row['count'] for row in priority_stats}
    
    return jsonify({
        'status': {
            'not_started': not_started,
            'in_progress': in_progress,
            'done': done
        },
        'productivity': productivity,
        'top_periods': top_periods,
        'priorities': priorities,
        'total': len(all_tasks)
    })

@app.route('/api/task', methods=['POST'])
@login_required
def api_add_task():
    db = get_db()
    data = request.json
    
    cursor = db.execute('''
        INSERT INTO tasks (title, description, priority, user_id, deadline, status)
        VALUES (?, ?, ?, ?, ?, 'not_started')
    ''', (data.get('title'), data.get('description'), data.get('priority', 'medium'), 
          current_user.id, data.get('deadline')))
    task_id = cursor.lastrowid
    
    if data.get('subtasks'):
        for subtask in data['subtasks']:
            if subtask.strip():
                db.execute('''
                    INSERT INTO tasks (title, user_id, parent_id, status)
                    VALUES (?, ?, ?, 'not_started')
                ''', (subtask, current_user.id, task_id))
    
    db.commit()
    return jsonify({'success': True, 'id': task_id})

@app.route('/api/task/<int:id>', methods=['PUT'])
@login_required
def api_update_task(id):
    db = get_db()
    task = db.execute('SELECT * FROM tasks WHERE id = ?', (id,)).fetchone()
    
    if not task or task['user_id'] != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.json
    action = data.get('action')
    
    if action == 'toggle':
        subtasks = db.execute('SELECT * FROM tasks WHERE parent_id = ?', (id,)).fetchall()
        
        new_status = 'not_started' if task['status'] == 'done' else 'done'
        completed_at = datetime.utcnow().isoformat() if new_status == 'done' else None
        
        db.execute('UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?', 
                  (new_status, completed_at, id))
        
        if subtasks:
            for subtask in subtasks:
                db.execute('UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?', 
                          (new_status, completed_at, subtask['id']))
    
    elif action == 'toggle_subtask':
        new_status = 'not_started' if task['status'] == 'done' else 'done'
        completed_at = datetime.utcnow().isoformat() if new_status == 'done' else None
        db.execute('UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?', 
                  (new_status, completed_at, id))
    
    db.commit()
    return jsonify({'success': True})

@app.route('/api/task/<int:id>', methods=['DELETE'])
@login_required
def api_delete_task(id):
    db = get_db()
    task = db.execute('SELECT * FROM tasks WHERE id = ?', (id,)).fetchone()
    
    if task and task['user_id'] == current_user.id:
        db.execute('DELETE FROM tasks WHERE id = ? OR parent_id = ?', (id, id))
        db.commit()
        return jsonify({'success': True})
    
    return jsonify({'error': 'Access denied'}), 403

@app.route('/set_lang/<language>')
def set_lang(language):
    if language in ['ru', 'en']:
        session['lang'] = language
    return redirect(request.referrer or url_for('index'))

@app.route('/toggle_theme')
def toggle_theme():
    current_theme = session.get('theme', 'dark')
    session['theme'] = 'light' if current_theme == 'dark' else 'dark'
    return redirect(request.referrer or url_for('index'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        db = get_db()
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_row = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user_row and check_password_hash(user_row['password_hash'], password):
            user = User(user_row['id'], user_row['username'], user_row['password_hash'])
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('error_login_invalid')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        db = get_db()
        username = request.form.get('username')
        password = request.form.get('password')
        
        if len(password) < 8:
            flash('error_pass_short')
            return redirect(url_for('register'))
        
        existing = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            flash('error_user_exists')
            return redirect(url_for('register'))
        
        hashed_pw = generate_password_hash(password)
        cursor = db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                           (username, hashed_pw))
        db.commit()
        
        user = User(cursor.lastrowid, username, hashed_pw)
        login_user(user)
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)