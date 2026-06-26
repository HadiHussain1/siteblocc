# === DO NOT TOUCH ===
from flask import Flask, request, jsonify, render_template, render_template_string, send_from_directory, flash, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import mysql.connector
import os, json, re
from flask import session, redirect, url_for, request, flash
from datetime import datetime
import stripe
from flask_mail import Mail, Message
from markupsafe import Markup
import secrets, random, string
from dotenv import load_dotenv
load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

app = Flask(__name__)
CORS(app)
app.secret_key = "CLIENT_SECRET"

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Hadi!2008",
        database="saas_builder"
    )


app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'info@dinebloc.com')


# Initialize Flask-Mail
mail = Mail(app)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WIZARD_DIR = os.path.dirname(os.path.dirname(BASE_DIR))  # Go up 2 levels to website_wizard/
MODULE_DIR = os.path.join(WIZARD_DIR, "module_library", "html")


@app.route('/client_static/<path:filename>')
def client_static(filename):
    return send_from_directory(
        os.path.join(BASE_DIR, 'static'),
        filename
    )


@app.route('/uploads/<path:filename>')
def uploads(filename):
    uploads_dir = os.path.join(os.path.dirname(BASE_DIR), 'uploads')
    return send_from_directory(uploads_dir, filename)


@app.route('/favicon.ico')
def favicon_ico():
    return ("", 204)


@app.route('/project_favicon')
def project_favicon():
    if not PROJECT_ID:
        return ("", 204)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT d.image, s.logo_path
        FROM project_details d
        LEFT JOIN project_settings s ON s.project_id = d.project_id
        WHERE d.project_id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    details = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    image_data = details.get('image')
    if image_data:
        if isinstance(image_data, memoryview):
            image_data = image_data.tobytes()

        return Response(image_data, mimetype=detect_image_mime(image_data))

    logo_path = (details.get("logo_path") or "").strip().lstrip("/")
    if logo_path.startswith("static/"):
        logo_path = logo_path.split("static/", 1)[1]

    if logo_path:
        candidate_path = os.path.join(BASE_DIR, "static", logo_path)
        if os.path.exists(candidate_path):
            return redirect(url_for("client_static", filename=logo_path))

    return ("", 204)


@app.route('/project_hero_image')
def project_hero_image():
    if not PROJECT_ID:
        return ("", 204)

    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT hero_image, hero_image_path
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    details = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    hero_image_path = (details.get("hero_image_path") or "").strip().lstrip("/")
    if hero_image_path.startswith("static/"):
        hero_image_path = hero_image_path.split("static/", 1)[1]
    if hero_image_path.startswith("client_static/"):
        hero_image_path = hero_image_path.split("client_static/", 1)[1]

    if hero_image_path:
        upload_root = app.config["UPLOAD_FOLDER"]
        static_root = os.path.join(BASE_DIR, "static")
        asset_candidates = []

        if hero_image_path.startswith(("uploads/", "generated/")):
            asset_candidates.append((hero_image_path, os.path.join(static_root, hero_image_path)))
        else:
            asset_candidates.extend([
                (f"uploads/{hero_image_path}", os.path.join(upload_root, hero_image_path)),
                (f"generated/{hero_image_path}", os.path.join(static_root, "generated", hero_image_path)),
                (hero_image_path, os.path.join(static_root, hero_image_path)),
            ])

        for asset_path, candidate_path in asset_candidates:
            if os.path.exists(candidate_path):
                return redirect(url_for("client_static", filename=asset_path))

    image_data = details.get("hero_image")
    if isinstance(image_data, memoryview):
        image_data = image_data.tobytes()

    if isinstance(image_data, (bytes, bytearray)) and image_data:
        return Response(image_data, mimetype=detect_image_mime(image_data))

    return ("", 204)


def get_project_branding():
    fallback = {
        "primary_color": "#111827",
        "background_color": "#ffffff",
    }
    if not PROJECT_ID:
        return fallback

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT primary_color, background_color
        FROM project_settings
        WHERE project_id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    row = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    fallback.update({k: v for k, v in row.items() if v})
    return fallback


def format_display_time(value):
    if not value:
        return ""
    raw = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    return raw


