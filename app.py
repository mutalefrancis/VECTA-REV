import os, sqlite3, datetime
# Added send_from_directory for PWA support
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image

app = Flask(__name__)
app.secret_key = "myway_v2_2026_secure"
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# --- RENDER DATABASE PERSISTENCE FIX ---
# This ensures the database file is found regardless of where Render runs the script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS landlords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, phone TEXT UNIQUE, password TEXT)""")
        
        conn.execute("""CREATE TABLE IF NOT EXISTS boarding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            landlord_id INTEGER,
            name TEXT, location TEXT, price INTEGER,
            phone TEXT, institution TEXT, distance TEXT,
            images TEXT, map_url TEXT, amenities TEXT,
            verified INTEGER DEFAULT 1,
            clicks INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Available',
            FOREIGN KEY(landlord_id) REFERENCES landlords(id))""")

        conn.execute("""CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT UNIQUE, 
            map_url TEXT)""") 
        conn.commit()

init_db()

def save_img(file):
    try:
        if not file or file.filename == '': return None
        # Convert to WebP for faster PWA loading
        name = f"{os.urandom(3).hex()}_{secure_filename(file.filename.rsplit('.', 1)[0])}.webp"
        path = os.path.join(app.config['UPLOAD_FOLDER'], name)
        img = Image.open(file)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((800, 800)) 
        img.save(path, "WEBP", quality=70)
        return name
    except: return None

# --- CORE ROUTES ---

@app.route('/sw.js')
def serve_sw():
    # Serves the service worker from the root directory
    return send_from_directory(BASE_DIR, 'sw.js')

@app.route("/")
def index():
    school = request.args.get('school', 'All Institutions')
    conn = get_db()
    if school == 'All Institutions' or not school:
        houses = conn.execute("SELECT * FROM boarding ORDER BY status ASC, id DESC").fetchall()
    else:
        houses = conn.execute("SELECT * FROM boarding WHERE institution LIKE ? ORDER BY status ASC, id DESC", (f'%{school}%',)).fetchall()
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    return render_template("index.html", houses=houses, schools=schools, selected_school=school)

@app.route("/track_click/<int:id>")
def track_click(id):
    conn = get_db()
    conn.execute("UPDATE boarding SET clicks = clicks + 1 WHERE id = ?", (id,))
    conn.commit()
    house = conn.execute("SELECT phone FROM boarding WHERE id = ?", (id,)).fetchone()
    if house:
        clean_p = house['phone'].replace(' ', '').replace('+', '').replace('-', '')
        return redirect(f"https://wa.me/{clean_p}")
    return redirect(url_for('index'))

# --- ADMIN ROUTES ---

@app.route("/admin", methods=["GET", "POST"])
def admin():
    # Logout landlord if they try to access admin
    if 'lid' in session:
        session.clear() 

    if request.method == "POST":
        if request.form.get('pass') == "202601": 
            session.clear()
            session['admin_auth'] = True
            return redirect(url_for('admin_console'))
        flash("UNAUTHORIZED ACCESS", "danger")
    return render_template("admin_login.html")

@app.route("/admin_console")
def admin_console():
    if not session.get('admin_auth'): 
        return redirect(url_for('admin'))
    conn = get_db()
    houses = conn.execute("SELECT * FROM boarding ORDER BY status ASC, id DESC").fetchall()
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    return render_template("admin_console.html", houses=houses, schools=schools)

@app.route("/admin/add_school", methods=["POST"])
def add_school():
    if not session.get('admin_auth'): 
        return redirect(url_for('admin'))
    name = request.form.get('school_name', '').strip()
    s_map = request.form.get('school_map', '').strip() 
    if name:
        conn = get_db()
        try:
            conn.execute("INSERT INTO schools (name, map_url) VALUES (?, ?)", (name, s_map))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("School already exists!")
    return redirect(url_for('admin_console'))

# --- LANDLORD ROUTES ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM landlords WHERE phone = ? AND password = ?",
                                (request.form.get('phone'), request.form.get('password'))).fetchone()
        if user:
            session.clear() 
            session['lid'], session['lname'] = user['id'], user['name']
            return redirect(url_for('dashboard'))
        flash("Invalid Credentials", "danger")
    return render_template("landlord_login.html")

@app.route("/dashboard")
def dashboard():
    if 'lid' not in session: return redirect(url_for('login'))
    conn = get_db()
    houses = conn.execute("SELECT * FROM boarding WHERE landlord_id = ? ORDER BY id DESC", (session['lid'],)).fetchall()
    total_clicks = sum(h['clicks'] for h in houses) if houses else 0
    return render_template("landlord_dashboard.html", houses=houses, count=len(houses), total_clicks=total_clicks)

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if 'lid' not in session and not session.get('admin_auth'): 
        return redirect(url_for('login'))
    
    conn = get_db()
    if request.method == "POST":
        files = request.files.getlist('photos')
        saved_files = [save_img(f) for f in files if f]
        imgs = ",".join([img for img in saved_files if img])
        
        landlord_id = session.get('lid') or 0
        amenities = " • ".join(request.form.getlist('amenities')) or "Standard Room"
        schools_list = ", ".join(request.form.getlist('schools'))

        conn.execute("""INSERT INTO boarding (landlord_id, name, location, price, phone, institution, distance, images, map_url, amenities, status)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (landlord_id, request.form.get('name'), request.form.get('location'), request.form.get('price'),
                      request.form.get('phone'), schools_list, request.form.get('distance'), imgs, 
                      request.form.get('map_url'), amenities, 'Available'))
        conn.commit()
        return redirect(url_for('admin_console' if session.get('admin_auth') else 'dashboard'))
        
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    return render_template("landlord_upload.html", schools=schools)

@app.route("/toggle_status/<int:id>")
def toggle_status(id):
    conn = get_db()
    house = conn.execute("SELECT * FROM boarding WHERE id = ?", (id,)).fetchone()
    if house:
        new_status = 'Full' if house['status'] == 'Available' else 'Available'
        conn.execute("UPDATE boarding SET status = ? WHERE id = ?", (new_status, id))
        conn.commit()
    return redirect(request.referrer or url_for('index'))

@app.route("/landlord/edit_house/<int:id>", methods=["GET", "POST"])
def edit_house(id):
    if 'lid' not in session: return redirect(url_for('login'))
    conn = get_db()
    house = conn.execute("SELECT * FROM boarding WHERE id = ? AND landlord_id = ?", (id, session['lid'])).fetchone()
    if request.method == "POST":
        conn.execute("UPDATE boarding SET name=?, price=?, location=?, status=? WHERE id=?",
                     (request.form.get('name'), request.form.get('price'), request.form.get('location'), request.form.get('status'), id))
        conn.commit()
        return redirect(url_for('dashboard'))
    return render_template("edit_house.html", house=house)

@app.route("/landlord/delete_house/<int:id>")
def landlord_delete_house(id):
    if 'lid' not in session: return redirect(url_for('login'))
    conn = get_db()
    conn.execute("DELETE FROM boarding WHERE id = ? AND landlord_id = ?", (id, session['lid']))
    conn.commit()
    return redirect(url_for('dashboard'))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Use environment variable for Render Port
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)