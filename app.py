from flask import (
    Flask, request, jsonify, render_template, render_template_string,
    redirect, url_for, session, flash, send_from_directory, Response, g
)
from flask_mail import Mail, Message

from flask_cors import CORS

import mysql.connector, pymysql
from mysql.connector import errorcode
import stripe

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest

from functools import wraps
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from markupsafe import Markup, escape

import os
import resend
import base64
import json
import time
import re
import shutil
import subprocess
import secrets
import random
import string
import zipfile
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from io import BytesIO
from jinja2 import ChoiceLoader, FileSystemLoader
import logging
logging.basicConfig(level=logging.DEBUG)

from dotenv import load_dotenv
load_dotenv()
from flask import Request

Request.on_json_loading_failed = lambda self, e: None

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
resend.api_key = os.getenv("RESEND_API_KEY")

PAYMENTS_ENABLED = False
TRIAL_APPLICATION_DEADLINE = datetime(2026, 8, 1, 23, 59, 59)
TRIAL_DURATION = timedelta(days=90)
HERO_IMAGE_REGEN_LIMIT = 2
trial_application_deadline = TRIAL_APPLICATION_DEADLINE.strftime("%Y-%m-%d")
DEFAULT_INFO_EMAIL = "info@dinebloc.com"
DEFAULT_NOREPLY_EMAIL = "info@dinebloc.com"


#def require_json(f):
 #   @wraps(f)
  #  def decorated_function(*args, **kwargs):
   #     print(f"DEBUG: require_json check for {request.method} {request.path}, is_json: {request.is_json}")
    #    if request.method in ['POST', 'PUT'] and not request.is_json:
     #       print(f"DEBUG: require_json returning 415 for {request.path}")
      #      return jsonify({"error": "Unsupported Media Type. Content-Type must be application/json"}), 415
       # return f(*args, **kwargs)
    #return decorated_function


def is_trial_application_open(reference_time=None):
    reference_time = reference_time or datetime.now()
    return reference_time <= TRIAL_APPLICATION_DEADLINE


def get_trial_end_date(applied_at=None):
    applied_at = applied_at or datetime.now()
    if not is_trial_application_open(applied_at):
        return None
    return applied_at + TRIAL_DURATION


# LEGACY: application-window trial helper (deprecated)
# def is_trial_active(applied_at=None):
#     if applied_at is None:
#         return is_trial_application_open()
#
#     trial_end = get_trial_end_date(applied_at)
#     return bool(trial_end and datetime.now() <= trial_end)


# TRIAL SYSTEM (Phase 1)
def is_trial_active(client):
    if not client or not client.get("trial_end"):
        return False

    trial_end = client.get("trial_end")
    if isinstance(trial_end, str):
        try:
            trial_end = datetime.fromisoformat(trial_end.replace("Z", ""))
        except ValueError:
            return False

    return trial_end > datetime.now()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.join(BASE_DIR, "module_library", "html")

print("MODULE_DIR:", MODULE_DIR)

from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

app.config["PROPAGATE_EXCEPTIONS"] = False
app.config["DEBUG"] = False
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_USE_TLS=os.getenv("MAIL_USE_TLS") == "True",
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER"),
)

@app.before_request
def debug_request():
    if request.method in ['POST', 'PUT']:
        print(f"DEBUG: {request.method} request to {request.path}")
        print(f"DEBUG: Content-Type: {request.content_type}")
        print(f"DEBUG: Is JSON: {request.is_json}")
        try:
            print(f"DEBUG: Data preview: {request.form.to_dict()}")
        except:
            print("DEBUG: Could not parse form data")

app.jinja_loader = ChoiceLoader([
    FileSystemLoader(os.path.join(BASE_DIR, "templates")),  # builder
    FileSystemLoader(os.path.join(BASE_DIR, "client_template", "templates"))  # client
])

app.secret_key = os.getenv("SECRET_KEY")
mail = Mail(app)

@app.errorhandler(BadRequest)
def handle_bad_request(e):
    print("DEBUG: BadRequest caught:", e)

    # FORCE treat ALL BadRequest as normal form submission
    return render_signup_page(error="Invalid form submission. Please try again."), 200


@app.errorhandler(json.JSONDecodeError)
def handle_json_decode_error(e):
    print(f"DEBUG: JSONDecodeError caught: {e}")
    print(f"DEBUG: Request method: {request.method}")
    print(f"DEBUG: Request path: {request.path}")
    print(f"DEBUG: Content-Type: {request.content_type}")
    print(f"DEBUG: Is JSON: {request.is_json}")
    try:
        print(f"DEBUG: Data: {request.form.to_dict()}")
    except:
        print("DEBUG: Could not read form data")
    return jsonify({"error": "Invalid JSON in request body"}), 400


def send_email(to, subject, html_body, sender=None, reply_to=None):
    try:
        msg = Message(subject, recipients=[to])
        msg.html = html_body

        if sender:
            msg.sender = sender

        if reply_to:
            msg.reply_to = reply_to

        response = resend.Emails.send({
            "from": "Dinebloc <info@dinebloc.com>",
            "to": [to],
            "subject": subject,
            "html": html_body,
            "reply_to": reply_to
        })
        print("RESEND RESPONSE:", response)
        return True

    except Exception as e:
        print("EMAIL ERROR:", str(e))
        logging.exception("Email send failed to %s with subject %s", to, subject)
        return False


def build_email_shell(title, intro, content_html, accent="#0b63ff"):
    safe_title = escape(title or "Dinebloc")
    safe_intro = escape(intro or "")
    return f"""
    <div style="margin:0;padding:32px 16px;background:linear-gradient(180deg,#eef4ff 0%,#f8fafc 100%);font-family:Inter,Arial,sans-serif;color:#0f172a;">
      <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid #dbeafe;box-shadow:0 22px 60px rgba(15,23,42,0.12);">
        <div style="padding:28px 32px;background:linear-gradient(135deg,{accent} 0%,#0f172a 100%);color:#ffffff;">
          <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;opacity:0.82;">Dinebloc</div>
          <h1 style="margin:10px 0 8px;font-size:30px;line-height:1.1;">{safe_title}</h1>
          <p style="margin:0;font-size:15px;line-height:1.65;opacity:0.92;">{safe_intro}</p>
        </div>
        <div style="padding:30px 32px;">
          {content_html}
        </div>
      </div>
    </div>
    """


def build_signup_verification_email_html(verify_link, name=None):
    safe_name = escape((name or "").strip() or "there")
    safe_link = escape(verify_link)
    content_html = f"""
    <p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#334155;">Hi {safe_name}, thanks for signing up to Dinebloc. Your account is almost ready.</p>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#334155;">Verify your email to activate your dashboard, continue your setup, and lock in your free trial access before <strong>August 1, 2026</strong>.</p>
    <div style="margin:24px 0;">
      <a href="{safe_link}" style="display:inline-block;padding:14px 24px;border-radius:12px;background:linear-gradient(135deg,#0b63ff,#1d4ed8);color:#ffffff;text-decoration:none;font-weight:700;">Verify &amp; Activate Account</a>
    </div>
    <div style="padding:18px 20px;border-radius:18px;background:#f8fafc;border:1px solid #e2e8f0;">
      <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">What happens next</div>
      <ul style="margin:12px 0 0;padding-left:18px;color:#334155;line-height:1.8;">
        <li>Your Dinebloc account becomes active.</li>
        <li>You can access the dashboard and start building your restaurant site.</li>
        <li>Your free trial remains active until August 1, 2026.</li>
        <li>No payment is required to complete verification.</li>
      </ul>
    </div>
    <p style="margin:18px 0 0;font-size:13px;line-height:1.7;color:#64748b;">If you did not create this account, you can ignore this email.</p>
    """
    return build_email_shell(
        "Verify your Dinebloc account",
        "Activate your account to access your dashboard and begin your free trial setup.",
        content_html
    )


def build_onboarding_email_html(client_name=None):
    safe_name = escape((client_name or "").strip() or "there")
    content_html = f"""
    <p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#334155;">Hi {safe_name}, your Dinebloc account is now active and your free trial is ready.</p>
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:22px 0;">
      <div style="padding:18px;border-radius:18px;background:#eff6ff;border:1px solid #bfdbfe;">
        <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;">Trial</div>
        <div style="margin-top:8px;font-size:22px;font-weight:800;color:#0f172a;">Active now</div>
        <div style="margin-top:6px;font-size:14px;color:#334155;">Ends on <strong>August 1, 2026</strong></div>
      </div>
      <div style="padding:18px;border-radius:18px;background:#f8fafc;border:1px solid #e2e8f0;">
        <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#475569;">Payments</div>
        <div style="margin-top:8px;font-size:22px;font-weight:800;color:#0f172a;">$0 upfront</div>
        <div style="margin-top:6px;font-size:14px;color:#334155;">No payments are required to begin your trial.</div>
      </div>
    </div>
    <div style="padding:20px;border-radius:20px;background:#fff7ed;border:1px solid #fed7aa;">
      <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#9a3412;">How orders work during the trial</div>
      <ul style="margin:12px 0 0;padding-left:18px;color:#7c2d12;line-height:1.8;">
        <li>Orders come through your dashboard and by email.</li>
        <li>Your restaurant should call the customer shortly after the order comes in to confirm it.</li>
        <li>Payment is made in-store or upon pickup.</li>
        <li>Customers should keep their phone available after ordering.</li>
      </ul>
    </div>
    <div style="margin-top:20px;padding:20px;border-radius:20px;background:#f8fafc;border:1px solid #e2e8f0;">
      <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Recommended next steps</div>
      <ul style="margin:12px 0 0;padding-left:18px;color:#334155;line-height:1.8;">
        <li>Create your first project and complete your restaurant details.</li>
        <li>Upload your menu and check the featured homepage content.</li>
        <li>Review your contact details and pickup or booking settings.</li>
        <li>Deploy your site when you are ready to go live.</li>
      </ul>
    </div>
    <p style="margin:18px 0 0;font-size:14px;line-height:1.75;color:#475569;">If you need help while setting up, reply to our support team and we can help you get your site ready faster.</p>
    """
    return build_email_shell(
        "Welcome to Dinebloc - Free Trial Active",
        "Your account is verified and your trial is active. Here is what to expect next.",
        content_html,
        accent="#2563eb"
    )


def build_password_reset_email_html(reset_link):
    safe_link = escape(reset_link)
    content_html = f"""
    <p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#334155;">We received a request to reset your Dinebloc password.</p>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#334155;">Use the secure button below to choose a new password for your account.</p>
    <div style="margin:24px 0;">
      <a href="{safe_link}" style="display:inline-block;padding:14px 24px;border-radius:12px;background:linear-gradient(135deg,#0b63ff,#1d4ed8);color:#ffffff;text-decoration:none;font-weight:700;">Reset Password</a>
    </div>
    <p style="margin:0;font-size:13px;line-height:1.7;color:#64748b;">If you did not request this change, you can ignore this email and your password will stay the same.</p>
    """
    return build_email_shell(
        "Reset your Dinebloc password",
        "Choose a new password using the secure reset link below.",
        content_html
    )


def get_subdomain():
    host = request.host.split(":")[0]  # remove port if any
    parts = host.split(".")

    if len(parts) >= 3:
        return parts[0]  # slug.dinebloc.com → slug

    return None


PASSWORD_RULES = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z\d]).{8,}$")


def build_signup_captcha_svg(text):
    width = 220
    height = 64
    palette = ["#0b63ff", "#ff3c3c", "#1e293b", "#2563eb", "#0f172a"]
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" rx="14" fill="#f8fbff"/>'
    ]

    for _ in range(7):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        color = random.choice(palette)
        pieces.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-opacity="0.18" stroke-width="1.5"/>'
        )

    for index, char in enumerate(text):
        x = 26 + (index * 28) + random.randint(-2, 2)
        y = 40 + random.randint(-5, 5)
        rotate = random.randint(-18, 18)
        color = random.choice(palette)
        pieces.append(
            f'<text x="{x}" y="{y}" font-family="Inter, Arial, sans-serif" font-size="28" font-weight="700" '
            f'fill="{color}" transform="rotate({rotate} {x} {y})">{char}</text>'
        )

    for _ in range(60):
        cx = random.randint(0, width)
        cy = random.randint(0, height)
        r = random.randint(1, 2)
        color = random.choice(palette)
        pieces.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" fill-opacity="0.14"/>'
        )

    pieces.append("</svg>")
    svg = "".join(pieces)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def refresh_signup_captcha():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(random.choice(alphabet) for _ in range(6))
    session["signup_captcha_answer"] = code.lower()
    session["signup_captcha_image"] = build_signup_captcha_svg(code)
    session["signup_form_started_at"] = time.time()


def render_signup_page(error=None, success=False):
    refresh_signup_captcha()
    return render_template(
        "sign-up.html",
        error=error,
        success=success,
        captcha_image=session.get("signup_captcha_image", "")
    )


def render_login_page(error=None, reset_message=None):
    return render_template("login.html", error=error, reset_message=reset_message)


def is_project_deployed(project):
    return str((project or {}).get("is_deployed") or "").strip().lower() in {"1", "true", "yes", "on"}


def is_project_deploying(project):
    return str((project or {}).get("is_deploying") or "").strip().lower() in {"1", "true", "yes", "on"}


def is_project_live(project):
    return is_project_deployed(project) and not is_project_deploying(project)


def is_strong_password(password):
    return bool(password and PASSWORD_RULES.match(password))



def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306))
    )


def ensure_worker_password_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'workers'
          AND COLUMN_NAME = 'password_visible'
    """)
    has_column = cursor.fetchone()[0] > 0

    if not has_column:
        cursor.execute("""
            ALTER TABLE workers
            ADD COLUMN password_visible VARCHAR(255) NULL
        """)
        conn.commit()

    cursor.close()


def ensure_questions_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(150),
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_questions_project_id (project_id)
        )
    """)
    conn.commit()
    cursor.close()


def ensure_customer_response_columns(conn):
    cursor = conn.cursor()

    for table_name in ("questions", "catering_inquiries", "reservations"):
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND COLUMN_NAME = 'response'
        """, (table_name,))
        has_column = cursor.fetchone()[0] > 0

        if not has_column:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN response TEXT")

    conn.commit()
    cursor.close()


def ensure_order_columns(conn):
    cursor = conn.cursor()

    order_columns = {
        "note": "ADD COLUMN note LONGTEXT NULL",
        "email": "ADD COLUMN email VARCHAR(255) NULL",
        "payment_status": "ADD COLUMN payment_status VARCHAR(50) NOT NULL DEFAULT 'pending'"
    }

    for column_name, alter_sql in order_columns.items():
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'orders'
              AND COLUMN_NAME = %s
        """, (column_name,))
        has_column = cursor.fetchone()[0] > 0

        if not has_column:
            cursor.execute(f"ALTER TABLE orders {alter_sql}")

    conn.commit()
    cursor.close()


def ensure_project_visits_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_visits (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            path VARCHAR(255),
            ip_address VARCHAR(64),
            visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_project_visits_project_id (project_id),
            INDEX idx_project_visits_visited_at (visited_at)
        )
    """)
    conn.commit()
    cursor.close()


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


def ensure_product_upload_attempts_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'product_upload_attempts'
    """)
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN product_upload_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0
        """)
        conn.commit()

    cursor.close()


def ensure_projects_deployment_column(conn):
    cursor = conn.cursor()
    for column_name, alter_sql in (
        ("is_deployed", "ADD COLUMN is_deployed BOOL NOT NULL DEFAULT FALSE"),
        ("is_deploying", "ADD COLUMN is_deploying BOOL NOT NULL DEFAULT FALSE"),
    ):
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'projects'
              AND COLUMN_NAME = %s
        """, (column_name,))
        has_column = cursor.fetchone()[0] > 0

        if not has_column:
            cursor.execute(f"ALTER TABLE projects {alter_sql}")
            conn.commit()

    cursor.close()


def get_project_settings(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT primary_color, secondary_color, background_color, logo_path
        FROM project_settings
        WHERE project_id=%s
        LIMIT 1
    """, (project_id,))
    settings = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    return settings


def is_truthy_db(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def get_project_pay_in_store(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT pay_in_store
        FROM project_details
        WHERE project_id = %s
        LIMIT 1
    """, (project_id,))
    row = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    return is_truthy_db(row.get("pay_in_store"))


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


def ensure_project_details_hero_image_attempts_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'hero_image_regen_attempts'
    """)
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN hero_image_regen_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0
        """)
        conn.commit()

    cursor.close()


def ensure_project_details_hero_image_history_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'hero_image_history'
    """)
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN hero_image_history LONGTEXT NULL
        """)
        conn.commit()
    elif (row[0] or "").lower() not in {"text", "mediumtext", "longtext", "json"}:
        cursor.execute("""
            ALTER TABLE project_details
            MODIFY COLUMN hero_image_history LONGTEXT NULL
        """)
        conn.commit()

    cursor.close()


