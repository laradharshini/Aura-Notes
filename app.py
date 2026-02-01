from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_bcrypt import Bcrypt
import sqlite3
from datetime import datetime, timezone
import json
import os

app = Flask(__name__)
app.secret_key = 'super-secret-key'
bcrypt = Bcrypt(app)
DB_NAME = 'aura_notes.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # SQLite handles simple types. TEXT for strings/json/dates, INTEGER for ids/bools
        
        # Users Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Notes Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            content TEXT,
            tags TEXT,
            color TEXT DEFAULT '#ffffff',
            is_locked INTEGER DEFAULT 0,
            password TEXT,
            expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)
        
        conn.commit()
        conn.close()
        print("Database initialized successfully (SQLite).")
    except Exception as e:
        print(f"Database initialization failed: {e}")

# Initialize DB on start
init_db()

def serialize_note(note):
    # Convert SQLite row to dictionary and handle types
    return {
        '_id': str(note['id']),
        'title': note['title'],
        'content': note['content'],
        'color': note['color'],
        'tags': json.loads(note['tags']) if note['tags'] else [],
        'is_locked': bool(note['is_locked']),
        'expires_at': note['expires_at'], # ISO string directly from DB
        'created_at': note['created_at'],
        'updated_at': note['updated_at']
    }

@app.route('/')
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()
    
    username = user['username'] if user else 'User'
    
    return render_template('index.html', username=username)

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 409
    finally:
        conn.close()

    return jsonify({'message': 'User created successfully'}), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and bcrypt.check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        return jsonify({'message': 'Login successful'}), 200
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'message': 'Logged out successfully'}), 200

# Require login decorator
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    user_id = session['user_id']
    query = request.args.get('q', '').lower()

    conn = get_db_connection()
    
    # Cleanup expired notes first
    cleanup_expired_notes(conn, user_id)
    
    cursor = conn.cursor()
    
    sql = "SELECT * FROM notes WHERE user_id = ?"
    params = [user_id]
    
    if query:
        if query.startswith('tag:'):
            # Explicit tag search
            tag_query = query[4:].strip()
            sql += " AND tags LIKE ?"
            params.append(f'%"{tag_query}"%') 
        else:
            # General search matches title, content, OR tags
            sql += " AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR tags LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%", f'%"{query}"%'])
            
    sql += " ORDER BY updated_at DESC"
    
    cursor.execute(sql, tuple(params))
    notes = cursor.fetchall()
    
    # Process notes (convert Row to dict to modify)
    processed_notes = []
    for note in notes:
        note_dict = dict(note)
        # Redact locked content
        if note_dict['is_locked']:
            note_dict['content'] = 'CONTENT LOCKED • Please unlock to view this note content.'
            note_dict['password'] = None
        processed_notes.append(serialize_note(note_dict))
    
    conn.close()
    
    return jsonify(processed_notes)

@app.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    data = request.json
    user_id = session['user_id']
    
    title = data.get('title', '').strip()
    content = data.get('content', '')
    note_password = data.get('password')
    expires_at = data.get('expires_at')
    color = data.get('color', '#ffffff')
    tags = data.get('tags', [])
    
    if not title:
        import re
        clean_text = re.sub('<[^<]+?>', '', content)
        words = clean_text.split()
        title = ' '.join(words[:5]) + '...' if words else 'Untitled Note'
        
    expiry_date_str = None
    if expires_at:
        # Validate format but store as string provided by frontend (ISO)
        # Ensure 'Z' is handled for python validation if needed, but for storage we keep what works
        # Ideally ensure uniform UTC ISO string
        try:
             # Just checking validity
             datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
             expiry_date_str = expires_at
        except ValueError:
            pass
            
    conn = get_db_connection()
    cursor = conn.cursor()
    
    hashed_pw = None
    is_locked = 0
    if note_password:
        hashed_pw = bcrypt.generate_password_hash(note_password).decode('utf-8')
        is_locked = 1
        
    now_iso = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO notes (user_id, title, content, tags, color, is_locked, password, expires_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, title, content, json.dumps(tags), color, is_locked, hashed_pw, expiry_date_str, now_iso, now_iso))
    
    conn.commit()
    new_id = cursor.lastrowid
    
    cursor.execute("SELECT * FROM notes WHERE id = ?", (new_id,))
    new_note = cursor.fetchone()
    
    conn.close()
    
    return jsonify(serialize_note(new_note)), 201

@app.route('/api/notes/<note_id>', methods=['PUT'])
@login_required
def update_note(note_id):
    data = request.json
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    existing_note = cursor.fetchone()
    
    if not existing_note:
        conn.close()
        return jsonify({'error': 'Note not found'}), 404
        
    updates = []
    params = []
    
    if 'title' in data:
        updates.append("title = ?")
        params.append(data['title'])
    elif 'content' in data and not data.get('title'):
        import re
        clean_text = re.sub('<[^<]+?>', '', data['content'])
        words = clean_text.split()
        new_auto_title = ' '.join(words[:5]) + '...' if words else 'Untitled Note'
        updates.append("title = ?")
        params.append(new_auto_title)
        
    if 'content' in data:
        updates.append("content = ?")
        params.append(data['content'])
        
    if 'color' in data:
        updates.append("color = ?")
        params.append(data['color'])
        
    if 'tags' in data:
        updates.append("tags = ?")
        params.append(json.dumps(data['tags']))
        
    if 'expires_at' in data:
        if data['expires_at'] is None:
            updates.append("expires_at = NULL")
        else:
             updates.append("expires_at = ?")
             params.append(data['expires_at'])

    if 'is_locked' in data:
        updates.append("is_locked = ?")
        params.append(1 if data['is_locked'] else 0)
        if not data['is_locked']:
            updates.append("password = NULL")
            
    if data.get('password'):
        hashed = bcrypt.generate_password_hash(data['password']).decode('utf-8')
        updates.append("password = ?")
        params.append(hashed)
        updates.append("is_locked = 1")
    
    if not updates:
        conn.close()
        return jsonify(serialize_note(existing_note)), 200
        
    updates.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    
    sql = f"UPDATE notes SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
    params.extend([note_id, user_id])
    
    cursor.execute(sql, tuple(params))
    conn.commit()
    
    cursor.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    updated_note = cursor.fetchone()
    conn.close()
    
    return jsonify(serialize_note(updated_note)), 200

@app.route('/api/notes/<note_id>', methods=['DELETE'])
@login_required
def delete_note(note_id):
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    if rows_affected == 0:
        return jsonify({'error': 'Note not found'}), 404
        
    return jsonify({'message': 'Note deleted'}), 200

@app.route('/api/notes/<note_id>/unlock', methods=['POST'])
@login_required
def unlock_note(note_id):
    data = request.json
    password_attempt = data.get('password')
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    note = cursor.fetchone()
    conn.close()
    
    if not note:
        return jsonify({'error': 'Note not found'}), 404
        
    if not note['is_locked']:
        return jsonify(serialize_note(note))
        
    if bcrypt.check_password_hash(note['password'], password_attempt):
        return jsonify(serialize_note(note))
    else:
        return jsonify({'error': 'Invalid password'}), 401

def cleanup_expired_notes(conn, user_id):
    try:
        # SQLite string comparison works for ISO dates
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("DELETE FROM notes WHERE user_id = ? AND expires_at < ?", (user_id, now_iso))
        conn.commit()
    except Exception as e:
        print(f"Cleanup failed: {e}")

if __name__ == '__main__':
    app.run(debug=True)