@app.route('/site.webmanifest')
def site_webmanifest():
    branding = get_project_branding()
    payload = {
        "name": PROJECT_NAME or "Restaurant",
        "short_name": (PROJECT_NAME or "Restaurant")[:12],
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": branding.get("background_color") or "#ffffff",
        "theme_color": branding.get("primary_color") or "#111827",
        "icons": [
            {
                "src": url_for("project_favicon"),
                "sizes": "192x192"
            },
            {
                "src": url_for("project_favicon"),
                "sizes": "512x512"
            }
        ]
    }
    return Response(json.dumps(payload), mimetype="application/manifest+json")


# Upload folder (static/uploads)
app.config.setdefault('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'static', 'uploads'))
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# read configuration, but template folder may not have a real project_config
try:
    with open(os.path.join(BASE_DIR, "project_config.json"), "r") as f:
        PROJECT_CONFIG = json.load(f)
except FileNotFoundError:
    PROJECT_CONFIG = {
        "PROJECT_ID": None,
        "PROJECT_NAME": "Template",
        "SLOGAN": ""
    }

PROJECT_ID = PROJECT_CONFIG.get("PROJECT_ID")
PROJECT_NAME = PROJECT_CONFIG.get("PROJECT_NAME")
SLOGAN = PROJECT_CONFIG.get("SLOGAN")
PROJECT_SLUG = PROJECT_CONFIG.get("PROJECT_SLUG") or re.sub(r'[^a-z0-9]+', '-', (PROJECT_NAME or '').lower()).strip('-')


def is_standalone_project_deployed():
    if not PROJECT_ID:
        return False

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT is_deployed
        FROM projects
        WHERE id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    project = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    return str(project.get("is_deployed") or "").strip().lower() in {"1", "true", "yes", "on"}


@app.before_request
def block_undeployed_standalone_site():
    if request.path.startswith(("/client_static/", "/static/", "/uploads/", "/project_favicon", "/site.webmanifest", "/favicon.ico")):
        return
    if not is_standalone_project_deployed():
        return "Website not deployed yet.", 404



ADMIN_PASSWORD = 'ajax9997cli23##45'


def ensure_project_details_featured_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'featured_html'
    """)
    has_column = cursor.fetchone()[0] > 0

    if not has_column:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN featured_html LONGTEXT NULL
        """)
        conn.commit()

    cursor.close()


def ensure_project_details_hero_image_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'hero_image'
    """)
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN hero_image LONGBLOB NULL
        """)
        conn.commit()
    elif (row[0] or "").lower() != "longblob":
        cursor.execute("""
            ALTER TABLE project_details
            MODIFY COLUMN hero_image LONGBLOB NULL
        """)
        conn.commit()

    cursor.close()


def ensure_project_details_hero_image_path_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'hero_image_path'
    """)
    has_column = cursor.fetchone()[0] > 0

    if not has_column:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN hero_image_path VARCHAR(255) NULL
        """)
        conn.commit()

    cursor.close()


def is_truthy_db(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def db_flag(value, default=1):
    if value is None:
        return int(default)
    return 1 if is_truthy_db(value) else 0

def ensure_project_settings_css_theme_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_settings'
          AND COLUMN_NAME = 'css_theme'
    """)
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "ALTER TABLE project_settings ADD COLUMN css_theme VARCHAR(20) NOT NULL DEFAULT 'main'"
        )
    conn.commit()
    cursor.close()


def ensure_delivery_settings_columns(conn):
    cursor = conn.cursor()
    cols = {
        "delivery_pay_online":      "ADD COLUMN delivery_pay_online TINYINT(1) NOT NULL DEFAULT 1",
        "delivery_pay_on_delivery": "ADD COLUMN delivery_pay_on_delivery TINYINT(1) NOT NULL DEFAULT 1",
    }
    for col, sql in cols.items():
        cursor.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='project_details' AND COLUMN_NAME=%s""", (col,))
        if not cursor.fetchone()[0]:
            cursor.execute(f"ALTER TABLE project_details {sql}")
    conn.commit()
    cursor.close()

def load_html(path):
    full_path = os.path.join(MODULE_DIR, path)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def get_default_featured_section_html():
    return load_html("sections/featured.html")