def get_client_by_project_id(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.*
        FROM clients c
        JOIN projects p ON p.client_id = c.id
        WHERE p.id = %s
        LIMIT 1
    """, (project_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def attach_project_context(project):
    g.project = project
    g.client = None
    g.trial_active = False

    if not project:
        return None

    g.client = get_client_by_project_id(project["id"])
    g.trial_active = is_trial_active(g.client)


def parse_hero_image_history(raw_value):
    if not raw_value:
        return []

    if isinstance(raw_value, memoryview):
        raw_value = raw_value.tobytes()

    if isinstance(raw_value, (bytes, bytearray)):
        raw_value = raw_value.decode("utf-8", errors="ignore")

    try:
        items = json.loads(raw_value) if isinstance(raw_value, str) else list(raw_value)
    except Exception:
        items = [line.strip() for line in str(raw_value).splitlines() if line.strip()]

    seen = set()
    history = []
    for item in items or []:
        normalized = resolve_hero_image_path(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        history.append(normalized)
    return history


def serialize_hero_image_history(items):
    history = parse_hero_image_history(items)
    return json.dumps(history) if history else None

    if g.client and not g.trial_active:
        print(f"Trial expired for client {g.client['id']}")

    return project


def get_project_client_email(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.email
        FROM projects p
        JOIN clients c ON p.client_id = c.id
        WHERE p.id = %s
        LIMIT 1
    """, (project_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return (row or {}).get("email") or DEFAULT_INFO_EMAIL


@app.context_processor
def inject_request_trial_context():
    return {
        "project": getattr(g, "project", None),
        "client": getattr(g, "client", None),
        "trial_active": getattr(g, "trial_active", False),
    }



app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, "uploads")
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -----------------------------
# PUBLIC ROUTES
# -----------------------------


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'client_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function



MODULE_COLUMN_MAP = {
    "online_ordering_system": "online_ordering_system",
    "catering_system": "catering_system",
    "booking_reservation_system": "booking_reservation_system",
    "staff_admin_system": "staff_admin_system",
    "delivery_system": "delivery_system",
    "pos_system": "POS_system",
}


@app.before_request
def detect_project():
    host = request.host.split(":")[0]
    parts = host.split(".")

    if len(parts) >= 3:
        slug = parts[0].strip().lower()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM projects WHERE slug=%s", (slug,))
        project = cursor.fetchone()

        cursor.close()
        conn.close()

        if project:
            attach_project_context(project)
            return

    

@app.route('/client_static/<path:filename>')
def client_static(filename):
    return send_from_directory(
        os.path.join(BASE_DIR, 'client_template', 'static'),
        filename
    )



@app.before_request
def load_modules():
    if hasattr(g, "project"):
        g.modules = get_project_modules(g.project["id"])
    else:
        g.modules = {}


@app.before_request
def enforce_deployment_gate():
    if not hasattr(g, "project") or is_project_deployed(g.project):
        return

    slug = g.project.get("slug")
    allowed_prefixes = (
        "/static/",
        "/client_static/",
        "/uploads/",
        "/project_favicon/",
        "/admin-logout",
        "/dashboard",
        "/delete_project/",
        f"/webconfig/{slug}",
        f"/deploy/{slug}",
        f"/deploy_project/{slug}",
        f"/admin/{slug}/config/update",
        f"/admin/{slug}/get_workers",
        f"/admin/{slug}/create_worker",
        f"/admin/{slug}/delete_worker/",
    )

    if any(request.path.startswith(prefix) for prefix in allowed_prefixes):
        return

    if request.path.startswith(f"/admin/{slug}"):
        if request.method == "GET":
            return redirect(url_for("webconfig", slug=slug))
        return jsonify({
            "success": False,
            "error": "Deploy this project from Config before using admin tools."
        }), 403

    return "Website not deployed yet.", 404


@app.before_request
def log_project_visit():
    if request.method != "GET" or not hasattr(g, "project"):
        return

    if request.path.startswith((
        "/admin/",
        "/dashboard",
        "/builder",
        "/deploy",
        "/client_static/",
        "/static/",
        "/login",
        "/logout"
    )):
        return

    if request.path.startswith("/worker/") or request.path.startswith("/webconfig/"):
        return

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return

    leaf = request.path.rsplit("/", 1)[-1]
    if "." in leaf and request.path != "/":
        return

    conn = get_db_connection()
    ensure_project_visits_table(conn)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO project_visits (project_id, path, ip_address)
        VALUES (%s, %s, %s)
    """, (
        g.project["id"],
        request.path,
        request.headers.get("X-Forwarded-For", request.remote_addr or "")[:64]
    ))
    conn.commit()
    cursor.close()
    conn.close()



@app.route("/")
def index():
    # CLIENT SITE
    if hasattr(g, "project"):
        modules = g.modules

        ctx = {
            **build_page_context(modules),
            **build_global_context(modules)
        }

        ctx["MAP_SECTION"] = render_template_string(
            load_html("sections/map.html"),
            ADDRESS=ctx.get("address", ""),
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
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT featured_html
            FROM project_details
            WHERE project_id=%s
            LIMIT 1
        """, (g.project["id"],))

        featured = cursor.fetchone() or {}
        cursor.close()
        conn.close()

        ctx["FEATURED_SECTION"] = (
            get_featured_section_html(featured.get("featured_html"))
        )

        return render_template("index.html", **ctx)

    # BUILDER SITE
    return render_template("landing.html")  # your builder homepage



# -----------------------------
# AUTHENTICATED ROUTES
# (logic will come later)
# -----------------------------


@app.route('/dashboard')
@login_required
def dashboard():

    conn = get_db_connection()
    ensure_project_visits_table(conn)
    cursor = conn.cursor(dictionary=True)

    client_id = session["client_id"]

    # Total Projects
    cursor.execute("""
        SELECT COUNT(*) as total
        FROM projects
        WHERE client_id=%s
    """, (client_id,))
    total_projects = cursor.fetchone()["total"]

    # Total Modules (sum of enabled modules across all projects)
    cursor.execute("""
        SELECT *
        FROM project_modules pm
        JOIN projects p ON pm.project_id = p.id
        WHERE p.client_id=%s
    """, (client_id,))

    modules_rows = cursor.fetchall()

    total_modules = 0
    MODULE_KEYS = [
        "online_ordering_system",
        "catering_system",
        "booking_reservation_system",
        "staff_admin_system",
        "delivery_system",
        "POS_system"
    ]

    for row in modules_rows:
        for key in MODULE_KEYS:
            if row.get(key):
                total_modules += 1

    # Recent Projects (latest 5)
    cursor.execute("""
        SELECT project_name, created_at
        FROM projects
        WHERE client_id=%s
        ORDER BY created_at DESC
        LIMIT 5
    """, (client_id,))
    recent_projects = cursor.fetchall()



    cursor.execute("""
        SELECT p.project_name, p.slug, p.created_at, p.is_deployed, p.is_deploying,
               s.primary_color, s.secondary_color, s.background_color
        FROM projects p
        LEFT JOIN project_settings s ON p.id = s.project_id
        WHERE p.client_id = %s
        ORDER BY p.created_at DESC
        LIMIT 5
    """, (session["client_id"],))

    projects = cursor.fetchall()
    for project in projects:
        project["project_link_url"] = (
            url_for("admin_panel", slug=project["slug"])
            if is_project_live(project)
            else url_for("webconfig", slug=project["slug"])
        )
        project["project_link_label"] = "Open Main Panel" if is_project_live(project) else "Open Config"

    cursor.execute("""
        SELECT o.total, o.created_at
        FROM orders o
        JOIN projects p ON o.project_id = p.id
        WHERE p.client_id = %s
        ORDER BY o.created_at ASC
    """, (client_id,))
    order_rows = cursor.fetchall()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM project_visits v
        JOIN projects p ON v.project_id = p.id
        WHERE p.client_id = %s
          AND DATE(v.visited_at) = CURDATE()
    """, (client_id,))
    traffic_today = cursor.fetchone()["total"]

    cursor.close()
    conn.close()

    today = datetime.now().date()

    def build_revenue_series(points, period):
        if period == "this_week":
            labels = []
            totals = []
            daily_map = defaultdict(float)
            for row in points:
                created_at = row.get("created_at")
                if not created_at:
                    continue
                day_key = created_at.date()
                if day_key >= today - timedelta(days=6):
                    daily_map[day_key] += float(row.get("total") or 0)

            for offset in range(6, -1, -1):
                day_key = today - timedelta(days=offset)
                labels.append(day_key.strftime("%a"))
                totals.append(round(daily_map.get(day_key, 0), 2))
            return {"label": "Revenue", "labels": labels, "values": totals}

        if period == "this_month":
            labels = []
            totals = []
            daily_map = defaultdict(float)
            for row in points:
                created_at = row.get("created_at")
                if not created_at:
                    continue
                day_key = created_at.date()
                if day_key >= today - timedelta(days=29):
                    daily_map[day_key] += float(row.get("total") or 0)

            for offset in range(29, -1, -1):
                day_key = today - timedelta(days=offset)
                labels.append(day_key.strftime("%d %b"))
                totals.append(round(daily_map.get(day_key, 0), 2))
            return {"label": "Revenue", "labels": labels, "values": totals}

        monthly_map = defaultdict(float)
        for row in points:
            created_at = row.get("created_at")
            if not created_at:
                continue
            month_key = created_at.strftime("%Y-%m")
            monthly_map[month_key] += float(row.get("total") or 0)

        keys = sorted(monthly_map.keys())
        if not keys:
            keys = [today.strftime("%Y-%m")]

        labels = [datetime.strptime(key, "%Y-%m").strftime("%b %Y") for key in keys]
        totals = [round(monthly_map.get(key, 0), 2) for key in keys]
        return {"label": "Revenue", "labels": labels, "values": totals}

    total_revenue = sum(float(row.get("total") or 0) for row in order_rows)
    weekly_map = defaultdict(float)
    for row in order_rows:
        created_at = row.get("created_at")
        if not created_at:
            continue
        year_week = created_at.strftime("%G-W%V")
        weekly_map[year_week] += float(row.get("total") or 0)

    average_weekly_purchase = round(
        total_revenue / len(weekly_map),
        2
    ) if weekly_map else 0.0

    performance_chart = {
        "all_time": build_revenue_series(order_rows, "all_time"),
        "this_week": build_revenue_series(order_rows, "this_week"),
        "this_month": build_revenue_series(order_rows, "this_month"),
    }


    return render_template(
        "dashboard.html",
        total_projects=total_projects,
        total_modules=total_modules,
        recent_projects=recent_projects,
        projects=projects,
        traffic_today=traffic_today,
        average_weekly_purchase=average_weekly_purchase,
        performance_chart=performance_chart
    )



@app.route('/builder')
@login_required
def builder():
    return render_template('builder-wizard.html')


@app.route('/how-it-works')
def how_it_works():
    return render_template('how-it-works.html')


@app.route('/contact')
def contact_page():
    if hasattr(g, "project"):
        return contact()
    return render_template('contact-dinebloc.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if 'client_id' in session:
        return redirect('/dashboard')

    if session.get('worker_id') and session.get('worker_project_slug'):
        return redirect(f"/worker/{session['worker_project_slug']}")

    if request.method == 'POST':
        identifier = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''

        if not identifier or not password:
            return render_login_page(error="Please fill in both username/email and password.")

        normalized_email = identifier.lower()
        normalized_username = identifier.lower()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # =========================
        # 1. CHECK ADMIN
        # =========================
        cursor.execute("SELECT * FROM clients WHERE email=%s", (normalized_email,))
        client = cursor.fetchone()

        if client:
            if not client['is_active']:
                error = "Please verify your email first."
            elif not check_password_hash(client['password_hash'], password):
                error = "Incorrect password."
            else:
                session['client_id'] = client['id']
                session['client_name'] = client['name']

                return redirect('/dashboard')

            cursor.close()
            conn.close()
            return render_login_page(error=error)

        # =========================
        # 2. CHECK WORKER (USERNAME OR EMAIL FIELD)
        # =========================
        cursor.execute("""
            SELECT w.*, p.slug 
            FROM workers w
            JOIN projects p ON w.project_id = p.id
            WHERE w.username=%s
        """, (normalized_username,))

        worker = cursor.fetchone()

        cursor.close()
        conn.close()

        if worker and check_password_hash(worker['password_hash'], password):
            session['worker_id'] = worker['id']
            session['worker_project_slug'] = worker['slug']

            return redirect(f"/worker/{worker['slug']}")

        return render_login_page(error="Invalid credentials")

    return render_login_page(error=error)


@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    email = (request.form.get('email') or '').strip().lower()
    reset_message = "If that email exists, a password reset link has been sent."

    if not email:
        return render_login_page(reset_message=reset_message)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, name, is_active FROM clients WHERE email=%s", (email,))
    client = cursor.fetchone()

    if client and client.get("is_active"):
        token = secrets.token_urlsafe(32)
        cursor.execute(
            "UPDATE clients SET verification_token=%s WHERE id=%s",
            (token, client["id"])
        )
        conn.commit()

        reset_link = url_for('reset_password', token=token, _external=True)
        send_email(
            to=email,
            subject="Reset your password",
            html_body=build_password_reset_email_html(reset_link),
            sender=DEFAULT_INFO_EMAIL
        )

    cursor.close()
    conn.close()

    return render_login_page(reset_message=reset_message)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    error = None
    success = False

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM clients WHERE verification_token=%s", (token,))
    client = cursor.fetchone()

    if not client:
        cursor.close()
        conn.close()
        return "Invalid or expired reset link.", 404

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            error = "Passwords do not match."
        elif not is_strong_password(password):
            error = "Password must be at least 8 characters and include letters, numbers, and symbols."
        else:
            cursor.execute(
                "UPDATE clients SET password_hash=%s, verification_token=NULL WHERE id=%s",
                (generate_password_hash(password), client["id"])
            )
            conn.commit()
            success = True

    cursor.close()
    conn.close()

    return render_template("reset-password.html", error=error, success=success)



@app.route('/sign-up', methods=['GET','POST'])
def sign_up():
    error = None

    if 'client_id' in session:
        return redirect('/dashboard')


    if request.method == 'POST':
        name = request.form.get('name')
        surname = request.form.get('surname')
        phone = request.form.get('phone')
        email = (request.form.get('email') or '').lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        captcha_answer = (request.form.get('captcha_answer') or '').strip().lower()
        honeypot = (request.form.get('company') or '').strip()

        form_started_at = session.get("signup_form_started_at", 0)

        # TRIAL SYSTEM (Phase 1)
        trial_start = datetime.now()
        trial_end = datetime(2026, 8, 1, 0, 0, 0)
        is_legacy = True
        subscription_status = "trial"

        # LEGACY: application-window trial assignment (deprecated)
        # trial_applied_at = datetime.now() if is_trial_application_open() else None
        # trial_ends_at = get_trial_end_date(trial_applied_at) if trial_applied_at else None
        trial_applied_at = trial_start
        trial_ends_at = trial_end

        if honeypot:
            error = "Signup could not be completed."
            return render_signup_page(error=error)

        if time.time() - form_started_at < 2:
            error = "Please take a moment to complete the form."
            return render_signup_page(error=error)

        if password != confirm_password:
            error = "Passwords do not match."
            return render_signup_page(error=error)

        if not is_strong_password(password):
            error = "Password must be at least 8 characters and include letters, numbers, and symbols."
            return render_signup_page(error=error)

        if captcha_answer != session.get("signup_captcha_answer"):
            error = "Captcha answer was incorrect. Please try again."
            return render_signup_page(error=error)
            
        password_hash = generate_password_hash(password)


        conn = get_db_connection()
        ensure_client_trial_columns(conn)
        cursor = conn.cursor(dictionary=True)

        # check duplicates
        cursor.execute("""
            SELECT id FROM clients
            WHERE email=%s OR phone=%s
        """, (email, phone))

        if cursor.fetchone():
            error = "Account with this email or phone already exists."
            return render_signup_page(error=error)

        token = secrets.token_urlsafe(32)

        cursor.execute("""
            INSERT INTO clients (
                name, surname, phone, email, verification_token, is_active, password_hash,
                trial_start, trial_end, is_legacy, subscription_status,
                trial_applied_at, trial_ends_at
            )
            VALUES (%s,%s,%s,%s,%s,FALSE,%s,%s,%s,%s,%s,%s,%s)
        """, (
            name, surname, phone, email, token, password_hash,
            trial_start, trial_end, is_legacy, subscription_status,
            trial_applied_at, trial_ends_at
        ))

        conn.commit()

        verify_link = url_for('verify_account', token=token, _external=True)

        html_body = build_signup_verification_email_html(verify_link, name=name)
        send_email(
            to=email,
            subject="Verify your Dinebloc account",
            html_body=html_body,
            sender=DEFAULT_NOREPLY_EMAIL
        )

        cursor.close()
        conn.close()

        session.pop("signup_captcha_answer", None)
        session.pop("signup_captcha_prompt", None)
        session.pop("signup_form_started_at", None)
        return render_signup_page(success=True)

    return render_signup_page(error=error)


@app.route('/verify/<token>')
def verify_account(token):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, name, email
        FROM clients
        WHERE verification_token=%s
        LIMIT 1
    """, (token,))
    client = cursor.fetchone()

    if not client:
        cursor.close()
        conn.close()
        return "Invalid or expired verification link.", 404

    cursor.close()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE clients
        SET is_active=TRUE,
            verification_token=NULL
        WHERE id=%s
    """, (client["id"],))

    conn.commit()

    cursor.close()
    conn.close()

    send_email(
        to=client["email"],
        subject="Welcome to Dinebloc - Free Trial Active",
        html_body=build_onboarding_email_html(client.get("name")),
        sender=DEFAULT_INFO_EMAIL
    )

    return redirect('/login')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')



@app.route("/create_project", methods=["POST"])
@login_required
def create_project():

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        ensure_projects_deployment_column(db)
        client_id = session["client_id"]

        # -----------------------------
        # BASIC INFO
        # -----------------------------

        project_name = request.form.get("project_name")
        niche = request.form.get("niche")
        slogan = request.form.get("slogan")

        description = request.form.get("description")
        story = request.form.get("story")

        address = (request.form.get("address") or "").strip()
        phone = request.form.get("phone")
        email = request.form.get("email")
        operating_hours = (request.form.get("operating_hours") or "")
        operating_hours = operating_hours.replace("\r\n", "\n").replace("\r", "\n").strip()
        total_cost = int(request.form.get("total_cost") or 65)

        background_color = request.form.get("bg_color")
        primary_color = request.form.get("primary_color")
        secondary_color = request.form.get("secondary_color")

        modules = request.form.getlist("modules")

        slug = re.sub(r'[^a-z0-9]+', '-', project_name.lower()).strip('-')



        # -----------------------------
        # HANDLE LOGO UPLOAD (defer writing into client project folder)
        # -----------------------------

        logo = request.files.get("logo")
        logo_path = None
        logo_bytes = None
        logo_filename = None

        if logo and logo.filename != "":
            logo_filename = f"{secrets.token_hex(8)}_{secure_filename(logo.filename)}"
            # read bytes and defer writing until after client site is generated
            logo_bytes = logo.read()

        project_id = None
        details = {}

        for attempt in range(3):
            try:
                # -----------------------------
                # CREATE PROJECT
                # -----------------------------

                cursor.execute("""
                    INSERT INTO projects (client_id, project_name, slug, niche, is_deployed)
                    VALUES (%s, %s, %s, %s, %s)
                """, (client_id, project_name, slug, niche, False))

                project_id = cursor.lastrowid

                # -----------------------------
                # PROJECT DETAILS
                # -----------------------------

                cursor.execute("""
                    INSERT INTO project_details
                    (project_id, slogan, description, story, address, phone, contact_email, operating_hours, total_cost)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (project_id, slogan, description, story, address, phone, email, operating_hours, total_cost))

                # -----------------------------
                # PROJECT SETTINGS
                # -----------------------------

                cursor.execute("""
                    INSERT INTO project_settings
                    (project_id, background_color, primary_color, secondary_color, logo_path)
                    VALUES (%s, %s, %s, %s, %s)
                """, (project_id, background_color, primary_color, secondary_color, logo_path))

                # Update project_details with raw image blob for favicon preview
                if logo_bytes:
                    try:
                        cursor.execute(
                            "UPDATE project_details SET image=%s WHERE project_id=%s",
                            (logo_bytes, project_id)
                        )
                    except Exception:
                        # DB may not have image column; ignore to avoid blocking project creation
                        pass

                # -----------------------------
                # MODULES
                # -----------------------------

                selected_modules = request.form.getlist("modules")

                module_columns = []
                module_values = []

                for form_value, db_column in MODULE_COLUMN_MAP.items():
                    module_columns.append(db_column)
                    module_values.append(form_value in selected_modules)

                cursor.execute(
                    f"""
                    INSERT INTO project_modules (project_id, {",".join(module_columns)})
                    VALUES (%s, {",".join(["%s"] * len(module_values))})
                    """,
                    (project_id, *module_values)
                )

                cursor.execute("""
                    SELECT address, phone, slogan, contact_email
                    FROM project_details
                    WHERE project_id=%s
                    LIMIT 1
                """, (project_id,))
                details = cursor.fetchone() or {}

                db.commit()
                break
            except mysql.connector.Error as db_error:
                try:
                    db.rollback()
                except Exception:
                    pass

                if db_error.errno not in {errorcode.ER_LOCK_WAIT_TIMEOUT, errorcode.ER_LOCK_DEADLOCK} or attempt == 2:
                    raise

                time.sleep(0.35 * (attempt + 1))
        cursor.close()
        db.close()

        

        project_data = {
            "project_id": project_id,
            "slug": slug,
            "project_name": project_name,
            "slogan": details.get("slogan"),
            "phone": phone,
            "address": address
        }



        #generate_client_site(project_data)

        # If a logo was uploaded, write it into the generated client project's static/logos
        if logo_bytes and logo_filename:
            project_path = os.path.join(PROJECTS_DIR, slug)
            logos_dir = os.path.join(project_path, 'static', 'uploads', 'logos')
            os.makedirs(logos_dir, exist_ok=True)
            logo_file_path = os.path.join(logos_dir, logo_filename)
            with open(logo_file_path, 'wb') as f:
                f.write(logo_bytes)

            # Update project_settings.logo_path to point to client's static/uploads path
            try:
                conn2 = get_db_connection()
                cur2 = conn2.cursor()
                cur2.execute("UPDATE project_settings SET logo_path=%s WHERE project_id=%s", (f"static/uploads/logos/{logo_filename}", project_id))
                conn2.commit()
            finally:
                try:
                    cur2.close()
                    conn2.close()
                except:
                    pass

        return jsonify({
            "success": True,
            "slug": slug,
            "url": f"https://{slug}.dinebloc.com/"
        })

    except Exception as e:
        print(f"Error creating project: {e}")
        try:
            db.rollback()
        except:
            pass
        try:
            cursor.close()
            db.close()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500



