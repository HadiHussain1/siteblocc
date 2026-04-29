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
        candidate_path = os.path.join(app.config["UPLOAD_FOLDER"], hero_image_path)
        if os.path.exists(candidate_path):
            return redirect(url_for("client_static", filename=hero_image_path))

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
    if request.path.startswith(("/client_static/", "/static/", "/project_favicon", "/site.webmanifest")):
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

    if value.startswith("uploads/"):
        candidate_path = os.path.join(BASE_DIR, "static", value)
        if os.path.exists(candidate_path):
            return f"client_static/{value}"
        return ""

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
        ctx["ORDER_CTA"] = load_html("layout/ordering_cta.html")
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


@app.route('/api/create-payment-intent', methods=['POST'])
def create_payment_intent():
    """Create a Stripe PaymentIntent only — no order written to DB yet.
    Order is created in /api/stripe/finalize-order after card is charged."""
    if not PROJECT_ID:
        return jsonify({"error": "Project not configured"}), 503

    data = request.get_json(silent=True) or {}
    order_total = data.get("order_total")

    if order_total is None:
        return jsonify({"error": "Missing order_total"}), 400
    try:
        order_total = float(order_total)
        if order_total <= 0:
            return jsonify({"error": "Invalid order total"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid order total"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT stripe_account_id, stripe_enabled FROM projects WHERE id=%s LIMIT 1", (PROJECT_ID,))
    project = cursor.fetchone()
    cursor.close()
    conn.close()

    if not project or not project.get("stripe_enabled") or not project.get("stripe_account_id"):
        return jsonify({"error": "Payments not enabled for this restaurant"}), 400

    account_id = project["stripe_account_id"]
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(round(order_total * 100)),
            currency="aud",
            on_behalf_of=account_id,
            transfer_data={"destination": account_id},
            metadata={"project_id": str(PROJECT_ID)},
        )
        return jsonify({"client_secret": intent.client_secret, "payment_intent_id": intent.id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/stripe/finalize-order', methods=['POST'])
def finalize_stripe_order():
    """Called after confirmCardPayment succeeds. Verifies payment with Stripe,
    then creates the order in the DB and returns the order_number."""
    if not PROJECT_ID:
        return jsonify({"error": "Project not configured"}), 503

    data = request.get_json(silent=True) or {}
    payment_intent_id = (data.get("payment_intent_id") or "").strip()

    if not payment_intent_id:
        return jsonify({"error": "Missing payment_intent_id"}), 400

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except Exception:
        return jsonify({"error": "Could not verify payment"}), 400

    if intent.status != "succeeded":
        return jsonify({"error": "Payment not confirmed by Stripe"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Ensure payment_intent_id column exists
    cursor.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='orders' AND COLUMN_NAME='payment_intent_id'""")
    if not cursor.fetchone()["COUNT(*)"]:
        cursor.execute("ALTER TABLE orders ADD COLUMN payment_intent_id VARCHAR(255) NULL")
        conn.commit()

    # Idempotency check
    cursor.execute("SELECT order_number FROM orders WHERE payment_intent_id=%s LIMIT 1", (payment_intent_id,))
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        conn.close()
        return jsonify({"order_number": existing["order_number"]})

    cursor.execute("SELECT COALESCE(MAX(id), 0) AS last_id FROM orders")
    last_id = (cursor.fetchone() or {}).get("last_id") or 0
    order_number = str(last_id + 1)

    order_total = float(data.get("order_total") or (intent.amount / 100))
    is_delivery  = 1 if data.get("is_delivery") else 0

    cursor.execute("""
        INSERT INTO orders
            (project_id, order_number, items, total, payment_method, payment_status, status,
             name, surname, phone, email, note, is_delivery, delivery_address, delivery_status,
             payment_intent_id)
        VALUES (%s,%s,%s,%s,'stripe','paid','received',%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        PROJECT_ID,
        order_number,
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
        payment_intent_id,
    ))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"order_number": order_number})


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
    cursor = conn.cursor(dictionary=True)

    # --- THEME ---
    cursor.execute("""
        SELECT primary_color, secondary_color, background_color
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

    # --- DETAILS ---
    cursor.execute("""
        SELECT address, phone, slogan, contact_email, operating_hours, hero_image, hero_image_path,
               delivery_pay_online, delivery_pay_on_delivery
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

    cursor.close()
    conn.close()

    favicon_url = url_for('project_favicon')

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
        "hero_image_css": f'url("/{hero_image_path}")' if hero_image_path else "none"
    }
