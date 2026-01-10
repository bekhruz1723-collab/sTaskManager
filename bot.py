import json
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from database import db_handler
except ImportError:
    print("ERROR: database.py not found!")
    import sys
    sys.exit(1)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8229500674:AAGWvQ6YoB1jYqOUgo5rKfMCSJ6KeyF3c-E')

LANGUAGE_SELECT, AUTH_CHOICE, LOGIN_USERNAME, LOGIN_PASSWORD = range(4)
REGISTER_USERNAME, REGISTER_PASSWORD = range(4, 6)
MAIN_MENU, ADD_TASK_TITLE, ADD_TASK_DESCRIPTION = range(6, 9)
ADD_TASK_PRIORITY, ADD_TASK_DEADLINE, ADD_TASK_SUBTASKS = range(9, 12)
ADD_SUBTASK_INPUT = 12

def load_translations():
    try:
        with open('translation.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

TRANSLATIONS = load_translations()

def t(lang, key):
    return TRANSLATIONS.get(lang, {}).get(key, key)

def get_user_by_username(username):
    db = db_handler.get_connection()
    cursor = db_handler.execute(db, 'SELECT * FROM users WHERE username = %s', (username,))
    user = db_handler.fetchone(cursor)
    cursor.close()
    db_handler.close(db)
    return user

def create_user(username, password):
    db = db_handler.get_connection()
    hashed_pw = generate_password_hash(password)
    try:
        if db_handler.use_postgresql:
            cursor = db_handler.execute(db, 'INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id', (username, hashed_pw))
            user_id = db_handler.get_lastrowid(cursor, db)
        else:
            cursor = db_handler.execute(db, 'INSERT INTO users (username, password_hash) VALUES (%s, %s)', (username, hashed_pw))
            user_id = db_handler.get_lastrowid(cursor)
        
        cursor.close()
        db_handler.commit(db)
        db_handler.close(db)
        return user_id
    except Exception as e:
        print(f"Error creating user: {e}")
        try:
            cursor.close()
        except:
            pass
        db_handler.close(db)
        return None

def verify_password(user, password):
    return check_password_hash(user['password_hash'], password)

def get_user_tasks(user_id):
    db = db_handler.get_connection()
    cursor = db_handler.execute(db, '''
        SELECT * FROM tasks 
        WHERE user_id = %s AND parent_id IS NULL 
        ORDER BY created_at DESC
    ''', (user_id,))
    tasks_rows = db_handler.fetchall(cursor)
    cursor.close()
    
    tasks = []
    for task_row in tasks_rows:
        cursor = db_handler.execute(db, '''
            SELECT * FROM tasks 
            WHERE parent_id = %s 
            ORDER BY id ASC
        ''', (task_row['id'],))
        subtasks_rows = db_handler.fetchall(cursor)
        cursor.close()
        
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
        if task_dict.get('created_at'):
            if isinstance(task_dict['created_at'], datetime):
                task_dict['created_at'] = task_dict['created_at'].isoformat()
        if task_dict.get('completed_at'):
            if isinstance(task_dict['completed_at'], datetime):
                task_dict['completed_at'] = task_dict['completed_at'].isoformat()
        if task_dict.get('deadline'):
            task_dict['deadline'] = str(task_dict['deadline'])
        
        task_dict['subtasks'] = subtasks
        task_dict['computed_status'] = task_status
        tasks.append(task_dict)
    
    db_handler.close(db)
    return tasks

def add_task(user_id, title, description, priority, deadline, subtasks):
    db = db_handler.get_connection()
    
    if db_handler.use_postgresql:
        cursor = db_handler.execute(db, '''
            INSERT INTO tasks (title, description, priority, user_id, deadline, status)
            VALUES (%s, %s, %s, %s, %s, 'not_started')
            RETURNING id
        ''', (title, description, priority, user_id, deadline))
        task_id = db_handler.get_lastrowid(cursor, db)
    else:
        cursor = db_handler.execute(db, '''
            INSERT INTO tasks (title, description, priority, user_id, deadline, status)
            VALUES (%s, %s, %s, %s, %s, 'not_started')
        ''', (title, description, priority, user_id, deadline))
        task_id = db_handler.get_lastrowid(cursor)
    
    cursor.close()
    
    if subtasks:
        for subtask in subtasks:
            if subtask.strip():
                cursor = db_handler.execute(db, '''
                    INSERT INTO tasks (title, user_id, parent_id, status)
                    VALUES (%s, %s, %s, 'not_started')
                ''', (subtask, user_id, task_id))
                cursor.close()
    
    db_handler.commit(db)
    db_handler.close(db)
    return task_id

def toggle_task(task_id, user_id):
    db = db_handler.get_connection()
    cursor = db_handler.execute(db, 'SELECT * FROM tasks WHERE id = %s', (task_id,))
    task = db_handler.fetchone(cursor)
    cursor.close()
    
    if not task or task['user_id'] != user_id:
        db_handler.close(db)
        return False
    
    cursor = db_handler.execute(db, 'SELECT * FROM tasks WHERE parent_id = %s', (task_id,))
    subtasks = db_handler.fetchall(cursor)
    cursor.close()
    
    new_status = 'not_started' if task['status'] == 'done' else 'done'
    completed_at = datetime.utcnow() if new_status == 'done' else None
    
    cursor = db_handler.execute(db, 'UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s', 
              (new_status, completed_at, task_id))
    cursor.close()
    
    if subtasks:
        for subtask in subtasks:
            cursor = db_handler.execute(db, 'UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s', 
                      (new_status, completed_at, subtask['id']))
            cursor.close()
    
    db_handler.commit(db)
    db_handler.close(db)
    return True

def toggle_subtask(subtask_id, user_id):
    db = db_handler.get_connection()
    cursor = db_handler.execute(db, 'SELECT * FROM tasks WHERE id = %s', (subtask_id,))
    task = db_handler.fetchone(cursor)
    cursor.close()
    
    if not task or task['user_id'] != user_id:
        db_handler.close(db)
        return False
    
    new_status = 'not_started' if task['status'] == 'done' else 'done'
    completed_at = datetime.utcnow() if new_status == 'done' else None
    cursor = db_handler.execute(db, 'UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s', 
              (new_status, completed_at, subtask_id))
    cursor.close()
    
    db_handler.commit(db)
    db_handler.close(db)
    return True

def delete_task(task_id, user_id):
    db = db_handler.get_connection()
    cursor = db_handler.execute(db, 'SELECT * FROM tasks WHERE id = %s', (task_id,))
    task = db_handler.fetchone(cursor)
    cursor.close()
    
    if task and task['user_id'] == user_id:
        cursor = db_handler.execute(db, 'DELETE FROM tasks WHERE id = %s OR parent_id = %s', (task_id, task_id))
        cursor.close()
        db_handler.commit(db)
        db_handler.close(db)
        return True
    
    db_handler.close(db)
    return False

def get_stats(user_id, period):
    db = db_handler.get_connection()
    
    cursor = db_handler.execute(db, '''
        SELECT * FROM tasks WHERE user_id = %s AND parent_id IS NULL
    ''', (user_id,))
    all_tasks = db_handler.fetchall(cursor)
    cursor.close()
    
    not_started = 0
    in_progress = 0
    done = 0
    
    for task in all_tasks:
        cursor = db_handler.execute(db, 'SELECT * FROM tasks WHERE parent_id = %s', (task['id'],))
        subtasks = db_handler.fetchall(cursor)
        cursor.close()
        
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
    
    if db_handler.use_postgresql:
        if period == 'day':
            period_start = now - timedelta(days=7)
            group_by = "DATE(completed_at)"
        elif period == 'week':
            period_start = now - timedelta(weeks=12)
            group_by = "TO_CHAR(completed_at, 'IYYY-IW')"
        else:
            period_start = now - timedelta(days=365)
            group_by = "TO_CHAR(completed_at, 'YYYY-MM')"
    else:
        if period == 'day':
            period_start = now - timedelta(days=7)
            group_by = "DATE(completed_at)"
        elif period == 'week':
            period_start = now - timedelta(weeks=12)
            group_by = "strftime('%Y-W%W', completed_at)"
        else:
            period_start = now - timedelta(days=365)
            group_by = "strftime('%Y-%m', completed_at)"
    
    period_start_str = period_start.isoformat() if db_handler.use_postgresql else period_start.strftime('%Y-%m-%d %H:%M:%S')
    
    cursor = db_handler.execute(db, f'''
        SELECT {group_by} as period, COUNT(*) as count
        FROM tasks
        WHERE user_id = %s AND status = 'done' AND completed_at IS NOT NULL 
              AND parent_id IS NULL AND completed_at >= %s
        GROUP BY {group_by}
        ORDER BY period ASC
    ''', (user_id, period_start_str))
    productivity_query = db_handler.fetchall(cursor)
    cursor.close()
    
    productivity = [{'period': str(row['period']), 'count': row['count']} for row in productivity_query]
    
    cursor = db_handler.execute(db, '''
        SELECT priority, COUNT(*) as count
        FROM tasks
        WHERE user_id = %s AND parent_id IS NULL
        GROUP BY priority
    ''', (user_id,))
    priority_stats = db_handler.fetchall(cursor)
    cursor.close()
    
    priorities = {row['priority']: row['count'] for row in priority_stats}
    
    cursor = db_handler.execute(db, f'''
        SELECT {group_by} as period, COUNT(*) as count
        FROM tasks
        WHERE user_id = %s AND status = 'done' AND completed_at IS NOT NULL AND parent_id IS NULL
        GROUP BY {group_by}
        ORDER BY count DESC
        LIMIT 5
    ''', (user_id,))
    top_periods_query = db_handler.fetchall(cursor)
    cursor.close()
    
    top_periods = [{'period': str(row['period']), 'count': row['count']} for row in top_periods_query]
    
    db_handler.close(db)
    
    return {
        'status': {
            'not_started': not_started,
            'in_progress': in_progress,
            'done': done
        },
        'productivity': productivity,
        'priorities': priorities,
        'top_periods': top_periods,
        'total': len(all_tasks)
    }

def format_stats_text(stats, lang, period):
    text = f"📊 *{t(lang, 'stats_title')}*\n"
    text += f"📹 {t(lang, f'bot_period_{period}')}\n\n"
    
    text += f"📈 *{t(lang, 'stats_title')}:*\n"
    text += f"📋 {t(lang, 'bot_total_tasks')}: *{stats['total']}*\n"
    text += f"✅ {t(lang, 'bot_completed_tasks')}: *{stats['status']['done']}*\n"
    text += f"⏳ {t(lang, 'bot_in_progress_tasks')}: *{stats['status']['in_progress']}*\n"
    text += f"📋 {t(lang, 'bot_not_started_tasks')}: *{stats['status']['not_started']}*\n\n"
    
    text += f"🎯 *{t(lang, 'priority')}:*\n"
    priorities = stats['priorities']
    text += f"🟢 {t(lang, 'priority_low')}: {priorities.get('low', 0)}\n"
    text += f"🟡 {t(lang, 'priority_medium')}: {priorities.get('medium', 0)}\n"
    text += f"🔴 {t(lang, 'priority_high')}: {priorities.get('high', 0)}\n\n"
    
    if stats['productivity']:
        text += f"📊 *{t(lang, 'productivity_chart')}:*\n"
        for p in stats['productivity'][-5:]:
            bar_length = int(p['count'] * 2)
            bar = '█' * bar_length
            text += f"`{p['period'][:10]}` {bar} {p['count']}\n"
        text += "\n"
    
    if stats['top_periods']:
        text += f"🏆 *{t(lang, 'top_days')}:*\n"
        for i, p in enumerate(stats['top_periods'], 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            text += f"{medal} {p['period']}: *{p['count']}* {t(lang, 'tasks_count')}\n"
    
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇬🇧 EN", callback_data="lang_en"),
         InlineKeyboardButton("🇷🇺 RU", callback_data="lang_ru"),
         InlineKeyboardButton("🇺🇿 UZ", callback_data="lang_uz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌐 Choose language / Выберите язык / Tilni tanlang:",
        reply_markup=reply_markup
    )
    
    return LANGUAGE_SELECT

async def language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = query.data.split('_')[1]
    context.user_data['lang'] = lang
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_login'), callback_data="auth_login")],
        [InlineKeyboardButton(t(lang, 'bot_register'), callback_data="auth_register")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"{t(lang, 'bot_welcome')}\n\n{t(lang, 'bot_auth_prompt')}"
    await query.edit_message_text(welcome_text, reply_markup=reply_markup)
    
    return AUTH_CHOICE

async def auth_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    choice = query.data.split('_')[1]
    
    context.user_data['auth_type'] = choice
    
    await query.edit_message_text(t(lang, 'bot_enter_username'))
    
    if choice == 'login':
        return LOGIN_USERNAME
    else:
        return REGISTER_USERNAME

async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    context.user_data['username'] = update.message.text.strip()
    
    await update.message.reply_text(t(lang, 'bot_enter_password'))
    return LOGIN_PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    username = context.user_data['username']
    password = update.message.text.strip()
    
    user = get_user_by_username(username)
    
    if user and verify_password(user, password):
        context.user_data['user_id'] = user['id']
        context.user_data['username'] = username
        
        success_text = t(lang, 'bot_login_success').format(username)
        await update.message.reply_text(success_text)
        await show_main_menu(update, context)
        return MAIN_MENU
    else:
        keyboard = [
            [InlineKeyboardButton(t(lang, 'bot_login'), callback_data="auth_login")],
            [InlineKeyboardButton(t(lang, 'bot_register'), callback_data="auth_register")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            t(lang, 'error_login_invalid') + "\n\n" + t(lang, 'bot_auth_prompt'),
            reply_markup=reply_markup
        )
        return AUTH_CHOICE

async def register_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    context.user_data['username'] = update.message.text.strip()
    
    await update.message.reply_text(t(lang, 'bot_enter_password'))
    return REGISTER_PASSWORD

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    username = context.user_data['username']
    password = update.message.text.strip()
    
    if len(password) < 8:
        await update.message.reply_text(t(lang, 'error_pass_short') + "\n\n" + t(lang, 'bot_enter_password'))
        return REGISTER_PASSWORD
    
    user_id = create_user(username, password)
    
    if user_id:
        context.user_data['user_id'] = user_id
        context.user_data['username'] = username
        
        success_text = t(lang, 'bot_register_success').format(username)
        await update.message.reply_text(success_text)
        await show_main_menu(update, context)
        return MAIN_MENU
    else:
        keyboard = [
            [InlineKeyboardButton(t(lang, 'bot_login'), callback_data="auth_login")],
            [InlineKeyboardButton(t(lang, 'bot_register'), callback_data="auth_register")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            t(lang, 'error_user_exists') + "\n\n" + t(lang, 'bot_auth_prompt'),
            reply_markup=reply_markup
        )
        return AUTH_CHOICE

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_my_tasks'), callback_data="menu_tasks")],
        [InlineKeyboardButton(t(lang, 'bot_add_task'), callback_data="menu_add_task")],
        [InlineKeyboardButton(t(lang, 'bot_statistics'), callback_data="menu_stats")],
        [InlineKeyboardButton(t(lang, 'bot_settings'), callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = t(lang, 'bot_main_menu')
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data.split('_', 1)[1]
    
    if action == 'tasks':
        await show_tasks(update, context, page=0)
    elif action == 'add_task':
        await start_add_task(update, context)
        return ADD_TASK_TITLE
    elif action == 'stats':
        await show_stats_menu(update, context)
    elif action == 'settings':
        await show_settings(update, context)
    elif action == 'main':
        await show_main_menu(update, context)
    
    return MAIN_MENU

async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    lang = context.user_data.get('lang', 'en')
    user_id = context.user_data.get('user_id')
    
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        keyboard = [[InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            t(lang, 'bot_no_tasks'),
            reply_markup=reply_markup
        )
        return
    
    tasks_per_page = 5
    total_pages = (len(tasks) + tasks_per_page - 1) // tasks_per_page
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * tasks_per_page
    end_idx = start_idx + tasks_per_page
    page_tasks = tasks[start_idx:end_idx]
    
    text = f"📋 {t(lang, 'bot_my_tasks')}\n\n"
    
    keyboard = []
    for task in page_tasks:
        status_emoji = "✅" if task['computed_status'] == 'done' else "⏳" if task['computed_status'] == 'in_progress' else "📋"
        task_priority = task.get('priority', 'medium')
        priority_emoji = "🟢" if task_priority == 'low' else "🟡" if task_priority == 'medium' else "🔴"
        
        # Используем локализованные метки приоритетов
        priority_text = t(lang, f'priority_{task_priority}')
        
        text += f"{status_emoji} {priority_emoji} *{task['title']}*\n"
        if task.get('description'):
            desc = task['description']
            text += f"   _{desc[:50]}{'...' if len(desc) > 50 else ''}_\n"
        if task['subtasks']:
            completed = sum(1 for s in task['subtasks'] if s['status'] == 'done')
            text += f"   📌 {completed}/{len(task['subtasks'])}\n"
        text += "\n"
        
        task_title = task['title']
        button_text = f"{status_emoji} {task_title[:30]}..."
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"task_{task['id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(t(lang, 'bot_prev_page'), callback_data=f"tasks_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(t(lang, 'bot_next_page'), callback_data=f"tasks_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def task_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split('_')[-1])
    await show_tasks(update, context, page=page)
    
    return MAIN_MENU

async def task_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    task_id = int(query.data.split('_')[1])
    user_id = context.user_data.get('user_id')
    
    tasks = get_user_tasks(user_id)
    task = next((t for t in tasks if t['id'] == task_id), None)
    
    if not task:
        await query.edit_message_text("Error")
        return MAIN_MENU
    
    status_emoji = "✅" if task['computed_status'] == 'done' else "⏳" if task['computed_status'] == 'in_progress' else "📋"
    task_priority = task.get('priority', 'medium')
    priority_emoji = "🟢" if task_priority == 'low' else "🟡" if task_priority == 'medium' else "🔴"
    
    text = f"{t(lang, 'bot_task_details')}\n\n"
    text += f"{status_emoji} *{task['title']}*\n\n"
    
    if task.get('description'):
        text += f"📄 {task['description']}\n\n"
    
    priority_key = f"priority_{task_priority}"
    priority_text = t(lang, priority_key)
    text += f"🎯 {t(lang, 'priority')}: {priority_emoji} {priority_text}\n"
    
    if task.get('deadline'):
        text += f"📅 {t(lang, 'deadline')}: {task['deadline']}\n"
    
    created_date = task['created_at'][:10] if isinstance(task['created_at'], str) else str(task['created_at'])[:10]
    text += f"📅 {t(lang, 'created')}: {created_date}\n"
    
    if task['subtasks']:
        text += f"\n📌 {t(lang, 'subtasks')}:\n"
        for subtask in task['subtasks']:
            sub_emoji = "✅" if subtask['status'] == 'done' else "⏳"
            text += f"  {sub_emoji} {subtask['title']}\n"
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_toggle_status'), callback_data=f"toggle_{task_id}")],
        [InlineKeyboardButton(t(lang, 'bot_delete'), callback_data=f"delete_{task_id}")],
        [InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_tasks")]
    ]
    
    if task['subtasks']:
        subtask_buttons = []
        for subtask in task['subtasks']:
            sub_emoji = "✅" if subtask['status'] == 'done' else "⏳"
            subtask_title = subtask['title'][:25]
            subtask_buttons.append([InlineKeyboardButton(
                f"{sub_emoji} {subtask_title}",
                callback_data=f"togglesub_{subtask['id']}"
            )])
        keyboard = subtask_buttons + keyboard
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return MAIN_MENU

async def toggle_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    lang = context.user_data.get('lang', 'en')
    task_id = int(query.data.split('_')[1])
    user_id = context.user_data.get('user_id')
    
    toggle_task(task_id, user_id)
    
    await query.answer(t(lang, 'bot_task_completed'))
    
    query.data = f"task_{task_id}"
    await task_detail_handler(update, context)
    
    return MAIN_MENU

async def toggle_subtask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    lang = context.user_data.get('lang', 'en')
    subtask_id = int(query.data.split('_')[1])
    user_id = context.user_data.get('user_id')
    
    toggle_subtask(subtask_id, user_id)
    
    db = db_handler.get_connection()
    cursor = db_handler.execute(db, 'SELECT parent_id FROM tasks WHERE id = %s', (subtask_id,))
    parent = db_handler.fetchone(cursor)
    cursor.close()
    db_handler.close(db)
    
    await query.answer(t(lang, 'bot_task_completed'))
    
    if parent:
        parent_id = parent['parent_id']
        query.data = f"task_{parent_id}"
        await task_detail_handler(update, context)
    
    return MAIN_MENU

async def delete_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    task_id = int(query.data.split('_')[1])
    user_id = context.user_data.get('user_id')
    
    tasks = get_user_tasks(user_id)
    task = next((t for t in tasks if t['id'] == task_id), None)
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_yes'), callback_data=f"confirmdelete_{task_id}")],
        [InlineKeyboardButton(t(lang, 'bot_no'), callback_data=f"task_{task_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    confirm_text = t(lang, 'bot_confirm_delete').format(task['title'])
    await query.edit_message_text(confirm_text, reply_markup=reply_markup)
    
    return MAIN_MENU

async def confirm_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    lang = context.user_data.get('lang', 'en')
    task_id = int(query.data.split('_')[1])
    user_id = context.user_data.get('user_id')
    
    delete_task(task_id, user_id)
    
    await query.answer(t(lang, 'bot_task_deleted'))
    await show_tasks(update, context, page=0)
    
    return MAIN_MENU

async def start_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    context.user_data['new_task'] = {}
    
    await update.callback_query.edit_message_text(t(lang, 'bot_enter_task_title'))
    
    return ADD_TASK_TITLE

async def add_task_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    context.user_data['new_task']['title'] = update.message.text.strip()
    
    await update.message.reply_text(t(lang, 'bot_enter_task_description'))
    
    return ADD_TASK_DESCRIPTION

async def add_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    if update.message.text.strip() != '/skip':
        context.user_data['new_task']['description'] = update.message.text.strip()
    else:
        context.user_data['new_task']['description'] = ''
    
    keyboard = [
        [InlineKeyboardButton("🟢 " + t(lang, 'priority_low'), callback_data="priority_low")],
        [InlineKeyboardButton("🟡 " + t(lang, 'priority_medium'), callback_data="priority_medium")],
        [InlineKeyboardButton("🔴 " + t(lang, 'priority_high'), callback_data="priority_high")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(t(lang, 'bot_select_priority'), reply_markup=reply_markup)
    
    return ADD_TASK_PRIORITY

async def add_task_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    priority = query.data.split('_')[1]
    
    context.user_data['new_task']['priority'] = priority
    
    await query.edit_message_text(t(lang, 'bot_enter_deadline'))
    
    return ADD_TASK_DEADLINE

async def add_task_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    if update.message.text.strip() == '/skip':
        context.user_data['new_task']['deadline'] = None
    else:
        try:
            deadline = update.message.text.strip()
            datetime.strptime(deadline, '%Y-%m-%d')
            context.user_data['new_task']['deadline'] = deadline
        except ValueError:
            await update.message.reply_text(t(lang, 'bot_invalid_date'))
            return ADD_TASK_DEADLINE
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_yes'), callback_data="subtasks_yes")],
        [InlineKeyboardButton(t(lang, 'bot_no'), callback_data="subtasks_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(t(lang, 'bot_add_subtasks'), reply_markup=reply_markup)
    
    return ADD_TASK_SUBTASKS

async def add_task_subtasks_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    choice = query.data.split('_')[1]
    
    if choice == 'no':
        task_data = context.user_data['new_task']
        user_id = context.user_data['user_id']
        
        add_task(
            user_id,
            task_data['title'],
            task_data.get('description', ''),
            task_data['priority'],
            task_data.get('deadline'),
            []
        )
        
        await query.edit_message_text(t(lang, 'bot_task_added'))
        
        keyboard = [[InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(t(lang, 'bot_main_menu'), reply_markup=reply_markup)
        
        return MAIN_MENU
    else:
        context.user_data['new_task']['subtasks'] = []
        context.user_data['subtask_count'] = 1
        
        subtask_prompt = t(lang, 'bot_enter_subtask').format(1)
        await query.edit_message_text(subtask_prompt)
        
        return ADD_SUBTASK_INPUT

async def add_subtask_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    if update.message.text.strip() == '/done':
        task_data = context.user_data['new_task']
        user_id = context.user_data['user_id']
        
        add_task(
            user_id,
            task_data['title'],
            task_data.get('description', ''),
            task_data['priority'],
            task_data.get('deadline'),
            task_data.get('subtasks', [])
        )
        
        await update.message.reply_text(t(lang, 'bot_task_added'))
        
        keyboard = [[InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(t(lang, 'bot_main_menu'), reply_markup=reply_markup)
        
        return MAIN_MENU
    else:
        context.user_data['new_task']['subtasks'].append(update.message.text.strip())
        context.user_data['subtask_count'] += 1
        
        next_count = context.user_data['subtask_count']
        subtask_prompt = t(lang, 'bot_enter_subtask').format(next_count)
        await update.message.reply_text(subtask_prompt)
        
        return ADD_SUBTASK_INPUT

async def show_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_period_day'), callback_data="stats_day")],
        [InlineKeyboardButton(t(lang, 'bot_period_week'), callback_data="stats_week")],
        [InlineKeyboardButton(t(lang, 'bot_period_month'), callback_data="stats_month")],
        [InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        t(lang, 'bot_stats_period'),
        reply_markup=reply_markup
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    period = query.data.split('_')[1]
    user_id = context.user_data.get('user_id')
    
    stats = get_stats(user_id, period)
    stats_text = format_stats_text(stats, lang, period)
    
    keyboard = [[InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return MAIN_MENU

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    
    keyboard = [
        [InlineKeyboardButton(t(lang, 'bot_change_language'), callback_data="settings_language")],
        [InlineKeyboardButton(t(lang, 'bot_logout'), callback_data="settings_logout")],
        [InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        t(lang, 'bot_settings'),
        reply_markup=reply_markup
    )

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang = context.user_data.get('lang', 'en')
    action = query.data.split('_')[1]
    
    if action == 'language':
        keyboard = [
            [InlineKeyboardButton("🇬🇧 EN", callback_data="setlang_en"),
             InlineKeyboardButton("🇷🇺 RU", callback_data="setlang_ru"),
             InlineKeyboardButton("🇺🇿 UZ", callback_data="setlang_uz")],
            [InlineKeyboardButton(t(lang, 'bot_back'), callback_data="menu_settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            t(lang, 'bot_select_language'),
            reply_markup=reply_markup
        )
    elif action == 'logout':
        keyboard = [
            [InlineKeyboardButton(t(lang, 'bot_yes'), callback_data="confirm_logout")],
            [InlineKeyboardButton(t(lang, 'bot_no'), callback_data="menu_settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            t(lang, 'bot_confirm_logout'),
            reply_markup=reply_markup
        )
    
    return MAIN_MENU

async def set_language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    new_lang = query.data.split('_')[1]
    context.user_data['lang'] = new_lang
    
    await query.answer(t(new_lang, 'bot_change_language'))
    await show_main_menu(update, context)
    
    return MAIN_MENU

async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    lang = context.user_data.get('lang', 'en')
    
    context.user_data.clear()
    context.user_data['lang'] = lang
    
    keyboard = [
        [InlineKeyboardButton("🇬🇧 EN", callback_data="lang_en"),
         InlineKeyboardButton("🇷🇺 RU", callback_data="lang_ru"),
         InlineKeyboardButton("🇺🇿 UZ", callback_data="lang_uz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.answer(t(lang, 'bot_logout'))
    await query.edit_message_text(
        "🌐 Choose language / Выберите язык / Tilni tanlang:",
        reply_markup=reply_markup
    )
    
    return LANGUAGE_SELECT

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'en')
    context.user_data.clear()
    await update.message.reply_text(t(lang, 'bot_cancel'))
    return ConversationHandler.END

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    return await start(update, context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LANGUAGE_SELECT: [
                CallbackQueryHandler(language_selected, pattern=r'^lang_')
            ],
            AUTH_CHOICE: [
                CallbackQueryHandler(auth_choice, pattern=r'^auth_')
            ],
            LOGIN_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)
            ],
            LOGIN_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)
            ],
            REGISTER_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_username)
            ],
            REGISTER_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)
            ],
            MAIN_MENU: [
                CallbackQueryHandler(menu_handler, pattern=r'^menu_'),
                CallbackQueryHandler(task_page_handler, pattern=r'^tasks_page_'),
                CallbackQueryHandler(task_detail_handler, pattern=r'^task_\d+$'),
                CallbackQueryHandler(toggle_task_handler, pattern=r'^toggle_\d+$'),
                CallbackQueryHandler(toggle_subtask_handler, pattern=r'^togglesub_'),
                CallbackQueryHandler(delete_task_handler, pattern=r'^delete_'),
                CallbackQueryHandler(confirm_delete_handler, pattern=r'^confirmdelete_'),
                CallbackQueryHandler(show_stats, pattern=r'^stats_(day|week|month)'),
                CallbackQueryHandler(settings_handler, pattern=r'^settings_'),
                CallbackQueryHandler(set_language_handler, pattern=r'^setlang_'),
                CallbackQueryHandler(logout_handler, pattern=r'^confirm_logout'),
            ],
            ADD_TASK_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_title)
            ],
            ADD_TASK_DESCRIPTION: [
                MessageHandler(filters.TEXT, add_task_description)
            ],
            ADD_TASK_PRIORITY: [
                CallbackQueryHandler(add_task_priority, pattern=r'^priority_')
            ],
            ADD_TASK_DEADLINE: [
                MessageHandler(filters.TEXT, add_task_deadline)
            ],
            ADD_TASK_SUBTASKS: [
                CallbackQueryHandler(add_task_subtasks_choice, pattern=r'^subtasks_')
            ],
            ADD_SUBTASK_INPUT: [
                MessageHandler(filters.TEXT, add_subtask_input)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', restart)
        ],
        allow_reentry=True,
    )
    
    application.add_handler(conv_handler)
    
    db_type = 'PostgreSQL' if db_handler.use_postgresql else 'SQLite'
    print(f"Bot started successfully! (Using {db_type})")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()