@app.route("/check_project_name")
@login_required
def check_project_name():

            name = request.args.get("name", "").strip()

            if not name:
                return jsonify({"available": False})

            slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                "SELECT id FROM projects WHERE slug=%s LIMIT 1",
                (slug,)
            )

            exists = cursor.fetchone()

            cursor.close()
            db.close()

            return jsonify({
                "available": not bool(exists)
            })





def sanitize_order_text(value):
    return (value or "").strip() or None


def normalize_order_discount(raw_discount, base_price):
    try:
        discount = float(raw_discount or 0)
    except (TypeError, ValueError):
        discount = 0.0

    if discount < 0:
        discount = 0.0

    return min(discount, max(float(base_price or 0), 0.0))


def build_fallback_order_item(item, qty, item_kind):
    title = sanitize_order_text(item.get("title") or item.get("name") or item.get("item_name"))

    try:
        base_price = float(item.get("base_price", item.get("price", 0)) or 0)
    except (TypeError, ValueError):
        base_price = 0.0

    if not title or base_price < 0:
        return None

    discount = normalize_order_discount(item.get("discount"), base_price)
    final_price = max(base_price - discount, 0)

    payload = {
        "id": item.get("id"),
        "item_kind": item_kind,
        "title": title,
        "base_price": base_price,
        "discount": discount,
        "price": final_price,
        "quantity": qty
    }

    if item_kind == "product":
        payload["rank"] = sanitize_order_text(item.get("rank"))
    else:
        payload["type"] = sanitize_order_text(item.get("type"))
        payload["products"] = item.get("products")
        payload["bundle_items"] = item.get("bundle_items") or []

    return payload


def build_validated_order_items(project_id, items, cursor):
    total = 0.0
    validated_items = []

    for item in items or []:
        try:
            qty = int(item.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 1

        if qty <= 0:
            continue

        item_kind = item.get("item_kind") or item.get("kind") or "product"

        if item_kind == "deal":
            item_id = item.get("id")
            if item_id is None:
                fallback_item = build_fallback_order_item(item, qty, "deal")
                if fallback_item:
                    total += float(fallback_item["price"]) * qty
                    validated_items.append(fallback_item)
                continue

            cursor.execute(
                "SELECT id, title, price, description, products, type FROM deals WHERE id=%s AND project_id=%s",
                (item_id, project_id)
            )
            deal = cursor.fetchone()

            if not deal:
                fallback_item = build_fallback_order_item(item, qty, "deal")
                if fallback_item:
                    total += float(fallback_item["price"]) * qty
                    validated_items.append(fallback_item)
                continue

            base_price = float(deal["price"] or 0)
            discount = normalize_order_discount(item.get("discount"), base_price)
            final_price = max(base_price - discount, 0)
            total += final_price * qty

            validated_items.append({
                "id": deal["id"],
                "item_kind": "deal",
                "title": deal["title"],
                "base_price": base_price,
                "discount": discount,
                "price": final_price,
                "quantity": qty,
                "type": deal.get("type"),
                "products": deal.get("products"),
                "bundle_items": parse_deal_bundle_metadata(deal.get("description")).get("bundle_items", [])
            })
            continue

        item_id = item.get("id")
        if item_id is None:
            fallback_item = build_fallback_order_item(item, qty, "product")
            if fallback_item:
                total += float(fallback_item["price"]) * qty
                validated_items.append(fallback_item)
            continue

        cursor.execute(
            """
            SELECT id, title, price, has_ranking,
                   rank1_name, rank1_price,
                   rank2_name, rank2_price,
                   rank3_name, rank3_price,
                   rank4_name, rank4_price
            FROM products
            WHERE id=%s AND project_id=%s
            """,
            (item_id, project_id)
        )
        product = cursor.fetchone()

        if not product:
            fallback_item = build_fallback_order_item(item, qty, "product")
            if fallback_item:
                total += float(fallback_item["price"]) * qty
                validated_items.append(fallback_item)
            continue

        normalized_product = normalize_product_payload(product)
        selected_price = float(normalized_product["price"])
        selected_rank = None

        if normalized_product["has_ranking"]:
            requested_rank = (item.get("rank") or "").strip()
            matched_rank = next(
                (rank for rank in normalized_product["ranks"] if rank["name"] == requested_rank),
                None
            )

            if not matched_rank:
                continue

            selected_rank = matched_rank["name"]
            selected_price = float(matched_rank["price"])

        discount = normalize_order_discount(item.get("discount"), selected_price)
        final_price = max(selected_price - discount, 0)
        total += final_price * qty

        validated_items.append({
            "id": normalized_product["id"],
            "item_kind": "product",
            "title": normalized_product["title"],
            "base_price": selected_price,
            "discount": discount,
            "price": final_price,
            "quantity": qty,
            "rank": selected_rank
        })

    return validated_items, round(total, 2)


def create_order_record(project_id, data, cursor):
    validated_items, total = build_validated_order_items(project_id, data.get("items") or [], cursor)

    if not validated_items:
        raise ValueError("At least one valid order item is required.")

    cursor.execute("SELECT COALESCE(MAX(id), 0) AS last_id FROM orders")
    last_order = cursor.fetchone() or {}
    order_number = str((last_order.get("last_id") or 0) + 1)

    customer_name = sanitize_order_text(data.get("name"))
    customer_surname = sanitize_order_text(data.get("surname"))
    customer_phone = sanitize_order_text(data.get("phone"))
    customer_email = sanitize_order_text(data.get("email"))
    customer_note = sanitize_order_text(data.get("note"))

    cursor.execute("""
        INSERT INTO orders
        (project_id, order_number, items, total, payment_method, payment_status, status, name, surname, phone, email, note)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        project_id,
        order_number,
        json.dumps(validated_items),
        total,
        "instore",
        "pending",
        "received",
        customer_name,
        customer_surname,
        customer_phone,
        customer_email,
        customer_note
    ))

    return {
        "order_number": order_number,
        "validated_items": validated_items,
        "total": total,
        "name": customer_name,
        "surname": customer_surname,
        "phone": customer_phone,
        "email": customer_email,
        "note": customer_note
    }


def build_order_email_html(project_name, order_payload):
    item_rows = []
    for item in order_payload["validated_items"]:
        title = escape(item.get("title") or "Item")
        quantity = int(item.get("quantity") or 1)
        rank = sanitize_order_text(item.get("rank"))
        safe_rank = escape(rank) if rank else None
        descriptor = f"{title} ({safe_rank})" if safe_rank else title
        line_total = float(item.get("price") or 0) * quantity
        item_rows.append(
            f"""
            <tr>
              <td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;color:#0f172a;font-size:14px;">{descriptor}</td>
              <td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:14px;text-align:center;">{quantity}</td>
              <td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;color:#0f172a;font-size:14px;text-align:right;">${line_total:.2f}</td>
            </tr>
            """
        )

    customer_full_name = escape(" ".join(part for part in [order_payload.get("name"), order_payload.get("surname")] if part).strip() or "Guest")
    safe_phone = escape(order_payload.get('phone') or 'No phone provided')
    safe_email = escape(order_payload.get('email') or 'No email provided')
    safe_project_name = escape(project_name or "Restaurant")
    note_block = ""
    if order_payload.get("note"):
        note_block = f"""
        <div style="margin-top:18px;padding:16px 18px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Customer note</div>
          <div style="margin-top:8px;font-size:14px;line-height:1.6;color:#0f172a;">{escape(order_payload['note'])}</div>
        </div>
        """

    return f"""
    <div style="margin:0;padding:32px 18px;background:linear-gradient(180deg,#eff6ff 0%,#f8fafc 100%);font-family:Inter,Arial,sans-serif;color:#0f172a;">
      <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:24px;overflow:hidden;box-shadow:0 24px 60px rgba(15,23,42,0.12);border:1px solid #dbeafe;">
        <div style="padding:28px 30px;background:linear-gradient(135deg,#1d4ed8 0%,#2563eb 55%,#0f172a 100%);color:#ffffff;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.82;">New order received</div>
          <h1 style="margin:10px 0 6px;font-size:30px;line-height:1.1;">{safe_project_name}</h1>
          <p style="margin:0;font-size:15px;line-height:1.6;opacity:0.92;">Order #{order_payload['order_number']} has been placed and is waiting for restaurant confirmation.</p>
        </div>
        <div style="padding:28px 30px;">
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;">
            <div style="padding:16px 18px;border-radius:16px;background:#f8fafc;border:1px solid #e2e8f0;">
              <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Customer</div>
              <div style="margin-top:8px;font-size:16px;font-weight:700;color:#0f172a;">{customer_full_name}</div>
              <div style="margin-top:6px;font-size:14px;color:#475569;">{safe_phone}</div>
              <div style="margin-top:4px;font-size:14px;color:#475569;">{safe_email}</div>
            </div>
            <div style="padding:16px 18px;border-radius:16px;background:#fff7ed;border:1px solid #fed7aa;">
              <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9a3412;">Payment</div>
              <div style="margin-top:8px;font-size:16px;font-weight:700;color:#7c2d12;">In-store / pickup</div>
              <div style="margin-top:6px;font-size:14px;color:#9a3412;">Status: pending</div>
              <div style="margin-top:4px;font-size:18px;font-weight:800;color:#0f172a;">${order_payload['total']:.2f}</div>
            </div>
          </div>
          <div style="margin-top:22px;border:1px solid #e2e8f0;border-radius:18px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;">
              <thead>
                <tr style="background:#f8fafc;">
                  <th style="padding:12px 14px;text-align:left;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Item</th>
                  <th style="padding:12px 14px;text-align:center;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Qty</th>
                  <th style="padding:12px 14px;text-align:right;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Line total</th>
                </tr>
              </thead>
              <tbody>
                {''.join(item_rows)}
              </tbody>
            </table>
          </div>
          {note_block}
        </div>
      </div>
    </div>
    """


def build_customer_order_email_html(project_name, order_payload):
    item_rows = []
    for item in order_payload["validated_items"]:
        title = escape(item.get("title") or "Item")
        quantity = int(item.get("quantity") or 1)
        rank = sanitize_order_text(item.get("rank"))
        safe_rank = escape(rank) if rank else None
        descriptor = f"{title} ({safe_rank})" if safe_rank else title
        line_total = float(item.get("price") or 0) * quantity
        item_rows.append(
            f"""
            <tr>
              <td style="padding:12px 14px;border-bottom:1px solid #e2e8f0;color:#0f172a;font-size:14px;">{descriptor}</td>
              <td style="padding:12px 14px;border-bottom:1px solid #e2e8f0;color:#475569;font-size:14px;text-align:center;">{quantity}</td>
              <td style="padding:12px 14px;border-bottom:1px solid #e2e8f0;color:#0f172a;font-size:14px;text-align:right;">${line_total:.2f}</td>
            </tr>
            """
        )

    safe_project_name = escape(project_name or "Restaurant")
    note_block = ""
    if order_payload.get("note"):
        note_block = f"""
        <div style="margin-top:18px;padding:16px 18px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Note on your order</div>
          <div style="margin-top:8px;font-size:14px;line-height:1.6;color:#0f172a;">{escape(order_payload['note'])}</div>
        </div>
        """

    return f"""
    <div style="margin:0;padding:32px 18px;background:linear-gradient(180deg,#eff6ff 0%,#f8fafc 100%);font-family:Inter,Arial,sans-serif;color:#0f172a;">
      <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:24px;overflow:hidden;box-shadow:0 24px 60px rgba(15,23,42,0.12);border:1px solid #dbeafe;">
        <div style="padding:28px 30px;background:linear-gradient(135deg,#0b63ff 0%,#1d4ed8 55%,#0f172a 100%);color:#ffffff;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.82;">Order confirmation</div>
          <h1 style="margin:10px 0 8px;font-size:30px;line-height:1.1;">{safe_project_name}</h1>
          <p style="margin:0;font-size:15px;line-height:1.6;opacity:0.92;">Your order has been received.</p>
        </div>
        <div style="padding:28px 30px;">
          <div style="padding:18px;border-radius:18px;background:#eff6ff;border:1px solid #bfdbfe;text-align:center;">
            <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;">Order number</div>
            <div style="margin-top:8px;font-size:36px;font-weight:900;color:#0f172a;">#{escape(order_payload['order_number'])}</div>
          </div>
          <div style="margin-top:18px;padding:20px;border-radius:18px;background:#fff7ed;border:1px solid #fed7aa;">
            <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#7c2d12;">The restaurant will call you shortly to confirm your order.</p>
            <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#7c2d12;">Payment will be made in-store or upon pickup.</p>
            <p style="margin:0;font-size:15px;line-height:1.7;color:#7c2d12;">Please keep your phone available.</p>
          </div>
          <div style="margin-top:22px;border:1px solid #e2e8f0;border-radius:18px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;">
              <thead>
                <tr style="background:#f8fafc;">
                  <th style="padding:12px 14px;text-align:left;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Item</th>
                  <th style="padding:12px 14px;text-align:center;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Qty</th>
                  <th style="padding:12px 14px;text-align:right;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Line total</th>
                </tr>
              </thead>
              <tbody>
                {''.join(item_rows)}
              </tbody>
            </table>
          </div>
          <div style="margin-top:18px;display:flex;justify-content:flex-end;">
            <div style="padding:16px 18px;border-radius:16px;background:#f8fafc;border:1px solid #e2e8f0;min-width:220px;">
              <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Total</div>
              <div style="margin-top:6px;font-size:28px;font-weight:800;color:#0f172a;">${order_payload['total']:.2f}</div>
            </div>
          </div>
          {note_block}
        </div>
      </div>
    </div>
    """


def send_order_notification(project, order_payload):
    send_email(
        to=get_project_client_email(project["id"]),
        subject=f"New Order Received - {project.get('project_name')}",
        html_body=build_order_email_html(project.get("project_name") or "Restaurant", order_payload),
        sender=DEFAULT_INFO_EMAIL
    )


def send_customer_order_confirmation(project, order_payload):
    customer_email = (order_payload.get("email") or "").strip()
    if not customer_email:
        return

    send_email(
        to=customer_email,
        subject=f"Order Confirmation - {project.get('project_name')}",
        html_body=build_customer_order_email_html(project.get("project_name") or "Restaurant", order_payload),
        sender=DEFAULT_INFO_EMAIL,
        reply_to=get_project_client_email(project["id"])
    )


@app.route("/add_order", methods=["POST"])
@app.route("/admin/<slug>/add_order", methods=["POST"])
def add_order(slug=None):
    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    if getattr(g, "client", None) and not getattr(g, "trial_active", False):
        logging.info("Trial expired for client %s", g.client["id"])

    data = request.get_json(silent=True) or request.form or {}
    project_id = project["id"]

    conn = get_db_connection()
    ensure_order_columns(conn)
    cursor = conn.cursor(dictionary=True)
    try:
        order_payload = create_order_record(project_id, data, cursor)
    except ValueError as exc:
        cursor.close()
        conn.close()
        return jsonify(success=False, error=str(exc)), 400

    conn.commit()
    cursor.close()
    conn.close()
    send_order_notification(project, order_payload)
    send_customer_order_confirmation(project, order_payload)

    return {
        "success": True,
        "order_number": order_payload["order_number"],
        "payment_method": "instore",
        "payment_status": "pending"
    }


def ensure_client_trial_columns(conn):
    # TRIAL SYSTEM (Phase 1)
    cursor = conn.cursor()
    trial_columns = {
        "trial_start": "ADD COLUMN trial_start DATETIME NULL",
        "trial_end": "ADD COLUMN trial_end DATETIME NULL",
        "is_legacy": "ADD COLUMN is_legacy BOOLEAN NOT NULL DEFAULT TRUE",
        "subscription_status": "ADD COLUMN subscription_status VARCHAR(32) NOT NULL DEFAULT 'trial'",
        # LEGACY: previous trial fields (deprecated but preserved)
        "trial_applied_at": "ADD COLUMN trial_applied_at DATETIME NULL",
        "trial_ends_at": "ADD COLUMN trial_ends_at DATETIME NULL",
    }

    for column_name, alter_sql in trial_columns.items():
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'clients'
              AND COLUMN_NAME = %s
        """, (column_name,))
        has_column = cursor.fetchone()[0] > 0

        if not has_column:
            cursor.execute(f"ALTER TABLE clients {alter_sql}")

    conn.commit()
    cursor.close()




STRIPE_WEBHOOK_SECRET = "whsec_test_placeholder"


@app.route("/stripe_webhook", methods=["POST"])
def stripe_webhook():
    # LEGACY: Stripe payment system (disabled for trial phase)
    if not PAYMENTS_ENABLED:
        return "", 204

    # LEGACY: Stripe checkout flow (disabled for trial phase)
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except:
        return "", 400

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]

        order_number = session_data["metadata"]["order_number"]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE orders
            SET payment_status='paid'
            WHERE order_number=%s
        """, (order_number,))

        conn.commit()
        cursor.close()
        conn.close()

    return "", 200




CLIENT_STATIC_DIR = os.path.join(BASE_DIR, "client_template", "static")
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")





def get_project_modules(project_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM project_modules
        WHERE project_id = %s
    """, (project_id,))

    modules = cursor.fetchone()

    cursor.close()
    conn.close()

    modules = modules or {}

    print("\n================ MODULE DEBUG ================")
    KNOWN_MODULES = {
        "online_ordering_system",
        "staff_admin_system",
        "booking_reservation_system",
        "catering_system",
        "delivery_system",
        "pos_system"
    }

    for key, value in modules.items():
        if key in KNOWN_MODULES:
            print(f"{key}: {bool(value)}")

    print("==============================================\n")

    return modules