def sanitize_featured_html(html):
    content = (html or "").strip()
    if not content:
        return ""

    content = re.sub(r"^```(?:html)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(r"<script\b[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style\b[^>]*>.*?</style>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"\sstyle=(['\"]).*?\1", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"\son[a-z-]+=(['\"]).*?\1", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = content.strip()

    if not content:
        return ""

    if "<section" not in content.lower():
        content = (
            '<section class="featured"><div class="container">'
            f"{content}</div></section>"
        )
    elif 'class="featured"' not in content.lower() and "class='featured'" not in content.lower():
        content = re.sub(
            r"<section\b",
            '<section class="featured"',
            content,
            count=1,
            flags=re.IGNORECASE
        )

    return content


def get_featured_section_html(saved_html=None):
    cleaned = sanitize_featured_html(saved_html)
    return cleaned or get_default_featured_section_html()


def normalize_hero_image_value(hero_image):
    if not hero_image:
        return ""

    if isinstance(hero_image, memoryview):
        hero_image = hero_image.tobytes()

    if isinstance(hero_image, (bytes, bytearray)):
        return bytes(hero_image)

    return str(hero_image).strip()


def resolve_hero_image_path(hero_image):
    value = normalize_hero_image_value(hero_image)

    if not value or isinstance(value, (bytes, bytearray)):
        return ""

    value = value.lstrip("/")
    if value.startswith("static/"):
        value = value.split("static/", 1)[1]
    if value.startswith("client_static/"):
        value = value.split("client_static/", 1)[1]

    if value.startswith("uploads/"):
        candidate_path = os.path.join(BASE_DIR, "static", value)
        if os.path.exists(candidate_path):
            return f"client_static/{value}"
        return ""

    if value.startswith("generated/"):
        candidate_path = os.path.join(BASE_DIR, "static", value)
        if os.path.exists(candidate_path):
            return f"client_static/{value}"
        return ""

    upload_candidate = os.path.join(app.config["UPLOAD_FOLDER"], value)
    if os.path.exists(upload_candidate):
        return f"client_static/uploads/{value}"

    generated_candidate = os.path.join(BASE_DIR, "static", "generated", value)
    if os.path.exists(generated_candidate):
        return f"client_static/generated/{value}"

    static_candidate = os.path.join(BASE_DIR, "static", value)
    if os.path.exists(static_candidate):
        return f"client_static/{value}"

    return value


def get_hero_image_css(hero_image):
    image_value = normalize_hero_image_value(hero_image)

    if isinstance(image_value, (bytes, bytearray)):
        image_url = url_for("project_hero_image")
    else:
        image_url = image_value

    return f'url("{image_url}")' if image_url else "none"


NAV_RULES = [
    ("menu", "Menu", None),  # Always
    ("about", "About", None),
    ("contact", "Contact", None),

    ("catering", "Catering", "catering_system"),
    ("reservations", "Reservations", "booking_reservation_system"),
]


ADMIN_ROUTE = '/admin-92f8b3c4e1'


def build_navbar(modules):
    links = []

    for route, label, required_module in NAV_RULES:
        if required_module is None or modules.get(required_module):
            # resolve URL server-side so templates receive real hrefs
            try:
                href = url_for(route)
            except Exception:
                href = '#'
            links.append(f'<a href="{href}">{label}</a>')

    return "\n".join(links)


def get_project_modules(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM project_modules
        WHERE project_id = %s
    """, (project_id,))

    modules = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    return modules



# === CORE PAGES (ALWAYS) ===

def build_page_context(modules):
    ctx = {
        "NAVBAR": build_navbar(modules),

        "ORDER_CTA": "",
        "CART_ICON": "",
        "CART_SIDEBAR": "",

        "FEATURED_SECTION": load_html("sections/featured.html"),
        "MAP_SECTION": load_html("sections/map.html"),
        "CATERING_TEASER": "",
        "RESERVATIONS_TEASER": "",
        # SCRIPTS will be rendered below with module-specific script tags
        "SCRIPTS": "",
    }

    if modules.get("online_ordering_system"):
        ctx["ORDER_CTA"] = load_html("layout/ordering_cta.html").replace("{{MENU_LINK}}", "/menu")
        ctx["CART_ICON"] = load_html("layout/cart_icon.html")
        ctx["CART_SIDEBAR"] = load_html("layout/cart_sidebar.html")

    # Menu data should always load; ordering extras stay conditional.
    ordering_scripts = f'<script src="{url_for("client_static", filename="js/menu.js")}"></script>'

    if modules.get("online_ordering_system"):
        ordering_scripts = (
            f'<script src="{url_for("client_static", filename="js/cart.js")}"></script>'
            f'{ordering_scripts}'
        )

    # Mark script strings as safe to avoid Jinja auto-escaping
    ordering_scripts = Markup(ordering_scripts)

    # Render the scripts layout with the module-specific tags
    ctx["SCRIPTS"] = render_template_string(
        load_html("layout/scripts.html"),
        ORDERING_SCRIPTS=ordering_scripts,
        MEMBER_SCRIPTS=Markup("")
    )

    return ctx


@app.route("/menu")
def menu():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template("menu.html", **ctx)


@app.route("/table/<int:table_id>")
def table_order(table_id):
    modules = get_project_modules(PROJECT_ID)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, table_number, capacity FROM restaurant_tables "
        "WHERE id=%s AND project_id=%s AND is_active=1 LIMIT 1",
        (table_id, PROJECT_ID)
    )
    table_row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not table_row:
        return redirect(url_for("menu"))

    table_label = (table_row.get("table_number") or f"T{table_id}").strip()

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules),
        "table_id": table_id,
        "table_label": table_label,
        "table_capacity": table_row.get("capacity", 2),
    }

    return render_template("table_order.html", **ctx)


@app.route("/about")
def about():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    # page-specific DB
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT story
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    data = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    ctx["story"] = data.get("story", "")

    return render_template("about.html", **ctx)


@app.route("/contact")
def contact():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template("contact.html", **ctx)



@app.route('/catering', methods=['GET', 'POST'])
def catering():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    if request.method == "POST":
        name = request.form.get("name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        event_date = request.form.get("event_date")
        guests = request.form.get("guests")
        event_type = request.form.get("event_type")
        details = request.form.get("details")

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO catering_inquiries
            (project_id, name, phone, email, event_date, guests, event_type, details)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (PROJECT_ID, name, phone, email, event_date, guests, event_type, details))

        conn.commit()
        cursor.close()
        conn.close()

        msg = Message(
            subject=f"Catering Inquiry — {PROJECT_NAME}",
            recipients=[ctx.get("CONTACT_EMAIL", "your@email.com")],
            body=f"""
New Catering Inquiry

Name: {name}
Phone: {phone}
Email: {email}
Date: {event_date}
Guests: {guests}
Type: {event_type}

Details:
{details}
"""
        )

        mail.send(msg)

        ctx["success"] = True

    return render_template("catering.html", **ctx)


@app.route('/reservations', methods=['GET', 'POST'])
def reservations():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        reservation_date = request.form.get("reservation_date")
        reservation_time = request.form.get("reservation_time")
        guests = request.form.get("guests")
        special_requests = request.form.get("special_requests")

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO reservations
            (project_id, name, email, phone, reservation_date, reservation_time, guests, special_requests)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (PROJECT_ID, name, email, phone, reservation_date, reservation_time, guests, special_requests))

        conn.commit()
        cursor.close()
        conn.close()

        msg = Message(
            subject=f"Reservation Confirmation — {PROJECT_NAME}",
            recipients=[email],
            body=f"""
Reservation Confirmation

Name: {name}
Date: {reservation_date}
Time: {reservation_time}
Guests: {guests}

Special Requests:
{special_requests}
"""
        )

        mail.send(msg)

        ctx["success"] = True

    return render_template("reservations.html", **ctx)



@app.route("/api/table-availability")
def table_availability():
    date_str = request.args.get("date", "")
    try:
        party_size = int(request.args.get("party_size", 1))
    except ValueError:
        return jsonify({"error": "Invalid party_size"}), 400
    try:
        conn = get_db_connection()
        slots = _get_available_slots(PROJECT_ID, date_str, party_size, conn)
        conn.close()
        return jsonify({"slots": slots})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/table-book", methods=["POST"])
def table_book():
    data = request.get_json(force=True) or {}
    required = ['date', 'start_time', 'party_size', 'customer_name', 'customer_email', 'customer_phone']
    if any(not data.get(f) for f in required):
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM table_booking_config WHERE project_id=%s LIMIT 1", (PROJECT_ID,))
        cfg = cursor.fetchone() or {}
        duration_min = int(cfg.get('slot_duration_minutes', 60))

        from datetime import datetime, timedelta
        start_dt = datetime.strptime(f"{data['date']} {data['start_time']}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration_min)
        end_str = end_dt.strftime('%H:%M')

        cursor.execute(
            "SELECT * FROM restaurant_tables WHERE project_id=%s AND is_active=1 AND capacity>=%s ORDER BY capacity ASC",
            (PROJECT_ID, int(data['party_size']))
        )
        candidates = cursor.fetchall()
        chosen_table = None
        for t in candidates:
            cursor.execute(
                "SELECT id FROM table_bookings WHERE table_id=%s AND booking_date=%s AND status='confirmed' "
                "AND NOT (end_time<=%s OR start_time>=%s)",
                (t['id'], data['date'], data['start_time'], end_str)
            )
            if not cursor.fetchone():
                chosen_table = t; break

        if not chosen_table:
            return jsonify({"success": False, "error": "No tables available for that slot. Please choose another time."}), 409

        import secrets as _sec
        ref = _sec.token_hex(6).upper()

        cursor.execute("""
            INSERT INTO table_bookings
                (project_id, table_id, booking_date, start_time, end_time, party_size,
                 customer_name, customer_email, customer_phone, special_requests, high_chairs_needed, booking_ref)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            PROJECT_ID, chosen_table['id'], data['date'], data['start_time'], end_str,
            int(data['party_size']), data['customer_name'].strip(), data['customer_email'].strip(),
            data['customer_phone'].strip(), (data.get('special_requests') or '').strip(),
            int(data.get('high_chairs_needed', 0)), ref
        ))
        conn.commit()

        table_label = chosen_table.get('table_number') or f"Table {chosen_table['id']}"
        cust_html = f"""
<div style="font-family:sans-serif;max-width:540px;margin:auto">
  <h2 style="color:#111">Booking Confirmed ✓</h2>
  <p>Hi <strong>{data['customer_name']}</strong>, your table is reserved at <strong>{PROJECT_NAME}</strong>.</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0">
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Date</td><td style="padding:8px">{data['date']}</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Time</td><td style="padding:8px">{data['start_time']} – {end_str}</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Party size</td><td style="padding:8px">{data['party_size']} guests</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Booking ref</td><td style="padding:8px"><strong>{ref}</strong></td></tr>
  </table>
  <p style="color:#555;font-size:0.9rem">Keep your booking reference — you may need it to cancel.</p>
</div>"""
        try:
            msg = Message(subject=f"Table Booking Confirmed – {PROJECT_NAME}", recipients=[data['customer_email']])
            msg.html = cust_html
            mail.send(msg)
        except Exception:
            pass

        return jsonify({"success": True, "booking_ref": ref, "table": table_label, "end_time": end_str})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/table-session-count")
def table_session_count():
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"count": 0})
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE project_id=%s AND table_session_id=%s",
            (PROJECT_ID, session_id)
        )
        row = cursor.fetchone()
        cursor.close(); conn.close()
        return jsonify({"count": int(row["cnt"]) if row else 0})
    except Exception as e:
        return jsonify({"count": 0, "error": str(e)})


