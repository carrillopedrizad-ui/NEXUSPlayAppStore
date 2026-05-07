import os
import sqlite3
import uuid
import zipfile
import shutil
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Los templates siempre están en la subcarpeta 'templates'
template_dir = os.path.join(BASE_DIR, 'templates')
static_dir = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = 'nexusplay_super_secret_key'

# En producción (Render), usar /tmp para archivos subidos
if os.environ.get('RENDER'):
    UPLOAD_FOLDER = '/tmp/uploads'
else:
    UPLOAD_FOLDER = 'uploads'

GAMES_FOLDER = os.path.join(UPLOAD_FOLDER, 'games')
IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'images')
UNZIPPED_FOLDER = os.path.join(UPLOAD_FOLDER, 'games_unzipped')

app.config['GAMES_FOLDER'] = GAMES_FOLDER
app.config['IMAGES_FOLDER'] = IMAGES_FOLDER
app.config['UNZIPPED_FOLDER'] = UNZIPPED_FOLDER

ALLOWED_EXTENSIONS = {'exe', 'apk', 'zip', 'png', 'jpg', 'jpeg', 'gif', 'html'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

for folder in [GAMES_FOLDER, IMAGES_FOLDER, UNZIPPED_FOLDER]:
    os.makedirs(folder, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, 'nexusplay.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def update_db_schema():
    conn = get_db_connection()
    try:
        conn.execute('ALTER TABLE games ADD COLUMN category TEXT DEFAULT "Acción"')
        conn.execute('ALTER TABLE games ADD COLUMN original_filename TEXT DEFAULT ""')
        conn.execute('ALTER TABLE games ADD COLUMN bg_color TEXT DEFAULT "#0b0d14"')
        conn.execute('ALTER TABLE games ADD COLUMN downloads INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute('ALTER TABLE games ADD COLUMN user_id INTEGER')
    except sqlite3.OperationalError:
        pass

    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER,
            filename TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER,
            username TEXT NOT NULL,
            comment_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER,
            score INTEGER NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    ''')
    conn.commit()
    conn.close()

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            developer TEXT NOT NULL,
            description TEXT NOT NULL,
            platform TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            game_filename TEXT NOT NULL,
            category TEXT DEFAULT 'Acción',
            original_filename TEXT DEFAULT '',
            bg_color TEXT DEFAULT '#0b0d14',
            downloads INTEGER DEFAULT 0,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()
    update_db_schema()

init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicia sesión para acceder a esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

CATEGORIES = ['Acción', 'Aventura', 'RPG', 'Terror', 'Plataformas', 'Simulador', 'Herramientas/Apps', 'Otro']

@app.route('/')
def index():
    category_filter = request.args.get('category')
    sort_by = request.args.get('sort', 'newest')
    
    conn = get_db_connection()
    
    query = 'SELECT games.*, IFNULL(AVG(ratings.score), 0) as avg_rating FROM games LEFT JOIN ratings ON games.id = ratings.game_id'
    params = []
    
    if category_filter and category_filter != 'Todas':
        query += ' WHERE category = ?'
        params.append(category_filter)
        
    query += ' GROUP BY games.id'
        
    if sort_by == 'popular':
        query += ' ORDER BY downloads DESC'
    elif sort_by == 'rated':
        query += ' ORDER BY avg_rating DESC'
    else:
        query += ' ORDER BY id DESC'
        
    games = conn.execute(query, params).fetchall()
    conn.close()
    
    return render_template('index.html', games=games, categories=CATEGORIES, current_category=category_filter or 'Todas', current_sort=sort_by)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        hashed_pw = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_pw))
            user_id = cursor.lastrowid
            conn.commit()
            
            session['user_id'] = user_id
            session['username'] = username
            
            flash('¡Cuenta creada exitosamente! Bienvenido a NexusPlay.', 'success')
            return redirect(url_for('index'))
            
        except sqlite3.IntegrityError:
            flash('El nombre de usuario ya existe.', 'error')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    my_games = conn.execute('SELECT * FROM games WHERE user_id = ? ORDER BY id DESC', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('profile.html', user=user, my_games=my_games)

@app.route('/game/<int:game_id>')
def game_details(game_id):
    conn = get_db_connection()
    game = conn.execute('SELECT games.*, IFNULL(AVG(ratings.score), 0) as avg_rating, COUNT(ratings.id) as rating_count FROM games LEFT JOIN ratings ON games.id = ratings.game_id WHERE games.id = ? GROUP BY games.id', (game_id,)).fetchone()
    
    if game is None:
        conn.close()
        return "Juego no encontrado", 404
        
    screenshots = conn.execute('SELECT filename FROM screenshots WHERE game_id = ?', (game_id,)).fetchall()
    comments = conn.execute('SELECT * FROM comments WHERE game_id = ? ORDER BY id DESC', (game_id,)).fetchall()
    conn.close()
            
    return render_template('game.html', game=game, screenshots=screenshots, comments=comments)

@app.route('/game/<int:game_id>/rate', methods=['POST'])
def rate_game(game_id):
    score = request.form.get('score', type=int)
    if score and 1 <= score <= 5:
        conn = get_db_connection()
        conn.execute('INSERT INTO ratings (game_id, score) VALUES (?, ?)', (game_id, score))
        conn.commit()
        conn.close()
        flash('¡Gracias por tu calificación!', 'success')
    return redirect(url_for('game_details', game_id=game_id))

@app.route('/game/<int:game_id>/comment', methods=['POST'])
def comment_game(game_id):
    username = request.form.get('username', 'Anónimo').strip()
    if not username:
        username = 'Anónimo'
    comment_text = request.form.get('comment_text', '').strip()
    
    if comment_text:
        conn = get_db_connection()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute('INSERT INTO comments (game_id, username, comment_text, created_at) VALUES (?, ?, ?, ?)', 
                     (game_id, username, comment_text, created_at))
        conn.commit()
        conn.close()
        flash('Comentario publicado.', 'success')
        
    return redirect(url_for('game_details', game_id=game_id))

@app.route('/play/<int:game_id>')
def play_game(game_id):
    conn = get_db_connection()
    game = conn.execute('SELECT * FROM games WHERE id = ?', (game_id,)).fetchone()
    if game is None or game['platform'] != 'Web (HTML/Zip)':
        conn.close()
        return "Juego no encontrado o no es web.", 404
        
    conn.execute('UPDATE games SET downloads = downloads + 1 WHERE id = ?', (game_id,))
    conn.commit()
    conn.close()
    
    game_uid = game['game_filename'].split('_')[0]
    extract_path = os.path.join(app.config['UNZIPPED_FOLDER'], game_uid)
    
    index_path = None
    if os.path.exists(extract_path):
        for root, dirs, files in os.walk(extract_path):
            if 'index.html' in [f.lower() for f in files]:
                rel_path = os.path.relpath(os.path.join(root, 'index.html'), 'static').replace('\\', '/')
                index_path = rel_path
                break
                
    if not index_path:
        return "Error: No se encontró un archivo 'index.html' dentro del archivo ZIP de este juego.", 404
        
    play_url = url_for('static', filename=index_path)
    return render_template('play.html', game=game, play_url=play_url)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_game():
    if request.method == 'POST':
        title = request.form['title']
        developer = session['username']
            
        description = request.form['description']
        platform = request.form['platform']
        category = request.form['category']
        bg_color = request.form.get('bg_color', '#0b0d14')
            
        if 'image' not in request.files or 'game_file' not in request.files:
            flash('Faltan archivos principales', 'error')
            return redirect(request.url)
            
        image = request.files['image']
        game_file = request.files['game_file']
        
        if image.filename == '' or game_file.filename == '':
            flash('No has seleccionado archivos principales', 'error')
            return redirect(request.url)
            
        if image and allowed_file(image.filename) and game_file and allowed_file(game_file.filename):
            uid = str(uuid.uuid4())[:8]
            
            image_filename = f"{uid}_{secure_filename(image.filename)}"
            original_game_filename = secure_filename(game_file.filename)
            game_filename_saved = f"{uid}_{original_game_filename}"
            
            image.save(os.path.join(app.config['IMAGES_FOLDER'], image_filename))
            game_path = os.path.join(app.config['GAMES_FOLDER'], game_filename_saved)
            game_file.save(game_path)
            
            if platform == 'Web (HTML/Zip)' and game_filename_saved.endswith('.zip'):
                extract_path = os.path.join(app.config['UNZIPPED_FOLDER'], uid)
                os.makedirs(extract_path, exist_ok=True)
                try:
                    with zipfile.ZipFile(game_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_path)
                except zipfile.BadZipFile:
                    flash('El archivo ZIP es inválido.', 'error')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO games (title, developer, description, platform, image_filename, game_filename, category, original_filename, bg_color, user_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, developer, description, platform, image_filename, game_filename_saved, category, original_game_filename, bg_color, session['user_id']))
            game_id = cursor.lastrowid
            
            screenshots = request.files.getlist('screenshots')
            for ss in screenshots:
                if ss and ss.filename != '' and allowed_file(ss.filename):
                    ss_filename = f"ss_{uid}_{secure_filename(ss.filename)}"
                    ss.save(os.path.join(app.config['IMAGES_FOLDER'], ss_filename))
                    cursor.execute('INSERT INTO screenshots (game_id, filename) VALUES (?, ?)', (game_id, ss_filename))
            
            conn.commit()
            conn.close()
            
            flash('¡Juego publicado exitosamente!', 'success')
            return redirect(url_for('game_details', game_id=game_id))
            
    return render_template('upload.html', categories=CATEGORIES)

@app.route('/download/<int:game_id>')
def download_game(game_id):
    conn = get_db_connection()
    game = conn.execute('SELECT * FROM games WHERE id = ?', (game_id,)).fetchone()
    
    if game:
        conn.execute('UPDATE games SET downloads = downloads + 1 WHERE id = ?', (game_id,))
        conn.commit()
        conn.close()
        
        original_name = game['original_filename'] if game['original_filename'] else game['game_filename'][9:]
        return send_from_directory(app.config['GAMES_FOLDER'], game['game_filename'], as_attachment=True, download_name=original_name)
        
    conn.close()
    return "Archivo no encontrado", 404

@app.route('/images/<filename>')
def serve_image(filename):
    return send_from_directory(app.config['IMAGES_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
