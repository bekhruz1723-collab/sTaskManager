import os
import json
import psycopg2
import psycopg2.extras
from database import db_handler
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_123')

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

def get_db():
    if 'db' not in g:
        g.db = db_handler.get_connection()
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db_handler.close(db) 

def init_db():
    db = get_db()
    db_handler.init_db(db)

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    try:
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        user = cur.fetchone()
        cur.close()
        if user:
            return User(user['id'], user['username'], user['password_hash'])
    except Exception:
        pass
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
    cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        SELECT * FROM tasks 
        WHERE user_id = %s AND parent_id IS NULL 
        ORDER BY created_at DESC
    ''', (current_user.id,))
    tasks_rows = cur.fetchall()
    
    tasks = []
    for task_row in tasks_rows:
        cur.execute('''
            SELECT * FROM tasks 
            WHERE parent_id = %s 
            ORDER BY id ASC
        ''', (task_row['id'],))
        subtasks_rows = cur.fetchall()
        
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
    
    cur.close()
    return jsonify(tasks)

@app.route('/api/stats/<period>', methods=['GET'])
@login_required
def api_get_stats(period):
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        SELECT * FROM tasks WHERE user_id = %s AND parent_id IS NULL
    ''', (current_user.id,))
    all_tasks = cur.fetchall()
    
    not_started = 0
    in_progress = 0
    done = 0
    
    for task in all_tasks:
        cur.execute('SELECT * FROM tasks WHERE parent_id = %s', (task['id'],))
        subtasks = cur.fetchall()
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
        group_by = "TO_CHAR(completed_at, 'YYYY-MM-DD HH24')" 
    elif period == 'day':
        period_start = now - timedelta(days=7)
        group_by = "TO_CHAR(completed_at, 'YYYY-MM-DD')"
    elif period == 'week':
        period_start = now - timedelta(weeks=12)
        group_by = "TO_CHAR(completed_at, 'IYYY-\"W\"IW')"
    elif period == 'month':
        period_start = now - timedelta(days=365)
        group_by = "TO_CHAR(completed_at, 'YYYY-MM')"
    else:  # year
        period_start = now - timedelta(days=365*3)
        group_by = "TO_CHAR(completed_at, 'YYYY')"
    
    cur.execute(f'''
        SELECT {group_by} as period, COUNT(*) as count
        FROM tasks
        WHERE user_id = %s AND status = 'done' AND completed_at IS NOT NULL 
              AND parent_id IS NULL AND completed_at >= %s
        GROUP BY {group_by}
        ORDER BY period ASC
    ''', (current_user.id, period_start.isoformat()))
    productivity_query = cur.fetchall()
    
    productivity = [{'period': row['period'], 'count': row['count']} for row in productivity_query]
    
    cur.execute(f'''
        SELECT {group_by} as period, COUNT(*) as count
        FROM tasks
        WHERE user_id = %s AND status = 'done' AND completed_at IS NOT NULL AND parent_id IS NULL
        GROUP BY {group_by}
        ORDER BY count DESC
        LIMIT 5
    ''', (current_user.id,))
    top_periods_query = cur.fetchall()
    
    top_periods = []
    for row in top_periods_query:
        formatted = row['period']
        try:
            if period == 'day':
                date_obj = datetime.strptime(row['period'], '%Y-%m-%d')
                formatted = date_obj.strftime('%d.%m.%Y')
            elif period == 'hour':
                date_obj = datetime.strptime(row['period'], '%Y-%m-%d %H')
                formatted = date_obj.strftime('%d.%m %H:00')
        except:
            pass
        top_periods.append({'period': formatted, 'count': row['count']})
    
    cur.execute('''
        SELECT priority, COUNT(*) as count
        FROM tasks
        WHERE user_id = %s AND parent_id IS NULL
        GROUP BY priority
    ''', (current_user.id,))
    priority_stats = cur.fetchall()
    
    priorities = {row['priority']: row['count'] for row in priority_stats}
    cur.close()
    
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
    cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        INSERT INTO tasks (title, description, priority, user_id, deadline, status)
        VALUES (%s, %s, %s, %s, %s, 'not_started')
        RETURNING id
    ''', (data.get('title'), data.get('description'), data.get('priority', 'medium'), 
          current_user.id, data.get('deadline')))
    
    task_id = cur.fetchone()['id']
    
    if data.get('subtasks'):
        for subtask in data['subtasks']:
            if subtask.strip():
                cur.execute('''
                    INSERT INTO tasks (title, user_id, parent_id, status)
                    VALUES (%s, %s, %s, 'not_started')
                ''', (subtask, current_user.id, task_id))
    
    db.commit()
    cur.close()
    return jsonify({'success': True, 'id': task_id})

@app.route('/api/task/<int:id>', methods=['PUT'])
@login_required
def api_update_task(id):
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('SELECT * FROM tasks WHERE id = %s', (id,))
    task = cur.fetchone()
    
    if not task or task['user_id'] != current_user.id:
        cur.close()
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.json
    action = data.get('action')
    
    if action == 'toggle':
        cur.execute('SELECT * FROM tasks WHERE parent_id = %s', (id,))
        subtasks = cur.fetchall()
        
        new_status = 'not_started' if task['status'] == 'done' else 'done'
        completed_at = datetime.utcnow().isoformat() if new_status == 'done' else None
        
        cur.execute('UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s', 
                   (new_status, completed_at, id))
        
        if subtasks:
            for subtask in subtasks:
                cur.execute('UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s', 
                           (new_status, completed_at, subtask['id']))
    
    elif action == 'toggle_subtask':
        new_status = 'not_started' if task['status'] == 'done' else 'done'
        completed_at = datetime.utcnow().isoformat() if new_status == 'done' else None
        cur.execute('UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s', 
                   (new_status, completed_at, id))
    
    db.commit()
    cur.close()
    return jsonify({'success': True})

@app.route('/api/task/<int:id>', methods=['DELETE'])
@login_required
def api_delete_task(id):
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('SELECT * FROM tasks WHERE id = %s', (id,))
    task = cur.fetchone()
    
    if task and task['user_id'] == current_user.id:
        cur.execute('DELETE FROM tasks WHERE id = %s OR parent_id = %s', (id, id))
        db.commit()
        cur.close()
        return jsonify({'success': True})
    
    cur.close()
    return jsonify({'error': 'Access denied'}), 403

@app.route('/set_lang/<language>')
def set_lang(language):
    if language in ['ru', 'en', 'uz']: 
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
        
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        user_row = cur.fetchone()
        cur.close()
        
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
        
        cur = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        existing = cur.fetchone()
        
        if existing:
            cur.close()
            flash('error_user_exists')
            return redirect(url_for('register'))
        
        hashed_pw = generate_password_hash(password)
        cur.execute('''
            INSERT INTO users (username, password_hash) 
            VALUES (%s, %s)
            RETURNING id
        ''', (username, hashed_pw))
        
        user_id = cur.fetchone()['id']
        db.commit()
        cur.close()
        
        user = User(user_id, username, hashed_pw)
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