def _td_to_str(t):
    from datetime import timedelta as _td, time as _t
    if isinstance(t, _td):
        s = int(t.total_seconds()); return f"{s//3600:02d}:{(s%3600)//60:02d}"
    if isinstance(t, _t): return t.strftime('%H:%M')
    return str(t)[:5]


def _get_available_slots(project_id, date_str, party_size, conn):
    from datetime import datetime, date as _date, timedelta, time as _t
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return []
    dow = target_date.weekday()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM table_booking_config WHERE project_id=%s LIMIT 1", (project_id,))
    cfg = cursor.fetchone()
    if not cfg:
        cursor.close(); return []
    cursor.execute("SELECT * FROM table_booking_hours WHERE project_id=%s AND day_of_week=%s LIMIT 1", (project_id, dow))
    hrs = cursor.fetchone()
    if not hrs or hrs['is_closed']:
        cursor.close(); return []
    cursor.execute("SELECT * FROM restaurant_tables WHERE project_id=%s AND is_active=1 ORDER BY capacity ASC", (project_id,))
    all_tables = cursor.fetchall()
    suitable = [t for t in all_tables if t['capacity'] >= party_size]
    if not suitable:
        cursor.close(); return []
    tid_list = [t['id'] for t in suitable]
    ph = ','.join(['%s'] * len(tid_list))
    cursor.execute(f"SELECT table_id, start_time, end_time FROM table_bookings WHERE table_id IN ({ph}) AND booking_date=%s AND status='confirmed'", tuple(tid_list) + (target_date,))
    booked = cursor.fetchall()
    cursor.execute("SELECT start_time, end_time FROM table_booking_blocked WHERE project_id=%s AND blocked_date=%s", (project_id, target_date))
    blocked = cursor.fetchall()
    cursor.close()

    duration = timedelta(minutes=int(cfg['slot_duration_minutes']))
    def _to_dt(t):
        s = _td_to_str(t); parts = s.split(':')
        return datetime.combine(target_date, _t(int(parts[0]), int(parts[1])))
    open_dt = _to_dt(hrs['open_time'])
    close_dt = _to_dt(hrs['close_time'])
    now = datetime.now()
    lead = timedelta(minutes=int(cfg['booking_lead_minutes']))
    earliest = now + lead
    slots = []
    cur = open_dt
    step = timedelta(minutes=30)
    while cur + duration <= close_dt:
        if target_date == _date.today() and cur < earliest:
            cur += step; continue
        s_str = cur.strftime('%H:%M')
        e_str = (cur + duration).strftime('%H:%M')
        def overlaps(b_start, b_end, s=cur, e=cur+duration):
            bs = _to_dt(b_start); be = _to_dt(b_end); return bs < e and be > s
        is_blocked = any(b['start_time'] is None or overlaps(b['start_time'], b['end_time']) for b in blocked)
        if not is_blocked:
            avail = [t for t in suitable if not any(b['table_id'] == t['id'] and overlaps(b['start_time'], b['end_time']) for b in booked)]
            if avail:
                slots.append({'start': s_str, 'end': e_str, 'tables_available': len(avail), 'smallest_fit': min(t['capacity'] for t in avail)})
        cur += step
    return slots


