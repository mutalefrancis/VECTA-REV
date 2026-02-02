import os, sqlite3, datetime, uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from PIL import Image

app = Flask(__name__)

# --- JINJA FILTERS ---
@app.template_filter('format_price')
def format_price(value):
    try:
        if value is None or value == "":
            return "0"
        return "{:,}".format(int(float(value)))
    except (ValueError, TypeError):
        return value

app.secret_key = "myway_v2_2026_secure"
app.config['UPLOAD_FOLDER'] = 'static/uploads'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- DATABASE ENGINE ---
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS landlords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, phone TEXT UNIQUE, password TEXT,
            security_question TEXT, security_answer TEXT)""")
        
        conn.execute("""CREATE TABLE IF NOT EXISTS boarding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            landlord_id INTEGER,
            name TEXT, location TEXT, price INTEGER,
            phone TEXT, institution TEXT, distance TEXT,
            images TEXT, map_url TEXT, amenities TEXT,
            verified INTEGER DEFAULT 1,
            clicks INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Available',
            category TEXT DEFAULT 'boarding',
            details TEXT,
            FOREIGN KEY(landlord_id) REFERENCES landlords(id))""")

        conn.execute("""CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT UNIQUE, 
            map_url TEXT)""") 
        
        # Auto-patch database if columns are missing
        patches = {
            "landlords": [("security_question", "TEXT"), ("security_answer", "TEXT")],
            "boarding": [("category", "TEXT DEFAULT 'boarding'"), ("details", "TEXT")]
        }
        for table, cols in patches.items():
            current = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for col_name, col_type in cols:
                if col_name not in current:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        conn.commit()

init_db()

# --- PWA IMAGE OPTIMIZER ---
def save_optimized_image(file, upload_folder):
    """Converts images to WebP and resizes to fix Performance/LCP issues."""
    img = Image.open(file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    # Cap width at 1200px for mobile performance
    max_width = 1200
    if img.width > max_width:
        w_percent = (max_width / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((max_width, h_size), Image.Resampling.LANCZOS)
    
    filename = str(uuid.uuid4()) + ".webp"
    filepath = os.path.join(upload_folder, filename)
    img.save(filepath, "WEBP", quality=75, optimize=True)
    return filename

# --- PUBLIC ROUTES ---
@app.route("/")
def index():
    school = request.args.get('school', 'All Institutions')
    cat = request.args.get('category', 'all')
    conn = get_db()
    query = "SELECT * FROM boarding WHERE 1=1"
    params = []
    if school != 'All Institutions' and school:
        query += " AND institution LIKE ?"
        params.append(f'%{school}%')
    if cat != 'all' and cat:
        query += " AND category = ?"
        params.append(cat)
    query += " ORDER BY status ASC, id DESC"
    houses = conn.execute(query, params).fetchall()
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    return render_template("index.html", houses=houses, schools=schools, selected_school=school, selected_cat=cat)

@app.route("/track_click/<int:id>")
def track_click(id):
    conn = get_db()
    conn.execute("UPDATE boarding SET clicks = clicks + 1 WHERE id = ?", (id,))
    conn.commit()
    h = conn.execute("SELECT * FROM boarding WHERE id = ?", (id,)).fetchone()
    if h:
        num = h['phone'].replace(' ', '').replace('+', '')
        if num.startswith('0'): num = '260' + num[1:]
        msg = f"Interested in {h['name']} ({h['category']}). Is it available?"
        return redirect(f"https://wa.me/{num}?text={msg.replace(' ', '%20')}")
    return redirect(url_for('index'))

# --- AUTH ROUTES ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM landlords WHERE phone = ? AND password = ?",
                               (request.form.get('phone'), request.form.get('password'))).fetchone()
        if user:
            session['lid'], session['lname'] = user['id'], user['name']
            return redirect(url_for('dashboard'))
        flash("Invalid credentials!")
    return render_template("landlord_login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        conn = get_db()
        try:
            conn.execute("INSERT INTO landlords (name, phone, password, security_question, security_answer) VALUES (?,?,?,?,?)",
                (request.form.get('name'), request.form.get('phone'), request.form.get('password'), 
                 request.form.get('security_question'), request.form.get('security_answer').lower().strip()))
            conn.commit()
            return redirect(url_for('login'))
        except: flash("Phone already exists!")
    return render_template("landlord_register.html")

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    conn = get_db()
    step, user = 1, None
    if request.method == "POST":
        phone = request.form.get('phone')
        user = conn.execute("SELECT * FROM landlords WHERE phone = ?", (phone,)).fetchone()
        if request.form.get('answer'): 
            if user and request.form.get('answer').lower().strip() == user['security_answer']:
                conn.execute("UPDATE landlords SET password = ? WHERE id = ?", 
                             (request.form.get('new_password'), user['id']))
                conn.commit()
                flash("Password updated!")
                return redirect(url_for('login'))
            flash("Incorrect answer.")
            step = 2
        elif user: step = 2
        else: flash("Phone not found."); step = 1
    return render_template("forgot_password.html", step=step, user=user)

# --- MASTER ADMIN ROUTES ---
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == "202601": 
            session['admin_auth'] = True
            return redirect(url_for('admin_console'))
        flash("ACCESS DENIED")
    return render_template("admin_login.html")

@app.route("/admin_console")
def admin_console():
    if not session.get('admin_auth'): return redirect(url_for('admin_login'))
    conn = get_db()
    return render_template("admin_console.html", 
                           houses=conn.execute("SELECT * FROM boarding ORDER BY id DESC").fetchall(),
                           landlords=conn.execute("SELECT * FROM landlords").fetchall(),
                           schools=conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall())

@app.route("/admin/add_school", methods=["POST"])
def add_school():
    if not session.get('admin_auth'): return redirect(url_for('admin_login'))
    conn = get_db()
    try:
        conn.execute("INSERT INTO schools (name, map_url) VALUES (?, ?)", 
                     (request.form.get('school_name'), request.form.get('school_map')))
        conn.commit()
    except: flash("School exists.")
    return redirect(url_for('admin_console'))

@app.route("/admin/delete_school/<int:id>")
def delete_school(id):
    if not session.get('admin_auth'): return redirect(url_for('admin_login'))
    conn = get_db()
    conn.execute("DELETE FROM schools WHERE id = ?", (id,))
    conn.commit()
    return redirect(url_for('admin_console'))

# --- DASHBOARD & MANAGEMENT ---
@app.route("/dashboard")
def dashboard():
    if 'lid' not in session: return redirect(url_for('login'))
    conn = get_db()
    houses = conn.execute("SELECT * FROM boarding WHERE landlord_id = ?", (session['lid'],)).fetchall()
    return render_template("landlord_dashboard.html", houses=houses, count=len(houses),
                           total_clicks=sum(h['clicks'] for h in houses))

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if 'lid' not in session and not session.get('admin_auth'): return redirect(url_for('login'))
    conn = get_db()
    if request.method == "POST":
        imgs = ",".join([save_optimized_image(f, app.config['UPLOAD_FOLDER']) for f in request.files.getlist('photos') if f])
        conn.execute("""INSERT INTO boarding (landlord_id, name, location, price, phone, institution, distance, images, map_url, amenities, category, details) 
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session.get('lid', 0), request.form.get('name'), request.form.get('location'), request.form.get('price'),
             request.form.get('phone'), ", ".join(request.form.getlist('schools')), request.form.get('distance'), 
             imgs, request.form.get('map_url'), " • ".join(request.form.getlist('amenities')), 
             request.form.get('category'), request.form.get('details')))
        conn.commit()
        return redirect(url_for('dashboard'))
    return render_template("landlord_upload.html", schools=conn.execute("SELECT * FROM schools").fetchall())