@app.route("/debug_generate")
def debug_generate():
    project_data = {
        "slug": "test-site",
        "project_name": "Test Restaurant",
        "slogan": "Testing Engine",
        "phone": "0400000000",
        "address": "Melbourne"
    }

    #generate_client_site(project_data)
    return "Generated"




def get_port():
    config_path = os.path.join(os.path.dirname(__file__), "project_config.json")

    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
            return int(config.get("PORT", 5001))

    return 5001




MODULE_FILE_MAP = {
    "online_ordering_system": {
        "templates": [
            "checkout.html",
            "checkout-instore.html",
            "payment_success.html"
        ],
        "js": ["cart.js"],
        "routes": ["ordering"]
    },

    "staff_admin_system": {
        "templates": [
            "workers.html",
            "worker_login.html"
        ],
        "js": ["admin/worker.js"],
        "routes": ["admin"]
    },

    "booking_reservation_system": {
        "templates": ["reservations.html"],
        "routes": ["reservations"]
    },

    "catering_system": {
        "templates": ["catering.html"],
        "routes": ["catering"]
    },

    "delivery_system": {
        "templates": ["delivery.html"],
        "routes": ["delivery"]
    },

    "pos_system": {
        "templates": ["pos.html"],
        "routes": ["pos"]
    }
}



@app.route('/checkout')
def checkout_page():
    if not hasattr(g, "project"):
        return "Project not found", 404
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template('checkout.html', **ctx)


@app.route('/checkout-instore')
def checkout_instore():
    if not hasattr(g, "project"):
        return "Project not found", 404
    if getattr(g, "trial_active", False) or not get_project_pay_in_store(g.project["id"]):
        return redirect(url_for("menu"))
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template('checkout-instore.html', **ctx)


@app.route('/payment-success')
def payment_success():
    if not hasattr(g, "project"):
        return "Project not found", 404
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template('payment_success.html', **ctx)



@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    if not hasattr(g, "project"):
        return "Project not found", 404

    if getattr(g, "client", None) and not getattr(g, "trial_active", False):
        logging.info("Trial expired for client %s", g.client["id"])

    data = request.get_json(silent=True) or request.form or {}
    project_slug = g.project.get("slug")

    # LEGACY: Stripe payment system (disabled for trial phase)
    if PAYMENTS_ENABLED:
        # LEGACY: Stripe checkout flow (disabled for trial phase)
        if not stripe.api_key:
            return jsonify({
                "error": "Stripe is not configured on this server. Set STRIPE_SECRET_KEY and restart the app."
            }), 503

        success = f"https://{project_slug}.dinebloc.com/payment-success"
        cancel = f"https://{project_slug}.dinebloc.com/menu"

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'aud',
                    'product_data': {
                        'name': 'Restaurant Order',
                    },
                    'unit_amount': int(data['total'] * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success,
            cancel_url=cancel,
        )
        print("[checkout] created session", session)
        return jsonify({'id': session.id})

    conn = get_db_connection()
    ensure_order_columns(conn)
    cursor = conn.cursor(dictionary=True)

    try:
        order_payload = create_order_record(g.project["id"], data or {}, cursor)
    except ValueError as exc:
        cursor.close()
        conn.close()
        return jsonify(success=False, error=str(exc)), 400

    conn.commit()
    cursor.close()
    conn.close()

    send_order_notification(g.project, order_payload)
    send_customer_order_confirmation(g.project, order_payload)

    return jsonify({
        "success": True,
        "order_number": order_payload["order_number"],
        "payment_method": "instore",
        "payment_status": "pending",
        "redirect_url": url_for("payment_success")
    })









#@app.route('/sign_up', methods=['GET', 'POST'])
#def sign_up():
    error = None

    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        name = request.form.get('name')
        surname = request.form.get('surname')
        phone = request.form.get('phone')
        email = request.form.get('email').lower()

        # 🔎 Check if phone OR email already exists
        cursor.execute("""
            SELECT * FROM customers 
            WHERE phone = %s OR email = %s
        """, (phone, email))

        existing_user = cursor.fetchone()

        if existing_user:
            if existing_user['phone'] == phone:
                error = "This phone number is already registered."
            elif existing_user['email'] == email:
                error = "This email is already registered."

            # cursor.close()
            # conn.close()
            return render_template('sign_up.html', error=error)

        try:
            token = secrets.token_urlsafe(32)

            code = generate_member_code()

            # ensure uniqueness
            cursor.execute("SELECT id FROM customers WHERE member_code=%s", (code,))
            while cursor.fetchone():
                code = generate_member_code()
                cursor.execute("SELECT id FROM customers WHERE member_code=%s", (code,))

            cursor.execute("""
                INSERT INTO customers (name, surname, phone, email, member_code, verification_token)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (name, surname, phone, email, code, token))
            conn.commit()

            verify_link = url_for('verify_account', token=token, _external=True)

            html_body = f"""
            <div style="font-family:Inter,Arial,sans-serif;background:#ffffff;padding:30px;">
                <div style="max-width:500px;margin:auto;border-radius:14px;
                            border:1px solid #eee;padding:30px;text-align:center;">

                    <h2 style="color:#000;margin-bottom:10px;">
                        Verify Your Membership
                    </h2>

                    <p style="color:#555;font-size:15px;">
                        Thanks for joining our free member program.<br>
                        Please confirm your email to activate your account.
                    </p>

                    <a href="{verify_link}"
                        style="
                        display:inline-block;
                        margin-top:20px;
                        padding:14px 28px;
                        background:#d4a373;
                        color:#000;
                        text-decoration:none;
                        font-weight:600;
                        border-radius:10px;
                        ">
                        Activate My Account
                    </a>

                    <div style="
                        margin-top:28px;
                        padding:18px;
                        background:#fafafa;
                        border:1px solid #eee;
                        border-radius:10px;
                    ">
                        <p style="margin:0 0 8px 0;color:#666;font-size:13px;">
                            Your Member Code
                        </p>

                        <div style="
                            font-size:20px;
                            font-weight:700;
                            letter-spacing:2px;
                            color:#d4a373;
                        ">
                            {code}
                        </div>

                        <p style="margin-top:10px;font-size:12px;color:#888;">
                            This code will work after your account is activated.
                        </p>
                    </div>

                    <p style="margin-top:25px;font-size:13px;color:#888;">
                        If you didn’t sign up, you can safely ignore this email.
                    </p>

                </div>
            </div>
            """

            send_email(
                to=email,
                subject="Verify your membership",
                html_body=html_body,
                sender=DEFAULT_INFO_EMAIL
            )

            cursor.close()
            conn.close()
            return render_template("sign_up.html", success=True)

        except mysql.connector.IntegrityError:
            cursor.close()
            conn.close()
            error = "Account already exists."
            return render_template('sign_up.html', error=error)

    return render_template('sign_up.html', error=error)


#@app.route('/verify/<token>')
#def verify_account(token):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id FROM customers WHERE verification_token = %s
    """, (token,))
    user = cursor.fetchone()

    if not user:
        return "Invalid or expired verification link."

    cursor.execute("""
        UPDATE customers
        SET account_status = 'Activated',
            verification_token = NULL
        WHERE id = %s
    """, (user['id'],))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect('/menu')


# =====================
# Get all orders
# =====================
@app.route('/get_orders')
@app.route('/admin/<slug>/get_orders')
def get_orders(slug=None):
    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    if not hasattr(g, "project"):
        return "Project not found", 404
    conn = get_db_connection()
    ensure_order_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM orders WHERE project_id = %s ORDER BY created_at DESC",
        (project["id"],)
    )
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(orders)


@app.route('/admin/<slug>/order_catalog')
def order_catalog(slug):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT p.id, p.title, p.description, p.price,
               p.has_ranking,
               p.rank1_name, p.rank1_price,
               p.rank2_name, p.rank2_price,
               p.rank3_name, p.rank3_price,
               p.rank4_name, p.rank4_price,
               p.image_path, p.category_id, c.name AS category
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.project_id=%s
        ORDER BY p.title ASC
        """,
        (project["id"],)
    )
    products = [normalize_product_payload(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT * FROM deals WHERE project_id=%s ORDER BY title ASC",
        (project["id"],)
    )
    deals = []
    for deal in cursor.fetchall():
        parsed_bundle = parse_deal_bundle_metadata(deal.get("description"))
        deals.append({
            "id": deal["id"],
            "title": deal.get("title"),
            "price": float(deal.get("price") or 0),
            "type": deal.get("type"),
            "description": parsed_bundle["description"],
            "bundle_items": parsed_bundle["bundle_items"]
        })

    cursor.close()
    conn.close()

    return jsonify({"products": products, "deals": deals})


# =====================
# Update order status
# =====================
VALID_STATUSES = ['received', 'in progress', 'completed']

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
@app.route('/admin/<slug>/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.json
    status = data.get('status')

    if status not in ['received', 'in progress', 'completed']:
        return jsonify(success=False, error="Invalid status"), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    if status == 'in progress':
        cursor.execute("""
            UPDATE orders 
            SET status=%s, in_progress_time=NOW()
            WHERE id=%s AND project_id=%s
        """, (status, order_id, project["id"]))
    elif status == 'completed':
        cursor.execute("""
            UPDATE orders 
            SET status=%s, completed_time=NOW()
            WHERE id=%s AND project_id=%s
        """, (status, order_id, project["id"]))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify(success=True)


@app.route('/admin/<slug>/orders/<int:order_id>', methods=['POST'])
def update_order(order_id, slug):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.get_json(silent=True) or request.form or {}

    conn = get_db_connection()
    ensure_order_columns(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id FROM orders WHERE id=%s AND project_id=%s",
        (order_id, project["id"])
    )
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return jsonify(success=False, error="Order not found"), 404

    validated_items, total = build_validated_order_items(project["id"], data.get("items") or [], cursor)

    if not validated_items:
        cursor.close()
        conn.close()
        return jsonify(success=False, error="At least one valid order item is required."), 400

    cursor.execute("""
        UPDATE orders
        SET items=%s,
            total=%s,
            payment_method=%s,
            name=%s,
            surname=%s,
            phone=%s,
            email=%s,
            note=%s
        WHERE id=%s AND project_id=%s
    """, (
        json.dumps(validated_items),
        total,
        sanitize_order_text(data.get("payment")) or "cash",
        sanitize_order_text(data.get("name")),
        sanitize_order_text(data.get("surname")),
        sanitize_order_text(data.get("phone")),
        sanitize_order_text(data.get("email")),
        sanitize_order_text(data.get("note")),
        order_id,
        project["id"]
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify(success=True, total=total)



WORKER_PASSWORD = 'ajin123ji456u#789'




@app.route('/worker/<slug>')
def worker_page(slug):
    if not session.get('worker_id'):
        return redirect(url_for('login'))

    if session.get('worker_project_slug') != slug:
        return "Unauthorized", 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, project_name, slug, created_at
        FROM projects
        WHERE slug=%s
        LIMIT 1
    """, (slug,))
    project = cursor.fetchone()
    cursor.close()
    conn.close()

    if not project:
        return "Project not found", 404

    return render_template('worker.html', slug=slug, project=project)



@app.route('/worker/<slug>/orders')
def worker_orders(slug):
    if not session.get('worker_id'):
        return redirect(url_for('login'))

    if session.get('worker_project_slug') != slug:
        return "Unauthorized", 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, project_name, slug, created_at
        FROM projects
        WHERE slug=%s
        LIMIT 1
    """, (slug,))
    project = cursor.fetchone()
    cursor.close()
    conn.close()

    if not project:
        return "Project not found", 404

    return render_template(
        "admin_orders.html",
        project=project,
        MODULES={},
        worker_view=True
    )




@app.route('/worker-logout')
def worker_logout():
    session.clear()
    return redirect(url_for('login'))



ADMIN_ROUTE = '/admin-92f8b3c4e1'

ADMIN_PASSWORD = 'ajax9997cli23##45'



# ======================
# ADMIN PANEL
# ======================


def get_project_for_client(slug):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM projects
        WHERE slug=%s AND client_id=%s
    """, (slug, session["client_id"]))

    project = cursor.fetchone()

    cursor.close()
    conn.close()

    return project



@app.route('/admin-logout')
def admin_logout():
    session.clear()
    return redirect('/dashboard')


@app.route('/admin/<slug>/orders')
@login_required
def admin_orders(slug):
    project = get_project_for_client(slug)
    if not project:
        return "Unauthorized", 403
    if not is_project_live(project):
        return redirect(url_for("webconfig", slug=slug))

    attach_project_context(project)
    modules = get_project_modules(project["id"])

    return render_template(
        "admin_orders.html",
        project=project,
        MODULES=modules
    )


