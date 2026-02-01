import re
import os
from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session, redirect, url_for

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key-change-me")
bcrypt = Bcrypt(app)

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client.aesthetic_notes
notes_collection = db.notes
users_collection = db.users

def generate_title(content):
    if not content or not content.strip():
        return "Untitled Note"
    
    # Strip HTML tags
    text = re.sub('<[^<]+?>', ' ', content)
    text = text.strip()
    
    if not text:
        return "Untitled Note"
    
    # Get first sentence or first line
    # Split by common sentence terminators or newlines
    first_part = re.split(r'[.!?\n]', text)[0].strip()
    
    if not first_part:
        return "Untitled Note"
        
    # Limit to 7 words
    words = first_part.split()
    if len(words) > 7:
        return ' '.join(words[:7])
    
    return first_part

def cleanup_expired_notes():
    now = datetime.now(timezone.utc)
    result = notes_collection.delete_many({
        'expires_at': {'$ne': None, '$lt': now}
    })
    return result.deleted_count

# Auth Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session.get('username'))

def serialize_doc(doc):
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    
    res = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            res[key] = str(value)
        elif isinstance(value, datetime):
            res[key] = value.isoformat()
        else:
            res[key] = value
    return res

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/signup')
def signup():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('signup.html')

# API Auth Routes
@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    if users_collection.find_one({'username': username}):
        return jsonify({'error': 'Username already exists'}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    user = {
        'username': username,
        'password': hashed_password,
        'created_at': datetime.now(timezone.utc)
    }
    users_collection.insert_one(user)
    return jsonify({'status': 'success'}), 201

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user = users_collection.find_one({'username': username})
    if user and bcrypt.check_password_hash(user['password'], password):
        session['user_id'] = str(user['_id'])
        session['username'] = user['username']
        cleanup_expired_notes()
        return jsonify({'status': 'success', 'username': user['username']})
    
    return jsonify({'error': 'Invalid username or password'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'status': 'success'})

@app.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    cleanup_expired_notes()
    user_id = session['user_id']
    query_param = request.args.get('q', '')
    
    query = {'user_id': user_id}
    
    if query_param:
        regex_query = {'$regex': query_param, '$options': 'i'}
        query['$or'] = [
            {'title': regex_query},
            {'content': regex_query},
            {'tags': regex_query}
        ]
        
    notes = list(notes_collection.find(query).sort('created_at', -1))
    
    # Redact content for locked notes
    for note in notes:
        if note.get('is_locked'):
            note['content'] = 'CONTENT LOCKED • Please unlock to view this note content.'  # Clearer redaction
            # Never send the hashed password to the frontend
            note.pop('password', None)
            
    return jsonify(serialize_doc(notes))

@app.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    data = request.json
    user_id = session['user_id']
    now = datetime.now(timezone.utc)
    
    title = data.get('title', '').strip()
    content = data.get('content', '')
    note_password = data.get('password')
    expires_at = data.get('expires_at') # Should be ISO string or None
    
    # Parse expires_at if provided
    expiry_date = None
    if expires_at:
        try:
            expiry_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        except ValueError:
            pass

    if not title:
        title = generate_title(content)
        
    note = {
        'user_id': user_id,
        'title': title,
        'content': content,
        'color': data.get('color', '#ffffff'),
        'tags': data.get('tags', []),
        'is_locked': bool(note_password),
        'expires_at': expiry_date,
        'created_at': now,
        'updated_at': now
    }
    
    if note_password:
        note['password'] = generate_password_hash(note_password)
    result = notes_collection.insert_one(note)
    note['_id'] = result.inserted_id
    return jsonify(serialize_doc(note)), 201

@app.route('/api/notes/<note_id>', methods=['PUT'])
@login_required
def update_note(note_id):
    data = request.json
    user_id = session['user_id']
    
    title = data.get('title', '').strip()
    content = data.get('content', '')
    note_password = data.get('password')
    expires_at = data.get('expires_at')
    
    # Parse expires_at if provided
    expiry_date = None
    if expires_at:
        try:
            expiry_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    update_data = {
        'content': content,
        'color': data.get('color'),
        'tags': data.get('tags'),
        'expires_at': expiry_date if 'expires_at' in data else None,
        'updated_at': datetime.now(timezone.utc)
    }
    
    # Keep behavior: if expires_at is not in data, don't update it
    if 'expires_at' not in data:
        update_data.pop('expires_at')

    if title:
        update_data['title'] = title
    elif content:
        update_data['title'] = generate_title(content)
        
    if 'is_locked' in data:
        update_data['is_locked'] = data['is_locked']
        if not data['is_locked']:
            update_data['password'] = None
            
    if note_password:
        update_data['password'] = generate_password_hash(note_password)
        update_data['is_locked'] = True
    
    # Remove None values
    update_data = {k: v for k, v in update_data.items() if v is not None}
    
    result = notes_collection.update_one(
        {'_id': ObjectId(note_id), 'user_id': user_id}, 
        {'$set': update_data}
    )
    if result.matched_count == 0:
        return jsonify({'error': 'Note not found or unauthorized'}), 404
        
    return jsonify({'status': 'success'})

@app.route('/api/notes/<note_id>/unlock', methods=['POST'])
@login_required
def unlock_note(note_id):
    data = request.json
    password = data.get('password')
    user_id = session['user_id']
    
    note = notes_collection.find_one({'_id': ObjectId(note_id), 'user_id': user_id})
    if not note:
        return jsonify({'error': 'Note not found'}), 404
        
    if not note.get('is_locked'):
        return jsonify(serialize_doc(note))
        
    if note.get('password') and check_password_hash(note['password'], password):
        return jsonify(serialize_doc(note))
        
    return jsonify({'error': 'Invalid password'}), 401

@app.route('/api/notes/<note_id>', methods=['DELETE'])
@login_required
def delete_note(note_id):
    user_id = session['user_id']
    result = notes_collection.delete_one({'_id': ObjectId(note_id), 'user_id': user_id})
    if result.deleted_count == 0:
        return jsonify({'error': 'Note not found or unauthorized'}), 404
        
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    app.run(debug=True)