@app.route("/")
def index():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    # map needs address
    ctx["MAP_SECTION"] = render_template_string(
        load_html("sections/map.html"),
        ADDRESS=ctx["address"],
        MAP_KICKER=ctx.get("MAP_KICKER", "Find Us"),
        MAP_TITLE=ctx.get("MAP_TITLE", "Visit Us")
    )

    if modules.get("catering_system"):
        ctx["CATERING_TEASER"] = render_template_string(
            load_html("sections/catering_teaser.html"),
            CATERING_KICKER=ctx.get("CATERING_KICKER", "Events"),
            CATERING_TITLE=ctx.get("CATERING_TITLE", "Planning a special event?"),
            CATERING_TEXT=ctx.get("CATERING_TEXT", "Explore our catering options for private gatherings, office lunches, and large celebrations."),
            CATERING_LINK=url_for("catering")
        )

    if modules.get("booking_reservation_system"):
        ctx["RESERVATIONS_TEASER"] = render_template_string(
            load_html("sections/reservations_teaser.html"),
            RESERVATIONS_KICKER=ctx.get("RESERVATIONS_KICKER", "Bookings"),
            RESERVATIONS_TITLE=ctx.get("RESERVATIONS_TITLE", "Reserve your table"),
            RESERVATIONS_TEXT=ctx.get("RESERVATIONS_TEXT", "Book ahead and make your visit smooth, easy, and ready when you arrive."),
            RESERVATIONS_LINK=url_for("reservations")
        )

    conn = get_db_connection()
    ensure_project_details_featured_column(conn)
    ensure_project_details_hero_image_column(conn)
    ensure_project_details_hero_image_path_column(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT featured_html, hero_image, hero_image_path
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    featured = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    ctx["FEATURED_SECTION"] = get_featured_section_html(featured.get("featured_html"))
    ctx["hero_image"] = normalize_hero_image_value(featured.get("hero_image"))
    hero_image_asset = resolve_hero_image_path(featured.get("hero_image_path") or featured.get("hero_image"))
    ctx["hero_image_path"] = hero_image_asset or ("project_hero_image" if featured.get("hero_image") else "")
    ctx["hero_image_css"] = f'url("/{ctx["hero_image_path"]}")' if ctx["hero_image_path"] else "none"

    return render_template("index.html", **ctx)


@app.route('/checkout')
def checkout():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template("checkout.html", **ctx)


@app.route('/checkout-instore')
def checkout_instore():
    modules = get_project_modules(PROJECT_ID)

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template("checkout-instore.html", **ctx)


@app.route('/api/stripe/start-checkout', methods=['POST'])
def stripe_start_checkout():
    """Create a Stripe Checkout Session for the restaurant's Express Connect account.
    Stores a pending order in DB, returns the hosted Stripe checkout URL."""
    if not PROJECT_ID:
        return jsonify({"error": "Project not configured"}), 503

    data = request.get_json(silent=True) or {}

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT stripe_account_id, stripe_enabled, project_name FROM projects WHERE id=%s LIMIT 1", (PROJECT_ID,))
    project = cursor.fetchone()

    if not project or not project.get("stripe_enabled") or not project.get("stripe_account_id"):
        cursor.close()
        conn.close()
        return jsonify({"error": "Payments not enabled for this restaurant"}), 400

    # Ensure payment_intent_id column exists
    cursor.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='orders' AND COLUMN_NAME='payment_intent_id'""")
    if not cursor.fetchone()["COUNT(*)"]:
        cursor.execute("ALTER TABLE orders ADD COLUMN payment_intent_id VARCHAR(255) NULL")
        conn.commit()

    # Create pending order
    cursor.execute("SELECT COALESCE(MAX(id), 0) AS last_id FROM orders")
    last_id      = (cursor.fetchone() or {}).get("last_id") or 0
    order_number = str(last_id + 1)
    order_total  = float(data.get("order_total") or 0)
    is_delivery  = 1 if data.get("is_delivery") else 0

    cursor.execute("""
        INSERT INTO orders
            (project_id, order_number, items, total, payment_method, payment_status, status,
             name, surname, phone, email, note, is_delivery, delivery_address, delivery_status)
        VALUES (%s,%s,%s,%s,'stripe','checkout_pending','received',%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        PROJECT_ID, order_number,
        json.dumps(data.get("items") or []),
        order_total,
        str(data.get("name") or "")[:255],
        str(data.get("surname") or "")[:255],
        str(data.get("phone") or "")[:64],
        str(data.get("email") or "")[:255],
        str(data.get("note") or "")[:2000],
        is_delivery,
        str(data.get("delivery_address") or "")[:512] or None,
        "preparing" if is_delivery else None,
    ))
    conn.commit()

    account_id   = project["stripe_account_id"]
    project_name = project.get("project_name", "Restaurant")
    base_url     = request.host_url.rstrip("/")

    try:
        cs = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency":     "aud",
                    "product_data": {"name": f"Order from {project_name}"},
                    "unit_amount":  int(round(order_total * 100)),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/checkout",
            payment_intent_data={
                "on_behalf_of":  account_id,
                "transfer_data": {"destination": account_id},
                "metadata":      {"project_id": str(PROJECT_ID), "order_number": order_number},
            },
            metadata={"project_id": str(PROJECT_ID), "order_number": order_number},
        )
    except Exception as exc:
        cursor.close()
        conn.close()
        return jsonify({"error": str(exc)}), 500

    cursor.execute(
        "UPDATE orders SET payment_intent_id=%s WHERE order_number=%s",
        (cs.id, order_number)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"url": cs.url})