@app.route('/admin/<slug>/management', methods=['GET', 'POST'])
@login_required
def admin_management(slug):
    project = get_project_for_client(slug)
    if not project:
        return "Unauthorized", 403
    if not is_project_live(project):
        return redirect(url_for("webconfig", slug=slug))

    attach_project_context(project)
    modules = get_project_modules(project["id"])
    conn = get_db_connection()
    ensure_product_upload_attempts_column(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT product_upload_attempts
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    upload_details = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    product_upload_attempts = int(upload_details.get("product_upload_attempts") or 0)

    return render_template(
        "admin_management.html",
        project=project,
        MODULES=modules,
        product_upload_attempts=product_upload_attempts,
        product_upload_limit=BULK_PRODUCT_UPLOAD_LIMIT,
    )


def safe_json_loads(raw_value, fallback):
    try:
        return json.loads(raw_value) if raw_value else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def build_project_analytics(project_id, modules):
    conn = get_db_connection()
    ensure_questions_table(conn)
    ensure_customer_response_columns(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, title, is_active, category_id FROM products WHERE project_id=%s", (project_id,))
    products = cursor.fetchall()

    cursor.execute("SELECT id, title, price, type, is_active, products FROM deals WHERE project_id=%s", (project_id,))
    deals = cursor.fetchall()

    cursor.execute("""
        SELECT id, order_number, items, total, payment_method, status, name, surname, phone, created_at
        FROM orders
        WHERE project_id=%s
        ORDER BY created_at ASC, id ASC
    """, (project_id,))
    orders = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS count FROM categories WHERE project_id=%s", (project_id,))
    category_count = (cursor.fetchone() or {}).get("count", 0)

    cursor.execute("SELECT COUNT(*) AS count FROM workers WHERE project_id=%s", (project_id,))
    worker_count = (cursor.fetchone() or {}).get("count", 0)

    cursor.execute("SELECT COUNT(*) AS count FROM domains WHERE project_id=%s", (project_id,))
    domain_count = (cursor.fetchone() or {}).get("count", 0)

    cursor.execute("SELECT COUNT(*) AS count FROM memberships WHERE project_id=%s AND is_active=1", (project_id,))
    active_membership_count = (cursor.fetchone() or {}).get("count", 0)

    cursor.execute("SELECT COUNT(*) AS count FROM questions WHERE project_id=%s", (project_id,))
    question_count = (cursor.fetchone() or {}).get("count", 0)

    reservation_count = pending_reservations = 0
    if modules.get("booking_reservation_system"):
        cursor.execute("SELECT COUNT(*) AS count FROM reservations WHERE project_id=%s", (project_id,))
        reservation_count = (cursor.fetchone() or {}).get("count", 0)
        cursor.execute("SELECT COUNT(*) AS count FROM reservations WHERE project_id=%s AND status='pending'", (project_id,))
        pending_reservations = (cursor.fetchone() or {}).get("count", 0)

    catering_count = 0
    if modules.get("catering_system"):
        cursor.execute("SELECT COUNT(*) AS count FROM catering_inquiries WHERE project_id=%s", (project_id,))
        catering_count = (cursor.fetchone() or {}).get("count", 0)

    cursor.close()
    conn.close()

    product_lookup = {str(product["id"]): product.get("title") or f"Product {product['id']}" for product in products}
    deal_lookup = {str(deal["id"]): deal for deal in deals}

    order_count = len(orders)
    gross_revenue = round(sum(float(order.get("total") or 0) for order in orders), 2)
    average_order_value = round(gross_revenue / order_count, 2) if order_count else 0
    unique_customers = len({(order.get("phone") or f"{order.get('name')}-{order.get('surname')}").strip() for order in orders if (order.get("phone") or order.get("name"))})
    repeat_customer_count = sum(1 for count in Counter((order.get("phone") or f"{order.get('name')}-{order.get('surname')}").strip() for order in orders if (order.get("phone") or order.get("name"))).values() if count > 1)

    payment_counter = Counter()
    status_counter = Counter()
    product_units_counter = Counter()
    deal_units_counter = Counter()
    category_units_counter = Counter()
    direct_product_revenue = 0.0
    deal_revenue = 0.0
    total_items_sold = 0
    daily_revenue = defaultdict(float)
    daily_orders = defaultdict(int)
    hourly_orders = Counter()

    product_category_lookup = {str(product["id"]): product.get("category_id") for product in products}

    for order in orders:
        payment_counter[(order.get("payment_method") or "unknown").strip().lower() or "unknown"] += 1
        status_counter[(order.get("status") or "unknown").strip().lower() or "unknown"] += 1

        created_at = order.get("created_at")
        if created_at:
            day_key = created_at.strftime("%d %b")
            daily_revenue[day_key] += float(order.get("total") or 0)
            daily_orders[day_key] += 1
            hourly_orders[created_at.strftime("%H:00")] += 1

        items = safe_json_loads(order.get("items"), [])
        for item in items:
            qty = int(item.get("quantity") or 0)
            if qty <= 0:
                continue

            total_items_sold += qty
            item_kind = item.get("item_kind") or item.get("kind") or "product"

            if item_kind == "deal":
                deal_id = str(item.get("id"))
                deal_units_counter[deal_lookup.get(deal_id, {}).get("title") or item.get("title") or f"Deal {deal_id}"] += qty
                deal_revenue += float(item.get("price") or 0) * qty

                raw_products = str(item.get("products") or "")
                if raw_products:
                    for product_id in [part for part in raw_products.split(DEAL_PRODUCTS_SEPARATOR) if part]:
                        product_units_counter[product_lookup.get(product_id, f"Product {product_id}")] += qty
                        category_id = product_category_lookup.get(product_id)
                        if category_id:
                            category_units_counter[str(category_id)] += qty
                continue

            product_id = str(item.get("id"))
            product_units_counter[product_lookup.get(product_id, item.get("title") or f"Product {product_id}")] += qty
            direct_product_revenue += float(item.get("price") or 0) * qty
            category_id = product_category_lookup.get(product_id)
            if category_id:
                category_units_counter[str(category_id)] += qty

    active_products = sum(1 for product in products if parse_bool(product.get("is_active", 1)))
    active_deals = sum(1 for deal in deals if parse_bool(deal.get("is_active", 1)))
    sold_products_total = sum(product_units_counter.values())
    sold_deals_total = sum(deal_units_counter.values())
    completion_rate = round((status_counter.get("completed", 0) / order_count) * 100, 1) if order_count else 0

    top_products = product_units_counter.most_common(6)
    top_deals = deal_units_counter.most_common(6)
    top_hours = hourly_orders.most_common(6)
    trend_labels = list(daily_revenue.keys())[-10:]
    revenue_trend = [{"label": label, "value": round(daily_revenue[label], 2)} for label in trend_labels]
    order_trend = [{"label": label, "value": daily_orders[label]} for label in trend_labels]

    max_product_units = max((value for _, value in top_products), default=1)
    max_deal_units = max((value for _, value in top_deals), default=1)
    max_revenue_day = max((point["value"] for point in revenue_trend), default=1)
    max_order_day = max((point["value"] for point in order_trend), default=1)
    max_payment = max(payment_counter.values(), default=1)
    max_status = max(status_counter.values(), default=1)
    max_hour = max((value for _, value in top_hours), default=1)

    return {
        "cards": [
            {"label": "Total Earnings", "value": f"${gross_revenue:,.2f}", "accent": "blue"},
            {"label": "Orders Received", "value": str(order_count), "accent": "coral"},
            {"label": "Average Order", "value": f"${average_order_value:,.2f}", "accent": "green"},
            {"label": "Unique Customers", "value": str(unique_customers), "accent": "violet"},
            {"label": "Products Available", "value": str(len(products)), "accent": "amber"},
            {"label": "Products Sold", "value": str(sold_products_total), "accent": "indigo"},
            {"label": "Deals Live", "value": str(len(deals)), "accent": "rose"},
            {"label": "Deals Bought", "value": str(sold_deals_total), "accent": "teal"},
            {"label": "Completion Rate", "value": f"{completion_rate}%", "accent": "lime"},
            {"label": "Total Queries", "value": str(question_count + catering_count + reservation_count), "accent": "sky"},
            {"label": "Pending Reservations", "value": str(pending_reservations), "accent": "orange"},
            {"label": "Active Memberships", "value": str(active_membership_count), "accent": "pink"},
        ],
        "summary": {
            "active_products": active_products,
            "active_deals": active_deals,
            "worker_count": worker_count,
            "domain_count": domain_count,
            "repeat_customers": repeat_customer_count,
            "category_count": category_count,
            "direct_product_revenue": round(direct_product_revenue, 2),
            "deal_revenue": round(deal_revenue, 2),
            "catering_count": catering_count,
            "reservation_count": reservation_count,
            "question_count": question_count,
        },
        "top_products": [
            {"label": label, "value": value, "width": round((value / max_product_units) * 100, 1)}
            for label, value in top_products
        ],
        "top_deals": [
            {"label": label, "value": value, "width": round((value / max_deal_units) * 100, 1)}
            for label, value in top_deals
        ],
        "payments": [
            {"label": label.title(), "value": value, "width": round((value / max_payment) * 100, 1)}
            for label, value in payment_counter.items()
        ],
        "statuses": [
            {"label": label.title(), "value": value, "width": round((value / max_status) * 100, 1)}
            for label, value in status_counter.items()
        ],
        "revenue_trend": [
            {**point, "height": round((point["value"] / max_revenue_day) * 100, 1) if max_revenue_day else 0}
            for point in revenue_trend
        ],
        "order_trend": [
            {**point, "height": round((point["value"] / max_order_day) * 100, 1) if max_order_day else 0}
            for point in order_trend
        ],
        "busiest_hours": [
            {"label": label, "value": value, "width": round((value / max_hour) * 100, 1)}
            for label, value in top_hours
        ]
    }


@app.route('/admin/<slug>/analytics')
@login_required
def admin_analytics(slug):
    project = get_project_for_client(slug)
    if not project:
        return "Unauthorized", 403
    if not is_project_live(project):
        return redirect(url_for("webconfig", slug=slug))

    attach_project_context(project)
    modules = get_project_modules(project["id"])
    analytics = build_project_analytics(project["id"], modules)

    return render_template(
        "admin_analytics.html",
        project=project,
        MODULES=modules,
        analytics=analytics
    )


@app.route('/admin/<slug>/customers')
@login_required
def admin_customers(slug):
    project = get_project_for_client(slug)
    if not project:
        return "Unauthorized", 403
    if not is_project_live(project):
        return redirect(url_for("webconfig", slug=slug))

    attach_project_context(project)
    modules = get_project_modules(project["id"])

    conn = get_db_connection()
    ensure_questions_table(conn)
    ensure_customer_response_columns(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, name, email, message, response, created_at
        FROM questions
        WHERE project_id=%s
        ORDER BY created_at DESC, id DESC
    """, (project["id"],))
    contact_queries = cursor.fetchall()

    catering_queries = []
    if modules.get("catering_system"):
        cursor.execute("""
            SELECT id, name, phone, email, event_date, guests, event_type, details, response, created_at
            FROM catering_inquiries
            WHERE project_id=%s
            ORDER BY created_at DESC, id DESC
        """, (project["id"],))
        catering_queries = cursor.fetchall()

    reservation_queries = []
    if modules.get("booking_reservation_system"):
        cursor.execute("""
            SELECT id, name, email, phone, reservation_date, reservation_time, guests, special_requests, response, created_at
            FROM reservations
            WHERE project_id=%s
            ORDER BY created_at DESC, id DESC
        """, (project["id"],))
        reservation_queries = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "customers.html",
        project=project,
        MODULES=modules,
        contact_queries=contact_queries,
        catering_queries=catering_queries,
        reservation_queries=reservation_queries
    )


@app.route('/admin/<slug>/customers/respond', methods=['POST'])
@login_required
def admin_customers_respond(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    data = request.get_json(silent=True) or request.form or {}
    recipient = (data.get("recipient") or "").strip()
    message_body = (data.get("message") or "").strip()
    subject = (data.get("subject") or "").strip()
    inquiry_type = (data.get("inquiry_type") or "").strip()
    inquiry_id = data.get("inquiry_id")

    if not recipient or not message_body or not inquiry_type or not inquiry_id:
        return jsonify(success=False, error="Recipient, message, and inquiry details are required"), 400

    client_email = get_project_client_email(project["id"])
    table_map = {
        "question": "questions",
        "catering": "catering_inquiries",
        "reservation": "reservations"
    }
    table_name = table_map.get(inquiry_type)

    if not table_name:
        return jsonify(success=False, error="Invalid inquiry type"), 400

    conn = get_db_connection()
    ensure_customer_response_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        f"SELECT response FROM {table_name} WHERE id=%s AND project_id=%s",
        (inquiry_id, project["id"])
    )
    existing_row = cursor.fetchone()
    if not existing_row:
        cursor.close()
        conn.close()
        return jsonify(success=False, error="Inquiry not found"), 404

    timestamp = datetime.now().strftime("%d %b %Y %I:%M %p")
    new_entry = f"[{timestamp}]\n{message_body}"
    combined_response = f"{existing_row.get('response')}\n\n---\n\n{new_entry}" if existing_row.get('response') else new_entry

    cursor.close()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE {table_name} SET response=%s WHERE id=%s AND project_id=%s",
        (combined_response, inquiry_id, project["id"])
    )
    conn.commit()
    updated = cursor.rowcount > 0
    cursor.close()
    conn.close()

    if not updated:
        return jsonify(success=False, error="Inquiry not found"), 404

    send_email(
        to=recipient,
        subject=subject or f"Response from {project.get('project_name')}",
        html_body=f"<pre>{escape(message_body)}</pre>",
        sender=DEFAULT_INFO_EMAIL,
        reply_to=client_email
    )
    return jsonify(success=True, response=combined_response)




@app.route('/admin/<slug>')
@login_required
def admin_panel(slug):
    project = get_project_for_client(slug)
    if not project:
        return "Unauthorized", 403
    if not is_project_live(project):
        return redirect(url_for("webconfig", slug=slug))
    attach_project_context(project)
    g.modules = get_project_modules(project["id"])

    return render_template(
        "admin.html",
        project=project,
        MODULES=g.modules
    )



# ======================
# API — Categories
# ======================



@app.route('/categories', methods=['POST'])
@app.route('/admin/<slug>/categories', methods=['POST'])
def add_category(slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO categories (project_id, name) VALUES (%s, %s)",
        (project["id"], data['name'])
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})



@app.route('/categories/<int:id>', methods=['PUT'])
@app.route('/admin/<slug>/categories/<int:id>', methods=['PUT'])
def update_category(id, slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE categories SET name=%s WHERE id=%s AND project_id=%s",
        (data['name'], id, project["id"])
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


@app.route('/categories/<int:id>', methods=['DELETE'])
@app.route('/admin/<slug>/categories/<int:id>', methods=['DELETE'])
def delete_category(id, slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM categories WHERE id=%s AND project_id=%s",
        (id, project["id"])
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


# ======================
# API — Products
# ======================

@app.route('/products', methods=['GET'])
@app.route('/admin/<slug>/products', methods=['GET'])
def get_products(slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        '''
        SELECT p.id, p.title, p.description, p.price,
               p.has_ranking,
               p.rank1_name, p.rank1_price,
               p.rank2_name, p.rank2_price,
               p.rank3_name, p.rank3_price,
               p.rank4_name, p.rank4_price,
               p.image_path, p.category_id, c.name AS category
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.project_id=%s
        ORDER BY p.id
        ''',
        (project["id"],)
    )

    data = [normalize_product_payload(row) for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return jsonify(data)


@app.route('/products', methods=['POST'])
@app.route('/admin/<slug>/products', methods=['POST'])
def add_product(slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    title = request.form.get('title')
    description = request.form.get('description')
    price_raw = request.form.get('price') or 0
    category_id = int(request.form.get('category_id'))
    file = request.files.get('image')

    try:
        has_ranking, ranks = extract_product_ranking_form_data(request.form)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    try:
        price = float(price_raw) if not has_ranking else float(ranks[0]["price"])
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Price must be a valid number."}), 400

    rank_payload = get_rank_columns_payload(ranks if has_ranking else [])

    image_path = None

    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_path = f"/uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        '''
        INSERT INTO products
        (
            project_id, category_id, title, description, price, image_path,
            has_ranking,
            rank1_name, rank1_price,
            rank2_name, rank2_price,
            rank3_name, rank3_price,
            rank4_name, rank4_price
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''',
        (
            project["id"], category_id, title, description, price, image_path,
            has_ranking,
            rank_payload["rank1_name"], rank_payload["rank1_price"],
            rank_payload["rank2_name"], rank_payload["rank2_price"],
            rank_payload["rank3_name"], rank_payload["rank3_price"],
            rank_payload["rank4_name"], rank_payload["rank4_price"],
        )
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


@app.route('/admin/<slug>/bulk-products-upload', methods=['POST'])
@login_required
def bulk_products_upload(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    upload = request.files.get("catalogue")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "Please upload an image, PDF, DOCX, TXT, or CSV file."}), 400

    extension = get_file_extension(upload.filename)
    if extension not in BULK_PRODUCT_ALLOWED_EXTENSIONS:
        return jsonify({"success": False, "error": "Unsupported file type. Use an image, PDF, DOCX, TXT, or CSV."}), 400

    file_bytes = upload.read()
    if not file_bytes:
        return jsonify({"success": False, "error": "The uploaded file was empty."}), 400

    if len(file_bytes) > 12 * 1024 * 1024:
        return jsonify({"success": False, "error": "Upload is too large. Please keep files under 12MB."}), 400

    conn = get_db_connection()
    ensure_product_upload_attempts_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT product_upload_attempts
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone()

    if not details:
        cursor.execute(
            "INSERT INTO project_details (project_id, product_upload_attempts) VALUES (%s, 0)",
            (project["id"],)
        )
        conn.commit()
        attempts = 0
    else:
        attempts = int(details.get("product_upload_attempts") or 0)

    if attempts >= BULK_PRODUCT_UPLOAD_LIMIT:
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": "Bulk product upload limit reached.",
            "attempts_used": attempts,
            "attempts_remaining": 0,
            "disabled": True,
        }), 403

    attempts += 1
    cursor.execute("""
        UPDATE project_details
        SET product_upload_attempts=%s
        WHERE project_id=%s
    """, (attempts, project["id"]))
    conn.commit()
    cursor.close()
    conn.close()

    try:
        extracted_products = extract_bulk_products_with_ai(project["project_name"], file_bytes, extension)
    except Exception as exc:
        logging.exception("Bulk product extraction failed")
        return jsonify({
            "success": False,
            "error": str(exc) or "Product extraction failed.",
            "attempts_used": attempts,
            "attempts_remaining": max(BULK_PRODUCT_UPLOAD_LIMIT - attempts, 0),
            "disabled": attempts >= BULK_PRODUCT_UPLOAD_LIMIT,
        }), 502

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        inserted_count, category_count = insert_bulk_products(cursor, project["id"], extracted_products)
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Bulk product database insert failed")
        return jsonify({
            "success": False,
            "error": "Products were extracted, but database upload failed.",
            "attempts_used": attempts,
            "attempts_remaining": max(BULK_PRODUCT_UPLOAD_LIMIT - attempts, 0),
            "disabled": attempts >= BULK_PRODUCT_UPLOAD_LIMIT,
        }), 500
    finally:
        cursor.close()
        conn.close()

    return jsonify({
        "success": True,
        "inserted_products": inserted_count,
        "touched_categories": category_count,
        "attempts_used": attempts,
        "attempts_remaining": max(BULK_PRODUCT_UPLOAD_LIMIT - attempts, 0),
        "disabled": attempts >= BULK_PRODUCT_UPLOAD_LIMIT,
    })



@app.route('/products/<int:id>', methods=['PUT'])
@app.route('/admin/<slug>/products/<int:id>', methods=['PUT'])
def update_product(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    title = request.form.get('title')
    description = request.form.get('description')
    price = float(request.form.get('price'))
    category_id = int(request.form.get('category_id'))
    file = request.files.get('image')
    include_ranking = "has_ranking" in request.form or any(
        request.form.get(f"rank{index}_name") or request.form.get(f"rank{index}_price")
        for index in range(1, 5)
    )

    if include_ranking:
        try:
            has_ranking, ranks = extract_product_ranking_form_data(request.form)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
    else:
        has_ranking, ranks = None, None

    conn = get_db_connection()
    cursor = conn.cursor()
    image_path = None

    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_path = f"/uploads/{filename}"

    if include_ranking:
        rank_payload = get_rank_columns_payload(ranks if has_ranking else [])
        final_price = float(ranks[0]["price"]) if has_ranking and ranks else price

        if image_path:
            cursor.execute(
                '''
                UPDATE products
                SET title=%s, description=%s, price=%s, category_id=%s, image_path=%s,
                    has_ranking=%s,
                    rank1_name=%s, rank1_price=%s,
                    rank2_name=%s, rank2_price=%s,
                    rank3_name=%s, rank3_price=%s,
                    rank4_name=%s, rank4_price=%s
                WHERE id=%s AND project_id=%s
                ''',
                (
                    title, description, final_price, category_id, image_path,
                    has_ranking,
                    rank_payload["rank1_name"], rank_payload["rank1_price"],
                    rank_payload["rank2_name"], rank_payload["rank2_price"],
                    rank_payload["rank3_name"], rank_payload["rank3_price"],
                    rank_payload["rank4_name"], rank_payload["rank4_price"],
                    id, project["id"],
                )
            )
        else:
            cursor.execute(
                '''
                UPDATE products
                SET title=%s, description=%s, price=%s, category_id=%s,
                    has_ranking=%s,
                    rank1_name=%s, rank1_price=%s,
                    rank2_name=%s, rank2_price=%s,
                    rank3_name=%s, rank3_price=%s,
                    rank4_name=%s, rank4_price=%s
                WHERE id=%s AND project_id=%s
                ''',
                (
                    title, description, final_price, category_id,
                    has_ranking,
                    rank_payload["rank1_name"], rank_payload["rank1_price"],
                    rank_payload["rank2_name"], rank_payload["rank2_price"],
                    rank_payload["rank3_name"], rank_payload["rank3_price"],
                    rank_payload["rank4_name"], rank_payload["rank4_price"],
                    id, project["id"],
                )
            )
    else:
        if image_path:
            cursor.execute(
                '''
                UPDATE products
                SET title=%s, description=%s, price=%s, category_id=%s, image_path=%s
                WHERE id=%s AND project_id=%s
                ''',
                (title, description, price, category_id, image_path, id, project["id"],)
            )
        else:
            cursor.execute(
                '''
                UPDATE products
                SET title=%s, description=%s, price=%s, category_id=%s
                WHERE id=%s AND project_id=%s
                ''',
                (title, description, price, category_id, id, project["id"],)
            )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


@app.route('/products/<int:id>', methods=['DELETE'])
@app.route('/admin/<slug>/products/<int:id>', methods=['DELETE'])
def delete_product(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM products WHERE id=%s AND project_id=%s",
        (id, project["id"],)
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


# ======================
# API — Deals
# ======================

def resolve_project(slug=None):
    # 1. If already set (from detect_project)
    if hasattr(g, "project"):
        return attach_project_context(g.project)

    # 2. From URL slug
    if slug:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM projects WHERE slug=%s", (slug,))
        project = cursor.fetchone()

        cursor.close()
        conn.close()

        if project:
            if request.path.startswith("/admin/") and not is_project_live(project):
                return None
            return attach_project_context(project)

    # LEGACY: project query param system (deprecated)
    # project_param = request.args.get("project")
    # if project_param:
    #     conn = get_db_connection()
    #     cursor = conn.cursor(dictionary=True)
    #
    #     cursor.execute("SELECT * FROM projects WHERE slug=%s", (project_param,))
    #     project = cursor.fetchone()
    #
    #     cursor.close()
    #     conn.close()
    #
    #     if project:
    #         g.project = project
    #         return project

    return None


DEAL_PRODUCTS_SEPARATOR = "^^^&"
DEAL_BUNDLE_MARKER = "\n[[DEAL_BUNDLE]]"


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_product_ranks_from_row(row):
    ranks = []

    for index in range(1, 5):
        name = (row.get(f"rank{index}_name") or "").strip()
        price = row.get(f"rank{index}_price")

        if not name or price in (None, ""):
            continue

        try:
            price_value = float(price)
        except (TypeError, ValueError):
            continue

        ranks.append({
            "name": name,
            "price": price_value
        })

    return ranks


def normalize_product_payload(row):
    has_ranking = parse_bool(row.get("has_ranking"))
    ranks = build_product_ranks_from_row(row)

    return {
        "id": row["id"],
        "title": row.get("title"),
        "description": row.get("description"),
        "price": float(row.get("price") or 0),
        "image_path": row.get("image_path"),
        "category_id": row.get("category_id"),
        "category": row.get("category"),
        "has_ranking": bool(has_ranking and ranks),
        "ranks": ranks
    }


def extract_product_ranking_form_data(form, allow_missing=False):
    has_ranking = parse_bool(form.get("has_ranking"))
    ranks = []

    for index in range(1, 5):
        name = (form.get(f"rank{index}_name") or "").strip()
        price_raw = (form.get(f"rank{index}_price") or "").strip()

        if not name and not price_raw:
            continue

        if not name or not price_raw:
            if allow_missing:
                continue
            raise ValueError(f"Rank {index} requires both a name and a price.")

        try:
            price_value = float(price_raw)
        except ValueError as exc:
            raise ValueError(f"Rank {index} price must be a valid number.") from exc

        ranks.append({
            "name": name,
            "price": price_value
        })

    if has_ranking and not ranks:
        raise ValueError("At least one rank is required when ranking is enabled.")

    return has_ranking, ranks


def get_rank_columns_payload(ranks):
    payload = {}

    for index in range(1, 5):
        if index <= len(ranks):
            payload[f"rank{index}_name"] = ranks[index - 1]["name"]
            payload[f"rank{index}_price"] = ranks[index - 1]["price"]
        else:
            payload[f"rank{index}_name"] = None
            payload[f"rank{index}_price"] = None

    return payload


BULK_PRODUCT_UPLOAD_LIMIT = 3
BULK_PRODUCT_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "pdf", "docx", "txt", "csv"}
BULK_PRODUCT_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def get_file_extension(filename):
    return (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def normalize_price(value):
    if value in (None, ""):
        return None

    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned:
        return None

    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def compact_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_bulk_product_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("The AI response was not valid product data.")

    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        raise ValueError("No product list was returned.")

    normalized_products = []
    seen = set()

    for item in raw_products:
        if not isinstance(item, dict):
            continue

        title = compact_whitespace(item.get("title"))[:140]
        category = compact_whitespace(item.get("category"))[:90] or "Menu"
        description = compact_whitespace(item.get("description"))[:600]
        price = normalize_price(item.get("price"))
        ranks = []

        raw_ranks = item.get("ranks") if isinstance(item.get("ranks"), list) else []
        for rank in raw_ranks[:4]:
            if not isinstance(rank, dict):
                continue

            rank_name = compact_whitespace(rank.get("name"))[:80]
            rank_price = normalize_price(rank.get("price"))
            if rank_name and rank_price is not None:
                ranks.append({"name": rank_name, "price": rank_price})

        if ranks:
            price = ranks[0]["price"]

        if not title or price is None:
            continue

        if len(description.split()) < 10:
            description = (
                f"A fresh, satisfying {title.lower()} prepared with care and served with reliable local flavour."
            )

        key = (title.lower(), category.lower())
        if key in seen:
            continue
        seen.add(key)

        normalized_products.append({
            "title": title,
            "category": category,
            "description": description,
            "price": price,
            "has_ranking": bool(ranks),
            "ranks": ranks,
        })

    if not normalized_products:
        raise ValueError("No usable products were found in the upload.")

    return normalized_products


def extract_docx_text(file_bytes):
    with zipfile.ZipFile(BytesIO(file_bytes)) as docx:
        xml_content = docx.read("word/document.xml")

    root = ET.fromstring(xml_content)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts = [node.text for node in root.findall(".//w:t", namespace) if node.text]
    return compact_whitespace(" ".join(parts))


def extract_pdf_text(file_bytes):
    try:
        from PyPDF2 import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF support requires PyPDF2. Install the updated requirements first.") from exc

    reader = PdfReader(BytesIO(file_bytes))
    parts = []
    for page in reader.pages[:8]:
        parts.append(page.extract_text() or "")

    return compact_whitespace(" ".join(parts))


def extract_bulk_upload_text(file_bytes, extension):
    if extension in {"txt", "csv"}:
        return file_bytes.decode("utf-8", errors="ignore")
    if extension == "docx":
        return extract_docx_text(file_bytes)
    if extension == "pdf":
        return extract_pdf_text(file_bytes)
    return ""


def build_bulk_product_prompt(project_name):
    return f"""
You are extracting a restaurant/cafe product catalogue for WebBuilderMD.

Return ONLY valid JSON with this exact shape:
{{
  "products": [
    {{
      "title": "Product name",
      "category": "Relevant category",
      "description": "10 to 18 words, generate one if missing",
      "price": 12.50,
      "ranks": [
        {{"name": "Small", "price": 9.50}},
        {{"name": "Large", "price": 13.50}}
      ]
    }}
  ]
}}

Database rules you must follow:
- Categories map to categories.name.
- Products map to products.title, products.description, products.price, and category_id.
- Ranking maps to products.has_ranking plus rank1_name/rank1_price through rank4_name/rank4_price.
- If a product has ranking or sizes, put every visible size/variant in ranks and use the first rank price as product price.
- If a product has no ranking, ranks must be [] and price must be the visible product price.
- Details/descriptions must be at least 10 words. If missing, write a natural product description.
- Extract products only. Do not include deals, bundles, business hours, headings, contact info, or notes as products.
- Create sensible category names from visible menu sections. If none are visible, use "Menu".
- Prefer accuracy over guessing. Skip any product without a clear name and price.

Business/project name: {project_name}
""".strip()


def build_bulk_product_openai_messages(project_name, file_bytes, extension):
    prompt = build_bulk_product_prompt(project_name)

    if extension in BULK_PRODUCT_IMAGE_EXTENSIONS:
        mime = detect_image_mime(file_bytes)
        data_url = f"data:{mime};base64,{base64.b64encode(file_bytes).decode('ascii')}"
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }]

    extracted_text = extract_bulk_upload_text(file_bytes, extension)
    if not extracted_text:
        raise ValueError("Could not read text from this file.")

    return [{
        "role": "user",
        "content": f"{prompt}\n\nUploaded menu/catalogue text:\n{extracted_text[:18000]}",
    }]


def extract_bulk_products_with_ai(project_name, file_bytes, extension):
    messages = build_bulk_product_openai_messages(project_name, file_bytes, extension)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or "{}"
    payload = json.loads(raw_content)
    return normalize_bulk_product_payload(payload)


def get_or_create_category_id(cursor, project_id, category_name, category_cache):
    lookup_key = category_name.strip().lower()
    if lookup_key in category_cache:
        return category_cache[lookup_key]

    cursor.execute(
        "SELECT id FROM categories WHERE project_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1",
        (project_id, category_name)
    )
    row = cursor.fetchone()

    if row:
        category_id = row[0] if not isinstance(row, dict) else row["id"]
    else:
        cursor.execute(
            "INSERT INTO categories (project_id, name) VALUES (%s, %s)",
            (project_id, category_name)
        )
        category_id = cursor.lastrowid

    category_cache[lookup_key] = category_id
    return category_id


def insert_bulk_products(cursor, project_id, products):
    cursor.execute("SELECT id, name FROM categories WHERE project_id=%s", (project_id,))
    category_cache = {str(row[1]).strip().lower(): row[0] for row in cursor.fetchall()}

    inserted_count = 0
    category_names = set()

    for product in products:
        category_id = get_or_create_category_id(cursor, project_id, product["category"], category_cache)
        category_names.add(product["category"])
        rank_payload = get_rank_columns_payload(product["ranks"] if product["has_ranking"] else [])

        cursor.execute("""
            INSERT INTO products
            (
                project_id, category_id, title, description, price, image_path,
                has_ranking,
                rank1_name, rank1_price,
                rank2_name, rank2_price,
                rank3_name, rank3_price,
                rank4_name, rank4_price
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            project_id, category_id, product["title"], product["description"], product["price"], None,
            product["has_ranking"],
            rank_payload["rank1_name"], rank_payload["rank1_price"],
            rank_payload["rank2_name"], rank_payload["rank2_price"],
            rank_payload["rank3_name"], rank_payload["rank3_price"],
            rank_payload["rank4_name"], rank_payload["rank4_price"],
        ))
        inserted_count += 1

    return inserted_count, len(category_names)


def parse_deal_bundle_metadata(description):
    source = (description or "").strip()
    marker_index = source.find(DEAL_BUNDLE_MARKER)

    if marker_index == -1:
        return {
            "description": source,
            "bundle_items": []
        }

    clean_description = source[:marker_index].strip()
    raw_bundle = source[marker_index + len(DEAL_BUNDLE_MARKER):].strip()

    try:
        bundle_items = json.loads(raw_bundle)
        if not isinstance(bundle_items, list):
            bundle_items = []
    except json.JSONDecodeError:
        bundle_items = []

    return {
        "description": clean_description,
        "bundle_items": bundle_items
    }


def serialize_deal_products(bundle_items):
    product_ids = []

    for item in bundle_items or []:
        try:
            product_id = int(item.get("product_id"))
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError, AttributeError):
            continue

        if product_id <= 0 or quantity <= 0:
            continue

        product_ids.extend([str(product_id)] * quantity)

    return DEAL_PRODUCTS_SEPARATOR.join(product_ids)


def serialize_deal_description(description, bundle_items):
    base_description = (description or "").strip()
    safe_items = []

    for item in bundle_items or []:
        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError, AttributeError):
            continue

        if quantity <= 0:
            continue

        category_id = item.get("category_id")
        if category_id not in (None, ""):
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                category_id = None

            if category_id and category_id > 0:
                safe_items.append({
                    "product_id": None,
                    "category_id": category_id,
                    "quantity": quantity,
                    "product_title": (item.get("product_title") or "").strip(),
                    "rank_name": None,
                    "rank_price": None
                })
                continue

        try:
            product_id = int(item.get("product_id"))
        except (TypeError, ValueError, AttributeError):
            continue

        if product_id <= 0:
            continue

        safe_items.append({
            "product_id": product_id,
            "quantity": quantity,
            "product_title": (item.get("product_title") or "").strip(),
            "rank_name": (item.get("rank_name") or "").strip() or None,
            "rank_price": (
                float(item.get("rank_price"))
                if item.get("rank_price") not in (None, "")
                else None
            )
        })

    if not safe_items:
        return base_description

    return f"{base_description}{DEAL_BUNDLE_MARKER}{json.dumps(safe_items, separators=(',', ':'))}"