@app.route("/edit_house/<int:id>", methods=["GET", "POST"])
def edit_house(id):
    if 'lid' not in session and not session.get('admin_auth'): return redirect(url_for('login'))
    conn = get_db()
    if request.method == "POST":
        conn.execute("UPDATE boarding SET name=?, price=?, details=?, category=? WHERE id=?", 
                     (request.form.get('name'), request.form.get('price'), request.form.get('details'), request.form.get('category'), id))
        conn.commit()
        return redirect(url_for('admin_console' if session.get('admin_auth') else 'dashboard'))
    house = conn.execute("SELECT * FROM boarding WHERE id = ?", (id,)).fetchone()
    return render_template("landlord_edit.html", house=house, schools=conn.execute("SELECT * FROM schools").fetchall())

@app.route("/toggle_status/<int:id>")
def toggle_status(id):
    conn = get_db()
    h = conn.execute("SELECT status, category FROM boarding WHERE id = ?", (id,)).fetchone()
    curr, cat = h['status'], h['category']
    if cat == 'sale': new = 'Sold' if curr == 'Available' else 'Available'
    elif cat == 'rent': new = 'Occupied' if curr == 'Available' else 'Available'
    else: new = 'Full' if curr == 'Available' else 'Available'
    conn.execute("UPDATE boarding SET status = ? WHERE id = ?", (new, id))
    conn.commit()
    return redirect(request.referrer)

@app.route("/delete_house/<int:id>")
def delete_house(id):
    conn = get_db()
    if session.get('admin_auth'):
        conn.execute("DELETE FROM boarding WHERE id = ?", (id,))
    elif 'lid' in session:
        conn.execute("DELETE FROM boarding WHERE id = ? AND landlord_id = ?", (id, session['lid']))
    conn.commit()
    return redirect(request.referrer)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)