@app.route('/payment-success')
def payment_success():
    session_id           = request.args.get("session_id", "").strip()
    order_number         = request.args.get("order_number", "").strip() or None
    payment_method_param = request.args.get("payment_method", "").strip()
    payment_verified     = False
    used_stripe_checkout = bool(session_id) or payment_method_param == "stripe"

    if session_id:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT order_number, payment_status FROM orders WHERE payment_intent_id=%s LIMIT 1", (session_id,))
        existing = cursor.fetchone()

        if existing and existing["payment_status"] == "paid":
            order_number     = existing["order_number"]
            payment_verified = True
        else:
            try:
                cs = stripe.checkout.Session.retrieve(session_id)
                if cs.payment_status == "paid":
                    on = (cs.metadata or {}).get("order_number", "")
                    pi = cs.payment_intent or ""
                    if on:
                        cursor.execute(
                            "UPDATE orders SET payment_status='paid', payment_intent_id=%s WHERE order_number=%s",
                            (pi, on)
                        )
                        conn.commit()
                        order_number     = on
                        payment_verified = True
            except Exception:
                pass

        cursor.close()
        conn.close()

    ctx = build_global_context({})
    ctx.update({
        "order_number":     order_number,
        "payment_verified": payment_verified,
        "used_stripe_checkout": used_stripe_checkout,
        "payment_method":   payment_method_param,
    })
    return render_template("payment_success.html", **ctx)