@app.route('/categories', methods=['GET'])
@app.route('/admin/<slug>/categories', methods=['GET'])
def get_categories(slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, name FROM categories WHERE project_id=%s ORDER BY id",
        (project["id"],)
    )

    data = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(data)



@app.route('/deals', methods=['GET'])
@app.route('/admin/<slug>/deals', methods=['GET'])
def get_deals(slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM deals WHERE project_id=%s ORDER BY id",
        (project["id"],)
    )

    deals = []
    for deal in cursor.fetchall():
        parsed_bundle = parse_deal_bundle_metadata(deal.get("description"))
        deal["description"] = parsed_bundle["description"]
        deal["bundle_items"] = parsed_bundle["bundle_items"]
        deals.append(deal)

    cursor.close()
    conn.close()

    return jsonify(deals)



@app.route('/add_deal', methods=['POST'])
@app.route('/admin/<slug>/add_deal', methods=['POST'])
def add_deal(slug=None):

    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    title = request.form['title']
    description = request.form['description']
    price = request.form['price']
    type_ = request.form['type']
    bundle_items_raw = request.form.get('bundle_items', '[]')
    file = request.files.get('image')

    try:
        bundle_items = json.loads(bundle_items_raw)
    except json.JSONDecodeError:
        bundle_items = []

    image_path = None

    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_path = f"/uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        '''
        INSERT INTO deals
        (project_id, title, description, price, image_path, type, products)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''',
        (
            project["id"],
            title,
            serialize_deal_description(description, bundle_items),
            price,
            image_path,
            type_,
            serialize_deal_products(bundle_items)
        )
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})



@app.route('/delete_deal/<int:id>', methods=['POST', 'DELETE'])
@app.route('/admin/<slug>/delete_deal/<int:id>', methods=['POST', 'DELETE'])
def delete_deal(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM deals WHERE id=%s AND project_id=%s",
        (id, project["id"],)
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


@app.route('/update_deal/<int:id>', methods=['POST'])
@app.route('/admin/<slug>/update_deal/<int:id>', methods=['POST'])
def update_deal(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return "Project not found", 404

    is_json = request.is_json
    data = request.json if is_json else request.form
    bundle_items_raw = data.get('bundle_items') or ([] if is_json else '[]')
    if is_json:
        bundle_items = bundle_items_raw or []
    else:
        try:
            bundle_items = json.loads(bundle_items_raw)
        except json.JSONDecodeError:
            bundle_items = []

    serialized_description = serialize_deal_description(
        data.get('description'),
        bundle_items
    )
    file = request.files.get('image') if not is_json else None
    image_path = None

    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_path = f"/uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()

    if image_path:
        cursor.execute(
            '''
            UPDATE deals
            SET title=%s, description=%s, price=%s, type=%s, products=%s, image_path=%s
            WHERE id=%s AND project_id=%s
            ''',
            (
                data['title'],
                serialized_description,
                data['price'],
                data['type'],
                serialize_deal_products(bundle_items),
                image_path,
                id,
                project["id"],
            )
        )
    else:
        cursor.execute(
            '''
            UPDATE deals
            SET title=%s, description=%s, price=%s, type=%s, products=%s
            WHERE id=%s AND project_id=%s
            ''',
            (
                data['title'],
                serialized_description,
                data['price'],
                data['type'],
                serialize_deal_products(bundle_items),
                id,
                project["id"],
            )
        )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


# ======================
# Serve Uploaded Images
# ======================

@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/project_favicon')
@app.route('/project_favicon/<slug>')
def project_favicon(slug=None):
    slug = slug or (g.project.get("slug") if hasattr(g, "project") and g.project else None)
    if not slug:
        return ("", 204)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT d.image, s.logo_path
        FROM projects p
        LEFT JOIN project_details d ON p.id = d.project_id
        LEFT JOIN project_settings s ON p.id = s.project_id
        WHERE p.slug = %s
    """, (slug,))
    details = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    image_data = details.get('image')
    if image_data:
        if isinstance(image_data, memoryview):
            image_data = image_data.tobytes()

        from flask import Response
        return Response(image_data, mimetype=detect_image_mime(image_data))

    logo_path = (details.get("logo_path") or "").strip().lstrip("/")
    if logo_path:
        project_path = os.path.join(PROJECTS_DIR, slug)
        candidate_path = os.path.join(project_path, logo_path)
        if os.path.exists(candidate_path):
            return send_from_directory(project_path, logo_path)

    return ("", 204)


@app.route('/project_hero_image/<slug>')
def project_hero_image(slug):
    conn = get_db_connection()
    ensure_project_details_hero_image_column(conn)
    ensure_project_details_hero_image_path_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.is_deployed, d.hero_image, d.hero_image_path
        FROM projects p
        LEFT JOIN project_details d ON p.id = d.project_id
        WHERE p.slug = %s
    """, (slug,))
    details = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    if not is_project_deployed(details):
        return ("", 404)

    hero_image_path = (details.get("hero_image_path") or "").strip()
    if hero_image_path:
        normalized_path = hero_image_path.lstrip("/")
        if normalized_path.startswith("uploads/"):
            normalized_path = normalized_path.split("uploads/", 1)[1]
        candidate_path = os.path.join(app.config["UPLOAD_FOLDER"], normalized_path)
        if os.path.exists(candidate_path):
            return redirect(url_for("uploads", filename=normalized_path))

    image_data = details.get("hero_image")
    if isinstance(image_data, memoryview):
        image_data = image_data.tobytes()

    if isinstance(image_data, (bytes, bytearray)) and image_data:
        from flask import Response
        return Response(image_data, mimetype=detect_image_mime(image_data))

    return ("", 204)


@app.route('/pos')
def pos():
    return render_template('pos.html')




def find_free_port(start=5001):
    import socket
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1





#def build_client_app(modules):
    template_app_path = os.path.join(BASE_DIR, "client_template", "app.py")

    if not os.path.exists(template_app_path):
        raise FileNotFoundError(f"Missing client template app: {template_app_path}")

    with open(template_app_path, "r", encoding="utf-8") as f:
        app_code = f.read()


    if modules.get("online_ordering_system"):
        app_code += ORDERING_ROUTES

    if modules.get("staff_admin_system"):
        app_code += WORKER_ROUTES


    app_code += ADMIN_ROUTES

    if modules.get("booking_reservation_system"):
        app_code += RESERVATION_ROUTES

    if modules.get("catering_system"):
        app_code += CATERING_ROUTES

    if modules.get("POS_system"):
        app_code += POS_ROUTES

    app_code += """

if __name__ == "__main__":
    app.run(port=5001, debug=False, use_reloader=False)
"""

    return app_code




#def generate_client_site(project_data):
    project_id = project_data["project_id"]
    slug = project_data["slug"]

    modules = g.modules

    project_path = os.path.join(PROJECTS_DIR, slug)
    os.makedirs(project_path, exist_ok=True)

    # Copy static
    shutil.copytree(
        CLIENT_STATIC_DIR,
        os.path.join(project_path, "static"),
        dirs_exist_ok=True
    )

    # Copy templates
    shutil.copytree(
        os.path.join(BASE_DIR, "client_template", "templates"),
        os.path.join(project_path, "templates"),
        dirs_exist_ok=True
    )
    config = {
        "PROJECT_ID": g.project["id"],
        "PROJECT_NAME": project_data["project_name"],
        "SLOGAN": project_data["slogan"],
        "PROJECT_SLUG": project_data["slug"],
    }

    with open(os.path.join(project_path, "project_config.json"), "w") as f:
        json.dump(config, f, indent=2)

    # Build client app.py
    app_code = build_client_app(modules)

    with open(os.path.join(project_path, "app.py"), "w", encoding="utf-8") as f:
        f.write(app_code)

    print(f"✔ Client site generated at /projects/{slug}")


def load_html(path):
    full_path = os.path.join(MODULE_DIR, path)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()

running_preview_process = None

@app.route("/start_project_preview/<slug>", methods=["POST"])
@login_required
def start_project_preview(slug):
    global running_preview_process

    conn = get_db_connection()
    ensure_projects_deployment_column(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT is_deployed
        FROM projects
        WHERE slug=%s AND client_id=%s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()
    cursor.close()
    conn.close()

    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

    if not is_project_deployed(project):
        return jsonify({
            "success": False,
            "error": "Deploy this project from Config before previewing the restaurant website."
        }), 403

    project_path = os.path.join(PROJECTS_DIR, slug)
    app_path = os.path.join(project_path, "app.py")

    if not os.path.exists(app_path):
        return jsonify({"success": False, "error": "Client app not found"}), 404

    if running_preview_process and running_preview_process.poll() is None:
        running_preview_process.kill()
        running_preview_process.wait()   # 🔥 CRITICAL
        time.sleep(1.5)                 # 🔥 Windows needs this

    try:
        port = find_free_port()

        running_preview_process = subprocess.Popen(
            ["python", "app.py"],
            cwd=project_path,
            env={**os.environ, "FLASK_RUN_PORT": str(port)},
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

        return jsonify({"success": True, "port": port})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@app.route("/webconfig/<slug>")
@login_required
def webconfig(slug):

    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_column(conn)
    ensure_project_details_hero_image_attempts_column(conn)
    ensure_project_details_hero_image_history_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.id, p.project_name, p.slug, p.created_at, p.is_deployed, p.is_deploying,
               d.slogan, d.address, d.phone, d.contact_email, d.pay_in_store,
               d.hero_image, d.hero_image_path, d.hero_image_regen_attempts, d.hero_image_history,
               s.primary_color, s.secondary_color, s.background_color,
               s.logo_path
        FROM projects p
        LEFT JOIN project_details d ON p.id = d.project_id
        LEFT JOIN project_settings s ON p.id = s.project_id
        WHERE p.slug = %s AND p.client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))

    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return "Project not found", 404

    attach_project_context(project)
    project["hero_image_path"] = resolve_hero_image_path(project.get("hero_image_path") or project.get("hero_image"))
    project["hero_image_preview_url"] = url_for("project_hero_image", slug=project["slug"]) if (
        project.get("hero_image_path") or project.get("hero_image")
    ) else ""
    project["hero_image_ready"] = bool(project.get("hero_image_path") or project.get("hero_image"))
    project["hero_image_regen_attempts"] = int(project.get("hero_image_regen_attempts") or 0)
    project["hero_image_regen_remaining"] = max(HERO_IMAGE_REGEN_LIMIT - project["hero_image_regen_attempts"], 0)
    project["hero_image_history"] = [
        {
            "path": path,
            "url": url_for("uploads", filename=path.split("uploads/", 1)[1])
        }
        for path in parse_hero_image_history(project.get("hero_image_history"))
        if path.startswith("uploads/")
    ]
    project["is_deployed"] = is_project_deployed(project)
    project["is_deploying"] = is_project_deploying(project)

    cursor.execute("""
        SELECT *
        FROM project_modules
        WHERE project_id = %s
    """, (project["id"],))

    modules = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    return render_template(
        "webconfig.html",
        project=project,
        modules=modules
    )


@app.route("/admin/<slug>/config/update", methods=["POST"])
@login_required
def update_webconfig(slug):
    payload = request.get_json(silent=True) or {} or request.form

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id
        FROM projects
        WHERE slug = %s AND client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    attach_project_context(project)

    pay_in_store_enabled = False if getattr(g, "trial_active", False) else payload.get("pay_in_store_enabled")

    cursor.execute("""
        UPDATE project_settings
        SET primary_color = %s,
            secondary_color = %s,
            background_color = %s,
            updated_at = NOW()
        WHERE project_id = %s
    """, (
        payload.get("primary_color") or "#2563eb",
        payload.get("secondary_color") or "#0f172a",
        payload.get("background_color") or "#111111",
        project["id"]
    ))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_settings (
                project_id, primary_color, secondary_color, background_color, updated_at
            )
            VALUES (%s, %s, %s, %s, NOW())
        """, (
            project["id"],
            payload.get("primary_color") or "#2563eb",
            payload.get("secondary_color") or "#0f172a",
            payload.get("background_color") or "#111111",
        ))

    cursor.execute("""
        UPDATE project_details
        SET pay_in_store = %s
        WHERE project_id = %s
    """, (
        "true" if pay_in_store_enabled else "false",
        project["id"]
    ))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_details (project_id, pay_in_store)
            VALUES (%s, %s)
        """, (
            project["id"],
            "true" if pay_in_store_enabled else "false"
        ))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"success": True})


@app.route("/delete_project/<slug>", methods=["POST"])
@login_required
def delete_project(slug):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM projects
        WHERE slug = %s AND client_id = %s
    """, (slug, session["client_id"]))

    conn.commit()
    cursor.close()
    conn.close()

    project_path = os.path.join(PROJECTS_DIR, slug)

    if os.path.exists(project_path):
        shutil.rmtree(project_path)

    return jsonify({"success": True})


@app.route('/deploy/<slug>')
@login_required
def deploy_page(slug):
    conn = get_db_connection()
    ensure_projects_deployment_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM projects
        WHERE slug=%s AND client_id=%s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()

    cursor.close()
    conn.close()

    if not project:
        return "Project not found", 404

    return render_template("deploy.html", project=project)




def require_module(name):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not g.modules.get(name):
                return "Feature disabled", 403
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator


NAV_RULES = [
    ("menu", "Menu", None),  # Always
    ("about", "About", None),
    ("contact", "Contact", None),

    ("catering", "Catering", "catering_system"),
    ("reservations", "Reservations", "booking_reservation_system"),
]





def build_navbar(modules):
    links = []

    for route, label, required_module in NAV_RULES:
        if required_module is None or modules.get(required_module):
            try:
                href = url_for(route)
            except Exception:
                href = '#'
            links.append(f'<a href="{href}">{label}</a>')

    return "\n".join(links)





# === CORE PAGES (ALWAYS) ===

def build_page_context(modules):
    pay_in_store_enabled = (
        get_project_pay_in_store(g.project["id"])
        if hasattr(g, "project") and not getattr(g, "trial_active", False)
        else False
    )
    pay_in_store_section = """
      <div class="checkout-divider">
        <span>or</span>
      </div>

      <button class="btn btn-secondary order-btn" onclick="goToInstoreCheckout()">
        Place Order
      </button>
    """ if pay_in_store_enabled else ""

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
        ctx["CART_ICON"] = load_html("layout/cart_icon.html").replace("<!-- PAY_IN_STORE_SECTION -->", pay_in_store_section)
        ctx["CART_SIDEBAR"] = load_html("layout/cart_sidebar.html").replace("<!-- PAY_IN_STORE_SECTION -->", pay_in_store_section)
        ctx["ORDERING_ENABLED"] = modules.get("online_ordering_system")
        ctx["PAY_IN_STORE_ENABLED"] = pay_in_store_enabled

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
    if not hasattr(g, "project"):
        return "Project not found", 404
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    return render_template("menu.html", **ctx)


@app.route("/about")
def about():
    if not hasattr(g, "project"):
        return "Project not found", 404
    modules = g.modules

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
    """, (g.project["id"],))
    data = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    ctx["story"] = data.get("story", "")

    return render_template("about.html", **ctx)


@app.route("/contact", methods=['GET', 'POST'])
def contact():
    if not hasattr(g, "project"):
        return "Project not found", 404    
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    if request.method == "POST":
        name = request.form.get("name")
        contact_info = request.form.get("email")
        message = request.form.get("message")
        client_email = get_project_client_email(g.project["id"])

        conn = get_db_connection()
        ensure_questions_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO questions
            (project_id, name, email, message)
            VALUES (%s, %s, %s, %s)
        """, (g.project["id"], name, contact_info, message))
        conn.commit()
        cursor.close()
        conn.close()

        send_email(
            to=client_email,
            subject=f"General Contact - {g.project.get('project_name')}",
            html_body=f"<pre>New Contact Inquiry\n\nName: {name}\nContact: {contact_info}\n\nMessage:\n{message}</pre>",
            sender=DEFAULT_INFO_EMAIL
        )
        ctx["success"] = True

    return render_template("contact.html", **ctx)



@app.route('/catering', methods=['GET', 'POST'])
def catering():
    if not hasattr(g, "project"):
        return "Project not found", 404    
    modules = g.modules

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
        client_email = get_project_client_email(g.project["id"])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO catering_inquiries
            (project_id, name, phone, email, event_date, guests, event_type, details)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (g.project["id"], name, phone, email, event_date, guests, event_type, details))

        conn.commit()
        cursor.close()
        conn.close()

        send_email(
            to=client_email,
            subject=f"Catering Inquiry - {g.project.get('project_name')}",
            html_body=f"<pre>New Catering Inquiry\n\nName: {name}\nPhone: {phone}\nEmail: {email}\nDate: {event_date}\nGuests: {guests}\nType: {event_type}\n\nDetails:\n{details}</pre>",
            sender=DEFAULT_INFO_EMAIL
        )

        ctx["success"] = True

    return render_template("catering.html", **ctx)


@app.route('/reservations', methods=['GET', 'POST'])
def reservations():
    if not hasattr(g, "project"):
        return "Project not found", 404    
    modules = g.modules

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
        client_email = get_project_client_email(g.project["id"])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO reservations
            (project_id, name, email, phone, reservation_date, reservation_time, guests, special_requests)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (g.project["id"], name, email, phone, reservation_date, reservation_time, guests, special_requests))

        conn.commit()
        cursor.close()
        conn.close()

        send_email(
            to=email,
            subject=f"Reservation Confirmation - {g.project.get('project_name')}",
            html_body=f"<pre>Reservation Confirmation\n\nName: {name}\nDate: {reservation_date}\nTime: {reservation_time}\nGuests: {guests}\n\nSpecial Requests:\n{special_requests}</pre>",
            sender=DEFAULT_INFO_EMAIL,
            reply_to=client_email
        )

        ctx["success"] = True

    return render_template("reservations.html", **ctx)






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
    theme = get_project_settings(g.project["id"])

    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_column(conn)
    cursor = conn.cursor(dictionary=True)

    bg = theme.get("background_color") or "#111111"
    accent = theme.get("primary_color") or "#2563eb"
    secondary = theme.get("secondary_color") or accent

    accent_hover = lighten(accent)
    bg_contrast = get_contrast(bg)
    accent_contrast = get_contrast(accent)

    # --- DETAILS ---
    cursor.execute("""
        SELECT address, phone, slogan, contact_email, operating_hours, image, hero_image, hero_image_path
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (g.project["id"],))
    details = cursor.fetchone() or {}

    address = details.get("address", "")
    phone = details.get("phone", "")

    cursor.close()
    conn.close()

    try:
        favicon_url = url_for("project_favicon")
    except Exception:
        favicon_url = ""

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
        "project_name": g.project.get("project_name"),
        "slogan": details.get("slogan"),

        # contact
        "address": address,
        "phone": phone,
        "CONTACT_EMAIL": details.get("contact_email"),
        "operating_hours": details.get("operating_hours", ""),

        # modules
        "MODULES": modules,

        "PROJECT_SLUG": g.project["slug"],

        "favicon_url": favicon_url,
        "hero_image_path": (
            resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
            or ("project_hero_image" if details.get("hero_image") else "")
        ),
        "hero_image": normalize_hero_image_value(details.get("hero_image")),
        "hero_image_css": get_hero_image_css(details.get("hero_image_path") or details.get("hero_image"), slug=g.project["slug"]),
        "PAY_IN_STORE_ENABLED": (
            get_project_pay_in_store(g.project["id"])
            if not getattr(g, "trial_active", False)
            else False
        ),
    }



@app.route('/deploy_project/<slug>', methods=['POST'])
@login_required
def deploy_project(slug):
    conn = None
    cursor = None
    project = None

    try:
        data = request.get_json(silent=True) or {}

        domain_type = data.get("type")
        value = data.get("value")

        if domain_type != "subdomain":
            return jsonify({
                "success": False,
                "message": "Only subdomains supported"
            }), 400

        conn = get_db_connection()
        ensure_projects_deployment_column(conn)
        ensure_project_details_featured_column(conn)
        ensure_project_details_hero_image_column(conn)

        cursor = conn.cursor(dictionary=True)

        # 🔒 GET PROJECT
        cursor.execute("""
            SELECT id, project_name, slug, is_deployed, is_deploying
            FROM projects
            WHERE slug=%s AND client_id=%s
            LIMIT 1
        """, (slug, session["client_id"]))
        project = cursor.fetchone()

        if not project:
            return jsonify({
                "success": False,
                "message": "Project not found"
            }), 404

        if is_project_live(project):
            return jsonify({
                "success": False,
                "message": "This project is already deployed."
            }), 409

        if is_project_deploying(project):
            return jsonify({
                "success": False,
                "message": "This project is already deploying."
            }), 409

        cursor.execute("""
            UPDATE projects
            SET is_deploying=TRUE
            WHERE id=%s
        """, (project["id"],))
        conn.commit()

        # 🚀 MAIN DEPLOY LOGIC
        finalization = finalize_project_assets(project, conn, cursor)

        cursor.execute("""
            UPDATE projects
            SET is_deployed=TRUE,
                is_deploying=FALSE
            WHERE id=%s
        """, (project["id"],))

        conn.commit()

        return jsonify({
            "success": True,
            "message": "Deployment successful",
            "slug": slug,
            "url": f"https://{slug}.dinebloc.com/"
        })

    except Exception as e:
        print("DEPLOY ERROR:", str(e))

        if conn and project:
            try:
                rollback_cursor = conn.cursor()
                rollback_cursor.execute("""
                    UPDATE projects
                    SET is_deploying=FALSE
                    WHERE id=%s
                """, (project["id"],))
                conn.commit()
                rollback_cursor.close()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

        if conn:
            try:
                conn.rollback()
            except Exception:
                pass

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



@app.route('/admin/<slug>/create_worker', methods=['POST'])
@login_required
def create_worker(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False), 403

    # generate username (10 chars)
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

    # generate strong password (12 chars)
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(random.choices(chars, k=12))

    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    ensure_worker_password_column(conn)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO workers (project_id, username, password_hash, password_visible)
        VALUES (%s, %s, %s, %s)
    """, (project["id"], username, password_hash, password))

    worker_id = cursor.lastrowid

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "success": True,
        "id": worker_id,
        "username": username,
        "password": password
    })


@app.route('/admin/<slug>/get_workers')
@login_required
def get_workers(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify([])

    conn = get_db_connection()
    ensure_worker_password_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, username, created_at, password_visible
        FROM workers
        WHERE project_id=%s
        ORDER BY created_at DESC, id DESC
    """, (project["id"],))

    workers = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(workers)


@app.route('/admin/<slug>/delete_worker/<int:worker_id>', methods=['POST', 'DELETE'])
@login_required
def delete_worker(slug, worker_id):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM workers
        WHERE id=%s AND project_id=%s
    """, (worker_id, project["id"]))
    conn.commit()
    deleted = cursor.rowcount > 0
    cursor.close()
    conn.close()

    if not deleted:
        return jsonify(success=False, error="Worker not found"), 404

    return jsonify(success=True)



def generate_featured_section(description, business_name):
    prompt = f"""
You are a professional website UI copywriter.

Generate a PREMIUM featured section for a website homepage.

STRICT RULES:
- Output ONLY HTML
- NO <style>, NO inline CSS
- Use ONLY these classes:
  container, section-heading-block, section-kicker,
  section-title, section-intro, grid dishes, dish-card

CONTENT:
- 1 heading block
- 3–6 feature cards
- Exactly 3 feature cards
- Make it modern, premium, persuasive
- This section should advertise the business overall, not specific products
- Do NOT mention burgers, fries, drinks, ingredients, menu items, product names, dishes, patties, or specific food items
- Focus on brand identity, quality, local trust, atmosphere, convenience, and community appeal
- Keep the title elegant and concise
- Keep the intro to 1-2 short sentences
- Keep each card title short
- Keep each card paragraph compact so the layout stays balanced

Business Name: {business_name}
Business Description: {description}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )

    return response.choices[0].message.content


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

    article_blocks = re.findall(
        r"<article\b[^>]*class=(['\"]).*?dish-card.*?\1[^>]*>.*?</article>",
        content,
        flags=re.IGNORECASE | re.DOTALL
    )

    if len(article_blocks) > 3:
        trimmed_blocks = "".join(article_blocks[:3])
        content = re.sub(
            r"(<div\b[^>]*class=(['\"]).*?grid\s+dishes.*?\2[^>]*>).*?(</div>)",
            lambda match: f"{match.group(1)}{trimmed_blocks}{match.group(3)}",
            content,
            count=1,
            flags=re.IGNORECASE | re.DOTALL
        )

    return content


def get_featured_section_html(saved_html=None):
    cleaned = sanitize_featured_html(saved_html)
    return cleaned or get_default_featured_section_html()


def finalize_project_assets(project, conn, cursor):
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_attempts_column(conn)
    ensure_project_details_hero_image_history_column(conn)
    cursor.execute("""
        SELECT description, featured_html, hero_image, hero_image_path
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone() or {}

    description = (details.get("description") or "").strip()
    if not description:
        raise ValueError("Add a business description before deploying so we can generate the featured section and hero image.")

    featured_html = sanitize_featured_html(details.get("featured_html"))
    hero_image = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
    generated_featured = False
    generated_hero = False
    theme = get_project_settings(project["id"])

    if not featured_html:
        featured_html = sanitize_featured_html(
            generate_featured_section(description, project["project_name"])
        )
        generated_featured = bool(featured_html)

        if generated_featured:
            cursor.execute("""
                UPDATE project_details
                SET featured_html=%s
                WHERE project_id=%s
            """, (featured_html, project["id"]))

            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO project_details (project_id, featured_html)
                    VALUES (%s, %s)
                """, (project["id"], featured_html))

            conn.commit()

    if not hero_image:
        hero_image = generate_hero_image(
            description,
            project["project_name"],
            project["id"],
            primary_color=theme.get("primary_color"),
            secondary_color=theme.get("secondary_color"),
            background_color=theme.get("background_color"),
        )
        generated_hero = bool(hero_image)

    if not featured_html:
        featured_html = get_default_featured_section_html()

    cursor.execute("""
        UPDATE project_details
        SET featured_html=%s, hero_image_path=%s, hero_image=NULL
        WHERE project_id=%s
    """, (featured_html, hero_image or None, project["id"]))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_details (project_id, featured_html, hero_image_path, hero_image)
            VALUES (%s, %s, %s, NULL)
        """, (project["id"], featured_html, hero_image or None))

    return {
        "generated_featured": generated_featured,
        "generated_hero": generated_hero,
        "featured_html": featured_html,
        "hero_image_ready": bool(hero_image),
    }


@app.route("/finalize-project", methods=["POST"])
@login_required
def finalize_project():
    return jsonify({
        "success": False,
        "error": "Finalization now happens during deployment from Config."
    }), 410

    payload = request.get_json(silent=True) or {}
    slug = (payload.get("slug") or "").strip()

    if not slug:
        return jsonify({"success": False, "error": "Missing project slug."}), 400

    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_featured_column(conn)
    ensure_project_details_hero_image_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, project_name
        FROM projects
        WHERE slug=%s AND client_id=%s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Project not found."}), 404

    cursor.execute("""
        SELECT description, featured_html, hero_image, hero_image_path
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone() or {}

    description = (details.get("description") or "").strip()
    if not description:
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": "Add a business description before confirming so we can generate the featured section and hero image."
        }), 400

    # 🔥 1. Generate FEATURED HTML
    featured_html = sanitize_featured_html(details.get("featured_html"))

    # 🔥 2. Generate HERO IMAGE
    hero_image = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
    generated_featured = False
    generated_hero = False

    try:
        if not featured_html:
            featured_html = sanitize_featured_html(
                generate_featured_section(description, project["project_name"])
            )
            generated_featured = bool(featured_html)

            if generated_featured:
                cursor.execute("""
                    UPDATE project_details
                    SET featured_html=%s
                    WHERE project_id=%s
                """, (featured_html, project["id"]))

                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO project_details (project_id, featured_html)
                        VALUES (%s, %s)
                    """, (project["id"], featured_html))

                conn.commit()

        if not hero_image:
            hero_image = generate_hero_image(description, project["project_name"], project["id"])
            generated_hero = bool(hero_image)
    except Exception as exc:
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": f"Website finalization failed: {exc}"
        }), 502

    if not featured_html:
        featured_html = get_default_featured_section_html()

    # 🔥 3. SAVE BOTH
    cursor.execute("""
        UPDATE project_details
        SET featured_html=%s, hero_image_path=%s, hero_image=NULL
        WHERE project_id=%s
    """, (featured_html, hero_image or None, project["id"]))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_details (project_id, featured_html, hero_image_path, hero_image)
            VALUES (%s, %s, %s, NULL)
        """, (project["id"], featured_html, hero_image or None))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "success": True,
        "generated_featured": generated_featured,
        "generated_hero": generated_hero,
        "featured_html": featured_html,
        "hero_image_ready": bool(hero_image)
    })



def _legacy_requests_generate_hero_image(description, project_name, project_id=0):
    return generate_hero_image(description, project_name, project_id)

    prompt = f"""
    A realistic, high-quality, cinematic photograph representing a business.

    Business: {project_name}
    Description: {description}

    Requirements:
    - minimalistic composition
    - visually clean and modern
    - not cluttered
    - soft lighting, natural tones
    - suitable as website hero background
    - slight depth of field (background blur friendly)
    - no text, no logos
    - not overly dramatic or exaggerated
    - visually appealing for branding
    """

    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer YOUR_OPENAI_API_KEY"
        },
        json={
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": "1792x1024"   # 👈 HERO SIZE
        }
    )

    data = response.json()

    image_base64 = data["data"][0]["b64_json"]
    image_bytes = base64.b64decode(image_base64)

    # Save file
    filename = f"{secrets.token_hex(8)}.jpg"
    save_path = os.path.join("static/generated", filename)

    os.makedirs("static/generated", exist_ok=True)

    with open(save_path, "wb") as f:
        f.write(image_bytes)

    return f"/static/generated/{filename}"


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
    if value.startswith("uploads/"):
        candidate_path = os.path.join(app.config["UPLOAD_FOLDER"], value.split("uploads/", 1)[1])
        if not os.path.exists(candidate_path):
            return ""
        return value

    return value


def save_hero_image_bytes(image_bytes, project_id):
    if not image_bytes:
        return ""

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    filename = f"hero_{project_id}_{int(time.time())}.png"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    with open(filepath, "wb") as f:
        f.write(image_bytes)

    return f"uploads/{filename}"


def get_hero_image_css(hero_image, slug=None):
    image_value = normalize_hero_image_value(hero_image)

    if isinstance(image_value, (bytes, bytearray)):
        if not slug:
            return "none"
        image_url = url_for("project_hero_image", slug=slug)
    else:
        image_url = ""
        if image_value:
            normalized = str(image_value).lstrip("/")
            if normalized.startswith("uploads/"):
                image_url = url_for("uploads", filename=normalized.split("uploads/", 1)[1])
            elif normalized.startswith(("http://", "https://", "/")):
                image_url = normalized
            else:
                image_url = url_for("uploads", filename=normalized)

    return f'url("{image_url}")' if image_url else "none"


def generate_hero_image(description, project_name, project_id=0, primary_color=None, secondary_color=None, background_color=None):
    primary_color = (primary_color or "#2563eb").strip()
    secondary_color = (secondary_color or "#0f172a").strip()
    background_color = (background_color or "#111111").strip()
    prompt = f"""
A realistic website hero image for a business website.

Business: {project_name}
Description: {description}
Primary colour: {primary_color}
Secondary colour: {secondary_color}
Background colour: {background_color}

Requirements:
- realistic photography style
- clearly relevant to the business description
- clean, modern, believable, and premium and a bit of a blurry effect
- NO WRITING or TEXT in this image WHATSOEVER
- suitable for a homepage hero with text overlay
- leave calm negative space for a headline and button (around the middle)
- image contrast must keep white or near-white hero text readable
- not too minimalist, not too busy, not too dramatic
- realistic lighting and materials
- use the listed brand colours as gentle scene accents, styling cues, or environmental tones
- avoid placing key detail where hero text would normally sit
- no text, no logos, no watermarks
- composition should feel trustworthy, polished, and commercially usable
"""

    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1536x1024"
    )

    image_bytes = b""
    image_data = response.data[0] if getattr(response, "data", None) else None

    if image_data and getattr(image_data, "b64_json", None):
        image_bytes = base64.b64decode(image_data.b64_json)
    elif image_data and getattr(image_data, "url", None):
        with urlopen(image_data.url) as remote:
            image_bytes = remote.read()

    if not image_bytes:
        return ""

    return save_hero_image_bytes(image_bytes, project_id)


@app.route("/admin/<slug>/hero-image/regenerate", methods=["POST"])
@login_required
def regenerate_project_hero_image(slug):
    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_column(conn)
    ensure_project_details_hero_image_attempts_column(conn)
    ensure_project_details_hero_image_history_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, project_name, is_deployed, is_deploying
        FROM projects
        WHERE slug = %s AND client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Project not found."}), 404

    if not is_project_live(project):
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Deploy the project before requesting a new hero image."}), 409

    cursor.execute("""
        SELECT description, hero_image, hero_image_path, hero_image_regen_attempts, hero_image_history
        FROM project_details
        WHERE project_id = %s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone() or {}

    description = (details.get("description") or "").strip()
    if not description:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Add a business description first."}), 400

    attempts_used = int(details.get("hero_image_regen_attempts") or 0)
    if attempts_used >= HERO_IMAGE_REGEN_LIMIT:
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": "No regenerate attempts remain.",
            "attempts_remaining": 0
        }), 409

    current_image = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
    history = parse_hero_image_history(details.get("hero_image_history"))
    if current_image and current_image not in history:
        history.insert(0, current_image)

    theme = get_project_settings(project["id"])
    new_image = generate_hero_image(
        description,
        project["project_name"],
        project["id"],
        primary_color=theme.get("primary_color"),
        secondary_color=theme.get("secondary_color"),
        background_color=theme.get("background_color"),
    )

    if not new_image:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Hero image generation failed."}), 502

    attempts_used += 1
    cursor.execute("""
        UPDATE project_details
        SET hero_image_path=%s,
            hero_image=NULL,
            hero_image_regen_attempts=%s,
            hero_image_history=%s
        WHERE project_id=%s
    """, (
        new_image,
        attempts_used,
        serialize_hero_image_history(history),
        project["id"]
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "success": True,
        "attempts_remaining": max(HERO_IMAGE_REGEN_LIMIT - attempts_used, 0)
    })


@app.route("/admin/<slug>/hero-image/select", methods=["POST"])
@login_required
def select_project_hero_image(slug):
    payload = request.get_json(silent=True) or {} or request.form
    selected_path = resolve_hero_image_path(payload.get("path"))

    if not selected_path:
        return jsonify({"success": False, "error": "Choose a saved hero image first."}), 400

    conn = get_db_connection()
    ensure_project_details_hero_image_path_column(conn)
    ensure_project_details_hero_image_column(conn)
    ensure_project_details_hero_image_history_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.id
        FROM projects p
        WHERE p.slug = %s AND p.client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Project not found."}), 404

    cursor.execute("""
        SELECT hero_image, hero_image_path, hero_image_history
        FROM project_details
        WHERE project_id = %s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone() or {}

    current_image = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
    history = parse_hero_image_history(details.get("hero_image_history"))
    available_images = set(history)
    if current_image:
        available_images.add(current_image)

    if selected_path not in available_images:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "That hero image is no longer available."}), 404

    updated_history = [path for path in history if path != selected_path]
    if current_image and current_image != selected_path and current_image not in updated_history:
        updated_history.insert(0, current_image)

    cursor.execute("""
        UPDATE project_details
        SET hero_image_path=%s,
            hero_image=NULL,
            hero_image_history=%s
        WHERE project_id=%s
    """, (
        selected_path,
        serialize_hero_image_history(updated_history),
        project["id"]
    ))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_details (project_id, hero_image_path, hero_image, hero_image_history)
            VALUES (%s, %s, NULL, %s)
        """, (project["id"], selected_path, serialize_hero_image_history(updated_history)))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"success": True})



@app.route("/sitemap.xml")
def sitemap():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT slug FROM projects WHERE slug IS NOT NULL")
    projects = cursor.fetchall()

    cursor.close()
    conn.close()

    urls = []

    # Main site
    urls.append("https://dinebloc.com/")
    urls.append("https://www.dinebloc.com/")

    # Add each project
    for p in projects:
        slug = p["slug"]
        urls.append(f"https://{slug}.dinebloc.com/")

    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for url in urls:
        xml.append("<url>")
        xml.append(f"<loc>{url}</loc>")
        xml.append(f"<lastmod>{datetime.utcnow().date()}</lastmod>")
        xml.append("</url>")

    xml.append("</urlset>")

    return Response("\n".join(xml), mimetype="application/xml")


if __name__ == "__main__":
    app.run(debug=True, port=5000)