def get_contrast(hex_color):
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    luminance = (0.299*r + 0.587*g + 0.114*b)
    return "#000000" if luminance > 128 else "#ffffff"


def lighten(hex_color, factor=0.15):
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def detect_image_mime(image_data):
    if not image_data:
        return "image/png"
    if image_data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_data[:4] == b"GIF8":
        return "image/gif"
    if image_data[:4] == b"\x89PNG":
        return "image/png"
    if image_data[:4] == b"RIFF" and image_data[8:12] == b"WEBP":
        return "image/webp"
    if image_data.lstrip().startswith(b"<?xml") or image_data.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def build_global_context(modules):
    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_column(conn)
    ensure_delivery_settings_columns(conn)
    ensure_project_settings_css_theme_column(conn)
    cursor = conn.cursor(dictionary=True)

    # --- THEME ---
    cursor.execute("""
        SELECT primary_color, secondary_color, background_color, css_theme
        FROM project_settings
        WHERE project_id=%s
    """, (PROJECT_ID,))
    theme = cursor.fetchone() or {}

    bg = theme.get("background_color") or "#111111"
    accent = theme.get("primary_color") or "#2563eb"
    secondary = theme.get("secondary_color") or accent

    accent_hover = lighten(accent)
    bg_contrast = get_contrast(bg)
    accent_contrast = get_contrast(accent)

    _css_theme = (theme.get("css_theme") or "main").strip()
    _valid_themes = {"main", "main2", "main3"}
    theme_css_file = (_css_theme if _css_theme in _valid_themes else "main") + ".css"

    # --- DETAILS ---
    cursor.execute("""
        SELECT address, phone, slogan, contact_email, operating_hours, hero_image, hero_image_path,
               delivery_pay_online, delivery_pay_on_delivery,
               (image IS NOT NULL AND LENGTH(image) > 0) AS has_favicon_blob
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    details = cursor.fetchone() or {}

    address = details.get("address", "")
    phone = details.get("phone", "")
    hero_image_asset = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
    hero_image_path = hero_image_asset or ("project_hero_image" if details.get("hero_image") else "")

    # --- STRIPE ---
    cursor.execute("""
        SELECT stripe_account_id, stripe_enabled
        FROM projects
        WHERE id=%s
        LIMIT 1
    """, (PROJECT_ID,))
    stripe_row = cursor.fetchone() or {}
    stripe_enabled = bool(stripe_row.get("stripe_enabled"))
    stripe_pub_key = STRIPE_PUBLISHABLE_KEY if stripe_enabled else ""

    # --- FAVICON check (logo_path from project_settings) ---
    cursor.execute("""
        SELECT logo_path FROM project_settings WHERE project_id=%s LIMIT 1
    """, (PROJECT_ID,))
    settings_row = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    has_favicon = bool(details.get("has_favicon_blob")) or bool((settings_row.get("logo_path") or "").strip())
    favicon_url = url_for('project_favicon') if has_favicon else ""
    op_hours = None
    raw_operating_hours = details.get("operating_hours", "")
    if raw_operating_hours and raw_operating_hours.strip().startswith("{"):
        try:
            parsed_hours = json.loads(raw_operating_hours)
            op_hours = {}
            for day, entry in parsed_hours.items():
                entry = entry or {}
                op_hours[day] = {
                    "open": bool(entry.get("open")),
                    "from": format_display_time(entry.get("from")),
                    "to": format_display_time(entry.get("to")),
                }
        except Exception:
            op_hours = None

    return {
        # theme
        "primary": bg,
        "accent": accent,
        "secondary": secondary,
        "accent_hover": accent_hover,
        "contrast": bg_contrast,
        "accent_contrast": accent_contrast,

        "theme_bg": bg,
        "theme_accent": accent,
        "theme_accent_hover": accent_hover,
        "theme_contrast": bg_contrast,

        # project
        "project_name": PROJECT_NAME,
        "slogan": details.get("slogan", SLOGAN),
        "PROJECT_SLUG": PROJECT_SLUG,

        # contact
        "address": address,
        "phone": phone,
        "CONTACT_EMAIL": details.get("contact_email"),
        "operating_hours": details.get("operating_hours", ""),
        "op_hours": op_hours,

        # modules
        "MODULES": modules,

        # delivery payment settings
        "delivery_pay_online": db_flag(details.get("delivery_pay_online"), default=1),
        "delivery_pay_on_delivery": db_flag(details.get("delivery_pay_on_delivery"), default=1),

        # stripe
        "stripe_enabled": stripe_enabled,
        "stripe_publishable_key": stripe_pub_key,

        "favicon_url": favicon_url,
        "hero_image": normalize_hero_image_value(details.get("hero_image")),
        "hero_image_path": hero_image_path,
        "hero_image_css": f'url("/{hero_image_path}")' if hero_image_path else "none",

        "theme_css_file": theme_css_file,
    }
