print("APP VERSION: 999")
from flask import (
    Flask, request, jsonify, render_template, render_template_string,
    redirect, url_for, session, flash, send_from_directory, send_file, Response, g
)
from flask_mail import Mail, Message

from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from cryptography.fernet import Fernet, InvalidToken

import mysql.connector, pymysql
from mysql.connector import errorcode
import stripe

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from functools import wraps
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from markupsafe import Markup, escape
from textwrap import wrap

import os, stripe
import resend
import base64
import json
import time
import re
import mimetypes
import shutil
import uuid
import subprocess
import threading
import secrets
import random
import string
import zipfile
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from urllib.parse import quote
from io import BytesIO
from jinja2 import ChoiceLoader, FileSystemLoader
import logging
import sys
logging.basicConfig(level=logging.INFO)

# Ensure app logs are captured by Gunicorn/journalctl when running under systemd
root_logger = logging.getLogger()
gunicorn_error_logger = logging.getLogger('gunicorn.error')
if gunicorn_error_logger.handlers:
    for handler in gunicorn_error_logger.handlers:
        if handler not in root_logger.handlers:
            root_logger.addHandler(handler)
            handler.setLevel(logging.INFO)

gunicorn_access_logger = logging.getLogger('gunicorn.access')
if gunicorn_access_logger.handlers:
    for handler in gunicorn_access_logger.handlers:
        if handler not in root_logger.handlers:
            root_logger.addHandler(handler)
            handler.setLevel(logging.INFO)

from dotenv import load_dotenv
load_dotenv()
from flask import Request

Request.on_json_loading_failed = lambda self, e: None

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
resend.api_key = os.getenv("RESEND_API_KEY")

PAYMENTS_ENABLED = False
TRIAL_APPLICATION_DEADLINE = datetime(2026, 8, 1, 23, 59, 59)
TRIAL_DURATION = timedelta(days=90)
HERO_IMAGE_REGEN_LIMIT = 2
trial_application_deadline = TRIAL_APPLICATION_DEADLINE.strftime("%Y-%m-%d")
DEFAULT_INFO_EMAIL = "info@dinebloc.com"
DEFAULT_NOREPLY_EMAIL = "info@dinebloc.com"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(30 * 1024 * 1024)))
BULK_PRODUCT_MAX_BYTES = int(os.getenv("BULK_PRODUCT_MAX_BYTES", str(MAX_UPLOAD_BYTES)))
BULK_DEAL_MAX_BYTES = int(os.getenv("BULK_DEAL_MAX_BYTES", str(MAX_UPLOAD_BYTES)))
UPLOAD_REQUEST_OVERHEAD_BYTES = int(os.getenv("UPLOAD_REQUEST_OVERHEAD_BYTES", str(1024 * 1024)))
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + UPLOAD_REQUEST_OVERHEAD_BYTES
BULK_PRODUCT_MAX_REQUEST_BYTES = BULK_PRODUCT_MAX_BYTES + UPLOAD_REQUEST_OVERHEAD_BYTES
BULK_DEAL_MAX_REQUEST_BYTES = BULK_DEAL_MAX_BYTES + UPLOAD_REQUEST_OVERHEAD_BYTES


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.join(BASE_DIR, "module_library", "html")
CLIENT_STATIC_DIR = os.path.join(BASE_DIR, "client_template", "static")
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")




# Print payment configuration at startup
logging.info(f"[STARTUP] ========== PAYMENT CONFIGURATION ==========")
logging.info(f"[STARTUP] PAYMENTS_ENABLED: {PAYMENTS_ENABLED}")
logging.info(f"[STARTUP] stripe.api_key configured: {bool(stripe.api_key)}")
logging.info(f"[STARTUP] STRIPE_PUBLISHABLE_KEY configured: {bool(STRIPE_PUBLISHABLE_KEY)}")
logging.info(f"[STARTUP] =============================================")


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




print("MODULE_DIR:", MODULE_DIR)

from openai import OpenAI

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
except Exception:
    qrcode = None
    ERROR_CORRECT_M = None

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
except Exception:
    HexColor = None
    A4 = None
    ImageReader = None
    canvas = None

try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    logging.exception("Failed to initialize OpenAI client — AI-powered features (hero image, "
                       "featured section, QR poster copy, menu import) will be unavailable until "
                       "OPENAI_API_KEY is fixed. The rest of the app still runs.")
    client = None

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

# ── Security configuration ────────────────────────────────────────────────────
# Raise the Flask request body limit enough to avoid premature 413 rejections
# while still enforcing actual upload limits inside the route handlers.
app.config['MAX_CONTENT_LENGTH'] = max(
    MAX_UPLOAD_REQUEST_BYTES,
    BULK_PRODUCT_MAX_REQUEST_BYTES,
    BULK_DEAL_MAX_REQUEST_BYTES,
    50 * 1024 * 1024
)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

@app.before_request
def debug_request():
    if request.method in ['POST', 'PUT']:
        logging.debug("%s %s (Content-Type: %s)", request.method, request.path, request.content_type)

app.jinja_loader = ChoiceLoader([
    FileSystemLoader(os.path.join(BASE_DIR, "templates")),  # builder
    FileSystemLoader(os.path.join(BASE_DIR, "client_template", "templates"))  # client
])

app.secret_key = os.getenv("SECRET_KEY")
mail = Mail(app)

# ── CORS (credentials allowed for same-site AJAX; restrict origins in prod) ──
_allowed_origins = [o.strip() for o in os.getenv('ALLOWED_ORIGINS', '*').split(',') if o.strip()]
CORS(app, supports_credentials=True, origins=_allowed_origins)

# ── Rate limiter (in-memory; swap storage_uri for Redis in production) ────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ── Security response headers ─────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('X-XSS-Protection', '1; mode=block')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    if os.getenv('FLASK_ENV') == 'production':
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains; preload')
    return response

# ── Fernet helpers for encrypting sensitive stored values ─────────────────────
def _get_fernet():
    key = os.getenv("FERNET_KEY", "")
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None

def _fernet_encrypt(plaintext: str) -> str:
    f = _get_fernet()
    if not f or not plaintext:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()

def _fernet_decrypt(ciphertext: str) -> str:
    f = _get_fernet()
    if not f or not ciphertext:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ciphertext  # legacy plaintext fallback

@app.errorhandler(BadRequest)
def handle_bad_request(e):
    print("DEBUG: BadRequest caught:", e)

    # FORCE treat ALL BadRequest as normal form submission
    return render_signup_page(error="Invalid form submission. Please try again."), 200


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(e):
    msg = (
        f"[REQUEST_ENTITY_TOO_LARGE] path={request.path} method={request.method} "
        f"endpoint={request.endpoint} content_length={request.content_length} "
        f"MAX_CONTENT_LENGTH={app.config.get('MAX_CONTENT_LENGTH')} error={e}"
    )
    logging.error(msg)
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
    return jsonify({
        "success": False,
        "error": f"That file is too large. Please use a file under {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        "debug": {
            "path": request.path,
            "method": request.method,
            "endpoint": request.endpoint,
            "content_length": request.content_length,
            "MAX_CONTENT_LENGTH": app.config.get('MAX_CONTENT_LENGTH')
        }
    }), 413


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
        print("SEND_EMAIL CALLED:", to, subject)
        payload = {
            "from": "Dinebloc <info@dinebloc.com>",
            "to": [to],
            "subject": subject,
            "html": html_body,
        }
        if reply_to:
            payload["reply_to"] = reply_to

        response = resend.Emails.send(payload)
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
    <p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#334155;">Verify your email to activate your dashboard, continue your setup, and start your 3-month free trial.</p>
    <div style="margin:24px 0;">
      <a href="{safe_link}" style="display:inline-block;padding:14px 24px;border-radius:12px;background:linear-gradient(135deg,#0b63ff,#1d4ed8);color:#ffffff;text-decoration:none;font-weight:700;">Verify &amp; Activate Account</a>
    </div>
    <div style="padding:18px 20px;border-radius:18px;background:#f8fafc;border:1px solid #e2e8f0;">
      <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">What happens next</div>
      <ul style="margin:12px 0 0;padding-left:18px;color:#334155;line-height:1.8;">
        <li>Your Dinebloc account becomes active.</li>
        <li>You can access the dashboard and start building your restaurant site.</li>
        <li>Your free trial is active for 3 months from today.</li>
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
        <div style="margin-top:6px;font-size:14px;color:#334155;">3 months from sign-up</div>
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


def _row(label, value):
    if not value:
        return ""
    return f"""
    <tr>
      <td style="padding:10px 14px;font-size:13px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;vertical-align:top;width:1%;">{escape(label)}</td>
      <td style="padding:10px 14px;font-size:15px;color:#0f172a;vertical-align:top;">{escape(str(value))}</td>
    </tr>"""


def _details_table(rows_html):
    return f"""
    <table style="width:100%;border-collapse:collapse;margin:18px 0;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
      <tbody>{rows_html}</tbody>
    </table>"""


def build_client_notification_email(request_type, submitter_name, restaurant_name, rows_html):
    """Notify the restaurant that a new request has arrived."""
    type_labels = {
        "contact": "General Enquiry",
        "catering": "Catering Request",
        "reservation": "Reservation Request",
    }
    label = type_labels.get(request_type, "Request")
    safe_name = escape(submitter_name or "Someone")
    safe_restaurant = escape(restaurant_name or "your restaurant")
    content_html = f"""
    <p style="margin:0 0 18px;font-size:15px;line-height:1.75;color:#334155;">
      <strong>{safe_name}</strong> just submitted a <strong>{label}</strong> through your website.
      Log in to your Dinebloc inbox to view and respond.
    </p>
    {_details_table(rows_html)}
    <p style="margin:18px 0 0;font-size:13px;color:#64748b;line-height:1.7;">
      Reply directly to this email or log in to send a follow-up from your dashboard.
    </p>"""
    return build_email_shell(
        f"New {label}",
        f"A new request has arrived for {safe_restaurant}.",
        content_html,
        accent="#0f172a"
    )


def build_customer_confirmation_email(request_type, submitter_name, restaurant_name, rows_html):
    """Send a confirmation receipt to the customer."""
    type_labels = {
        "contact": "enquiry",
        "catering": "catering request",
        "reservation": "reservation request",
    }
    label = type_labels.get(request_type, "request")
    safe_name = escape(submitter_name or "there")
    safe_restaurant = escape(restaurant_name or "the restaurant")
    content_html = f"""
    <p style="margin:0 0 18px;font-size:15px;line-height:1.75;color:#334155;">
      Hi {safe_name}, we have received your {label} and will be in touch with you shortly.
    </p>
    {_details_table(rows_html)}
    <div style="margin:22px 0;padding:18px 20px;border-radius:14px;background:#f0fdf4;border:1px solid #bbf7d0;">
      <p style="margin:0;font-size:14px;color:#166534;line-height:1.7;">
        <strong>What happens next?</strong><br>
        A member of the team at {safe_restaurant} will review your {label} and reach out to confirm the details with you.
      </p>
    </div>
    <p style="margin:0;font-size:13px;color:#64748b;line-height:1.7;">
      If you have any questions in the meantime, feel free to reply to this email.
    </p>"""
    return build_email_shell(
        f"We received your {label}",
        f"Thanks for getting in touch with {safe_restaurant}.",
        content_html,
        accent="#0f172a"
    )


def build_followup_email(restaurant_name, message_body):
    """Styled follow-up / response email sent from the admin inbox."""
    safe_restaurant = escape(restaurant_name or "the restaurant")
    safe_body = escape(message_body or "")
    content_html = f"""
    <div style="padding:22px 24px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;font-size:15px;line-height:1.8;color:#0f172a;white-space:pre-wrap;">{safe_body}</div>
    <p style="margin:18px 0 0;font-size:13px;color:#64748b;line-height:1.7;">
      This message was sent by {safe_restaurant}. You can reply to this email to respond directly.
    </p>"""
    return build_email_shell(
        f"Message from {safe_restaurant}",
        "You have a new message regarding your request.",
        content_html,
        accent="#0f172a"
    )


def build_feedback_request_email(restaurant_name, customer_name, order_number, feedback_url):
    safe_restaurant = escape(restaurant_name or "the restaurant")
    safe_name = escape(customer_name or "there")
    safe_order = escape(order_number or "")
    safe_url = feedback_url
    stars_html = "".join(
        f'<a href="{safe_url}?rating={i}" style="display:inline-block;margin:0 5px;padding:12px 18px;'
        f'border-radius:12px;background:{"#f59e0b" if i <= 3 else "#22c55e"};color:#ffffff;'
        f'text-decoration:none;font-size:18px;font-weight:800;">{i}★</a>'
        for i in range(1, 6)
    )
    content_html = f"""
    <p style="margin:0 0 18px;font-size:15px;line-height:1.75;color:#334155;">
      Hi {safe_name}, your order{f" <strong>#{safe_order}</strong>" if safe_order else ""} from
      <strong>{safe_restaurant}</strong> is complete. We hope you enjoyed it!
    </p>
    <p style="margin:0 0 20px;font-size:15px;line-height:1.75;color:#334155;">
      Got 30 seconds? Tap a star to rate your experience — it means a lot to the team.
    </p>
    <div style="margin:24px 0;text-align:center;">
      {stars_html}
    </div>
    <p style="margin:18px 0 0;font-size:13px;color:#64748b;line-height:1.7;">
      You can also leave a short written comment after selecting your rating.
      Your feedback goes directly to {safe_restaurant}.
    </p>"""
    return build_email_shell(
        "How was your experience?",
        f"Your order from {safe_restaurant} is complete — let them know how it went.",
        content_html,
        accent="#f59e0b"
    )


def build_deployment_email(project_name, site_url):
    safe_name = escape(project_name or "Your Website")
    safe_url = escape(site_url or "")
    content_html = f"""
    <p style="margin:0 0 18px;font-size:15px;line-height:1.75;color:#334155;">
      Great news — <strong>{safe_name}</strong> has been successfully deployed and is now live on Dinebloc.
    </p>
    <div style="margin:28px 0;text-align:center;">
      <a href="{safe_url}"
         style="display:inline-block;padding:15px 32px;border-radius:14px;
                background:linear-gradient(135deg,#0b63ff,#1d4ed8);color:#ffffff;
                text-decoration:none;font-weight:700;font-size:16px;
                box-shadow:0 8px 22px rgba(11,99,255,0.28);">
        Visit Your Website
      </a>
    </div>
    <p style="margin:0 0 12px;font-size:14px;line-height:1.7;color:#334155;">
      Your site URL: <a href="{safe_url}" style="color:#0b63ff;font-weight:600;">{safe_url}</a>
    </p>
    <p style="margin:0;font-size:13px;line-height:1.7;color:#64748b;">
      You can manage your website, update content, and configure features from your Dinebloc dashboard at any time.
    </p>"""
    return build_email_shell(
        f"{safe_name} is live!",
        "Your website has been successfully deployed and is ready to receive visitors.",
        content_html,
        accent="#16a34a"
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
    host = request.host.split(":")[0]
    parts = host.split(".")

    # Supported formats (parts[0] is always the slug):
    #   grandpajoes.dinebloc.com        (3 parts)
    #   grandpajoes.dev.dinebloc.com    (4 parts, nginx routes port 8002)
    #   grandpajoes-dev.dinebloc.com    (backwards compat)
    if len(parts) < 3:
        return None

    sub = parts[0].strip().lower()

    # Backwards compatibility: grandpajoes-dev.dinebloc.com → grandpajoes
    if sub.endswith("-dev"):
        sub = sub[:-4]

    return sub


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


def ensure_upcoming_events_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS upcoming_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            event_datetime DATETIME,
            disable_online_ordering TINYINT(1) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_upcoming_events_project_id (project_id)
        )
    """)
    conn.commit()

    for col, col_def in [("start_datetime", "DATETIME"), ("end_datetime", "DATETIME")]:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'upcoming_events'
              AND COLUMN_NAME = %s
        """, (col,))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE upcoming_events ADD COLUMN {col} DATETIME")
            conn.commit()

    cursor.close()


def get_upcoming_events(project_id):
    conn = get_db_connection()
    ensure_upcoming_events_table(conn)
    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute("""
        SELECT id, title, description, event_datetime, disable_online_ordering, created_at
        FROM upcoming_events
        WHERE project_id = %s
        ORDER BY event_datetime ASC, id ASC
    """, (project_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


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


# ─── TABLE BOOKINGS SCHEMA ────────────────────────────────────────────────────

def ensure_table_booking_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS table_booking_config (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            slot_duration_minutes INT NOT NULL DEFAULT 60,
            advance_booking_days INT NOT NULL DEFAULT 60,
            min_party_size INT NOT NULL DEFAULT 1,
            max_party_size INT NOT NULL DEFAULT 12,
            high_chairs_enabled TINYINT(1) NOT NULL DEFAULT 1,
            max_high_chairs INT NOT NULL DEFAULT 4,
            table_numbering_enabled TINYINT(1) NOT NULL DEFAULT 0,
            booking_lead_minutes INT NOT NULL DEFAULT 30,
            notes_for_customers TEXT NULL,
            table_order_online_payment TINYINT(1) NOT NULL DEFAULT 0,
            UNIQUE KEY uq_project (project_id)
        )
    """)
    # Migrate: add column if table already existed without it
    try:
        cursor.execute("""
            ALTER TABLE table_booking_config
            ADD COLUMN table_order_online_payment TINYINT(1) NOT NULL DEFAULT 0
        """)
    except Exception:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS table_booking_hours (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            day_of_week TINYINT NOT NULL,
            open_time TIME NOT NULL DEFAULT '09:00:00',
            close_time TIME NOT NULL DEFAULT '22:00:00',
            is_closed TINYINT(1) NOT NULL DEFAULT 0,
            UNIQUE KEY uq_project_day (project_id, day_of_week)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restaurant_tables (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            capacity INT NOT NULL,
            table_number VARCHAR(20) NULL,
            sort_order INT NOT NULL DEFAULT 0,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_project (project_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS table_bookings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            table_id INT NOT NULL,
            booking_date DATE NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            party_size INT NOT NULL,
            customer_name VARCHAR(200) NOT NULL,
            customer_email VARCHAR(200) NOT NULL,
            customer_phone VARCHAR(50) NOT NULL,
            special_requests TEXT NULL,
            high_chairs_needed INT NOT NULL DEFAULT 0,
            status ENUM('confirmed','cancelled','completed','no_show') NOT NULL DEFAULT 'confirmed',
            booking_ref VARCHAR(12) NOT NULL,
            admin_notes TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cancelled_at TIMESTAMP NULL,
            cancelled_by ENUM('customer','admin') NULL,
            UNIQUE KEY uq_ref (booking_ref),
            INDEX idx_project_date (project_id, booking_date),
            INDEX idx_table_date (table_id, booking_date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS table_booking_blocked (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            blocked_date DATE NOT NULL,
            start_time TIME NULL,
            end_time TIME NULL,
            reason VARCHAR(255) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_project_date (project_id, blocked_date)
        )
    """)
    conn.commit()
    cursor.close()

    for table in ("restaurant_tables", "table_bookings", "table_booking_blocked",
                  "table_booking_config", "table_booking_hours"):
        ensure_location_id_column(conn, table)

    # table_booking_config/table_booking_hours were originally unique per
    # project only; widen to (project_id, location_id[, day_of_week]) so a
    # second location can have its own config/hours rows. Safe on both a
    # brand-new table (old key never existed) and an existing one (old key
    # gets dropped in favor of the new one) — idempotent either way.
    cursor = conn.cursor()
    for table, old_key, new_key, new_cols in (
        ("table_booking_config", "uq_project", "uq_project_location", "(project_id, location_id)"),
        ("table_booking_hours", "uq_project_day", "uq_project_location_day", "(project_id, location_id, day_of_week)"),
    ):
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s
        """, (table, new_key))
        if cursor.fetchone()[0]:
            continue

        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s
        """, (table, old_key))
        has_old_key = cursor.fetchone()[0] > 0

        if has_old_key:
            cursor.execute(f"ALTER TABLE {table} DROP INDEX {old_key}, ADD UNIQUE KEY {new_key} {new_cols}")
        else:
            cursor.execute(f"ALTER TABLE {table} ADD UNIQUE KEY {new_key} {new_cols}")
        conn.commit()
    cursor.close()


def ensure_locations_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            name VARCHAR(150) NOT NULL DEFAULT 'Main Location',
            address VARCHAR(255) NULL,
            city VARCHAR(100) NULL,
            postcode VARCHAR(20) NULL,
            country VARCHAR(100) NULL,
            phone VARCHAR(30) NULL,
            is_primary TINYINT(1) NOT NULL DEFAULT 0,
            sort_order INT NOT NULL DEFAULT 0,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_project (project_id)
        )
    """)
    conn.commit()
    cursor.close()


def ensure_location_id_column(conn, table_name):
    """Adds a nullable location_id column to `table_name` if missing, then
    backfills any rows still missing it to their project's primary location.
    Idempotent — safe to call on every request. `table_name` is always a
    hardcoded literal from this file, never user input."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='location_id'
    """, (table_name,))
    has_column = cursor.fetchone()[0] > 0

    if not has_column:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN location_id INT NULL")
        cursor.execute(f"ALTER TABLE {table_name} ADD INDEX idx_location_id (location_id)")
        conn.commit()

    ensure_locations_table(conn)
    cursor.execute(f"""
        UPDATE {table_name} t
        JOIN locations l ON l.project_id = t.project_id AND l.is_primary = 1
        SET t.location_id = l.id
        WHERE t.location_id IS NULL
    """)
    conn.commit()
    cursor.close()


def ensure_restaurant_tables_qr_column(conn):
    cursor = conn.cursor()
    try:
        cursor.execute(
            "ALTER TABLE restaurant_tables ADD COLUMN qr_code_path VARCHAR(255) NULL"
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cursor.close()


def _td_to_str(t):
    """Convert MySQL TIME (timedelta or time object) to HH:MM string."""
    from datetime import timedelta as _td, time as _t
    if isinstance(t, _td):
        s = int(t.total_seconds())
        return f"{s//3600:02d}:{(s%3600)//60:02d}"
    if isinstance(t, _t):
        return t.strftime('%H:%M')
    return str(t)[:5]


def _get_available_slots(project_id, date_str, party_size, conn, location_id=None):
    from datetime import datetime, date as _date, timedelta
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    dow = target_date.weekday()  # 0=Mon

    if location_id is None:
        location_id = resolve_active_location_id(project_id)

    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM table_booking_config WHERE project_id=%s AND location_id=%s LIMIT 1",
        (project_id, location_id)
    )
    cfg = cursor.fetchone() or {
        'slot_duration_minutes': 60,
        'booking_lead_minutes': 30,
    }

    cursor.execute(
        "SELECT * FROM table_booking_hours WHERE project_id=%s AND location_id=%s AND day_of_week=%s LIMIT 1",
        (project_id, location_id, dow)
    )
    hrs = cursor.fetchone()
    if not hrs or hrs['is_closed']:
        cursor.close()
        return []

    cursor.execute(
        "SELECT * FROM restaurant_tables WHERE project_id=%s AND location_id=%s AND is_active=1 ORDER BY capacity ASC",
        (project_id, location_id)
    )
    all_tables = cursor.fetchall()
    suitable = [t for t in all_tables if t['capacity'] >= party_size]
    if not suitable:
        cursor.close()
        return []

    tid_list = [t['id'] for t in suitable]
    ph = ','.join(['%s'] * len(tid_list))
    cursor.execute(
        f"SELECT table_id, start_time, end_time FROM table_bookings "
        f"WHERE table_id IN ({ph}) AND booking_date=%s AND status='confirmed'",
        tuple(tid_list) + (target_date,)
    )
    booked = cursor.fetchall()

    cursor.execute(
        "SELECT start_time, end_time FROM table_booking_blocked WHERE project_id=%s AND location_id=%s AND blocked_date=%s",
        (project_id, location_id, target_date)
    )
    blocked = cursor.fetchall()
    cursor.close()

    duration = timedelta(minutes=int(cfg['slot_duration_minutes']))
    from datetime import time as _t
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
            bs = _to_dt(b_start); be = _to_dt(b_end)
            return bs < e and be > s

        is_blocked = any(
            b['start_time'] is None or overlaps(b['start_time'], b['end_time'])
            for b in blocked
        )
        if not is_blocked:
            avail = [t for t in suitable if not any(
                b['table_id'] == t['id'] and overlaps(b['start_time'], b['end_time'])
                for b in booked
            )]
            if avail:
                slots.append({
                    'start': s_str, 'end': e_str,
                    'tables_available': len(avail),
                    'smallest_fit': min(t['capacity'] for t in avail)
                })
        cur += step
    return slots


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
        "payment_status": "ADD COLUMN payment_status VARCHAR(50) NOT NULL DEFAULT 'pending'",
        "is_delivery": "ADD COLUMN is_delivery TINYINT(1) NOT NULL DEFAULT 0",
        "delivery_address": "ADD COLUMN delivery_address TEXT NULL",
        "delivery_status": "ADD COLUMN delivery_status VARCHAR(30) NULL",
        "payment_intent_id": "ADD COLUMN payment_intent_id VARCHAR(255) NULL",
        "table_number": "ADD COLUMN table_number VARCHAR(50) NULL",
        "table_session_id": "ADD COLUMN table_session_id VARCHAR(36) NULL",
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


def ensure_order_sequences_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_sequences (
            project_id INT PRIMARY KEY,
            next_number INT UNSIGNED NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    cursor.close()


def ensure_service_override_columns(conn):
    cursor = conn.cursor()
    cols = {
        "ordering_temp_disabled_until": "ADD COLUMN ordering_temp_disabled_until DATETIME NULL",
        "delivery_temp_disabled_until":  "ADD COLUMN delivery_temp_disabled_until DATETIME NULL",
        "ordering_temp_enabled_until":   "ADD COLUMN ordering_temp_enabled_until DATETIME NULL",
        "delivery_temp_enabled_until":   "ADD COLUMN delivery_temp_enabled_until DATETIME NULL",
    }
    for col, sql in cols.items():
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='project_details' AND COLUMN_NAME=%s
        """, (col,))
        if not cursor.fetchone()[0]:
            cursor.execute(f"ALTER TABLE project_details {sql}")
    conn.commit()
    cursor.close()


def ensure_rejection_columns(conn):
    cursor = conn.cursor()
    cols = {
        "rejection_reason": "ADD COLUMN rejection_reason VARCHAR(1000) NULL",
        "rejected_at":      "ADD COLUMN rejected_at DATETIME NULL",
    }
    for col, sql in cols.items():
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='orders' AND COLUMN_NAME=%s
        """, (col,))
        if not cursor.fetchone()[0]:
            cursor.execute(f"ALTER TABLE orders {sql}")
    conn.commit()
    cursor.close()


def ensure_delivery_settings_columns(conn):
    cursor = conn.cursor()
    cols = {
        "delivery_pay_online":      "ADD COLUMN delivery_pay_online TINYINT(1) NOT NULL DEFAULT 1",
        "delivery_pay_on_delivery": "ADD COLUMN delivery_pay_on_delivery TINYINT(1) NOT NULL DEFAULT 1",
    }
    for col, sql in cols.items():
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='project_details' AND COLUMN_NAME=%s
        """, (col,))
        if not cursor.fetchone()[0]:
            cursor.execute(f"ALTER TABLE project_details {sql}")
    conn.commit()
    cursor.close()


def _table_has_column(conn, table_name, column_name):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
    """, (table_name, column_name))
    exists = cursor.fetchone()[0] > 0
    cursor.close()
    return exists


def _table_has_index(conn, table_name, index_name):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
    """, (table_name, index_name))
    exists = cursor.fetchone()[0] > 0
    cursor.close()
    return exists


def ensure_project_details_unique_project(conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT project_id, COUNT(*) AS row_count
        FROM project_details
        GROUP BY project_id
        HAVING row_count > 1
    """)
    duplicate_projects = cursor.fetchall()

    for duplicate in duplicate_projects:
        project_id = duplicate["project_id"]
        cursor.execute("""
            SELECT *
            FROM project_details
            WHERE project_id=%s
            ORDER BY id ASC
        """, (project_id,))
        rows = cursor.fetchall()
        if len(rows) < 2:
            continue

        keeper = rows[0]
        duplicate_ids = [row["id"] for row in rows[1:]]
        updates = {}

        for column_name, value in keeper.items():
            if column_name in {"id", "project_id"}:
                continue

            values = [row.get(column_name) for row in rows if row.get(column_name) not in (None, "")]
            if not values:
                continue

            if column_name in {"product_upload_attempts", "deal_upload_attempts", "hero_image_attempts"}:
                try:
                    updates[column_name] = min(int(value or 0) for value in values)
                except (TypeError, ValueError):
                    pass
            elif keeper.get(column_name) in (None, ""):
                updates[column_name] = values[-1]

        if updates:
            set_clause = ", ".join(f"{column_name}=%s" for column_name in updates)
            cursor.execute(
                f"UPDATE project_details SET {set_clause} WHERE id=%s",
                (*updates.values(), keeper["id"])
            )

        placeholders = ",".join(["%s"] * len(duplicate_ids))
        cursor.execute(f"DELETE FROM project_details WHERE id IN ({placeholders})", tuple(duplicate_ids))
        logging.warning(
            "[PROJECT_DETAILS] Collapsed %d duplicate row(s) for project_id=%s into id=%s",
            len(duplicate_ids),
            project_id,
            keeper["id"]
        )

    conn.commit()
    cursor.close()

    if not _table_has_index(conn, "project_details", "uq_project_details_project_id"):
        cursor = conn.cursor()
        cursor.execute("ALTER TABLE project_details ADD UNIQUE KEY uq_project_details_project_id (project_id)")
        conn.commit()
        cursor.close()


def _ensure_email_campaigns_table(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS email_campaigns (
            id INT AUTO_INCREMENT PRIMARY KEY,
            token VARCHAR(64) NOT NULL UNIQUE,
            business_name VARCHAR(255) NOT NULL,
            email_to VARCHAR(255) NOT NULL,
            email_html MEDIUMTEXT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            link_pressed TINYINT(1) NOT NULL DEFAULT 0,
            pressed_at TIMESTAMP NULL,
            INDEX (token)
        )
    """)
    c.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='email_campaigns' AND COLUMN_NAME='email_html'
    """)
    if not c.fetchone()[0]:
        c.execute("ALTER TABLE email_campaigns ADD COLUMN email_html MEDIUMTEXT NULL")
    conn.commit()
    c.close()




@app.route('/admin/email-history')
def email_history():
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        conn = get_db_connection()
        _ensure_email_campaigns_table(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, business_name, email_to, link_pressed, sent_at, pressed_at, email_html
            FROM email_campaigns ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "business_name": r["business_name"],
                "email_to": r["email_to"],
                "link_pressed": int(r["link_pressed"] or 0),
                "sent_at": (r["sent_at"] + timedelta(hours=10)).strftime("%d %b %Y %H:%M").lstrip("0") if r["sent_at"] else "—",
                "pressed_at": (r["pressed_at"] + timedelta(hours=10)).strftime("%d %b %Y %H:%M").lstrip("0") if r["pressed_at"] else None,
                "email_html": r["email_html"] or "",
            })
        return jsonify({"campaigns": result})
    except Exception as e:
        print(f"[email_history] ERROR: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/gen-email-token', methods=['POST'])
def gen_email_token():
    """Generate a tracking token and inject it into the HTML. Does NOT save to DB — that happens when the email is actually sent."""
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json() or {}
    raw_html = (data.get('email_html') or '').strip()
    token = secrets.token_urlsafe(32)
    track_url = f"https://dinebloc.com/sign-up?ref={token}"
    processed_html = raw_html.replace('REPLACE_WITH_TRACKING_URL', track_url) if raw_html else ''
    return jsonify({"success": True, "token": token, "track_url": track_url, "processed_html": processed_html})


@app.route('/admin/save-campaign', methods=['POST'])
def save_campaign():
    """Save a campaign to DB after the email has actually been sent."""
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json() or {}
    token        = (data.get('token') or '').strip()
    business_name = (data.get('business_name') or '').strip()
    email_to     = (data.get('email_to') or '').strip()
    email_html   = (data.get('email_html') or '').strip() or None
    if not token or not business_name or not email_to:
        return jsonify({"error": "Missing fields"}), 400
    try:
        conn = get_db_connection()
        _ensure_email_campaigns_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT IGNORE INTO email_campaigns (token, business_name, email_to, email_html) VALUES (%s, %s, %s, %s)",
            (token, business_name, email_to, email_html)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




def _record_hit(path):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS site_page_hits (
                id INT AUTO_INCREMENT PRIMARY KEY,
                path VARCHAR(255) NOT NULL,
                ip VARCHAR(64) NOT NULL,
                hit_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX (path),
                INDEX (hit_at)
            )
        """)
        ip = (request.headers.get("X-Forwarded-For", "") or request.remote_addr or "unknown")[:64]
        cursor.execute("INSERT INTO site_page_hits (path, ip) VALUES (%s, %s)", (path, ip))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[_record_hit] ERROR: {e}")


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


def ensure_menu_sections_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menu_sections (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            name VARCHAR(100) NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    cursor.close()


def ensure_categories_section_id_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'categories'
          AND COLUMN_NAME = 'section_id'
    """)
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
            ALTER TABLE categories
            ADD COLUMN section_id INT NULL
        """)
        conn.commit()
    cursor.close()


def ensure_deal_upload_attempts_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'deal_upload_attempts'
    """)
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN deal_upload_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0
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
    ensure_project_settings_css_theme_column(conn)
    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute("""
        SELECT primary_color, secondary_color, background_color, logo_path, css_theme
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


def db_flag(value, default=1):
    if value is None:
        return int(default)
    return 1 if is_truthy_db(value) else 0


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


def get_project_pay_in_store(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
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


def ensure_project_details_initial_menu_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'project_details'
          AND COLUMN_NAME = 'initial_menu_path'
    """)
    has_column = cursor.fetchone()[0] > 0
    if not has_column:
        cursor.execute("""
            ALTER TABLE project_details
            ADD COLUMN initial_menu_path VARCHAR(500) NULL
        """)
        conn.commit()
    cursor.close()


def ensure_wizard_drafts_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wizard_drafts (
            client_id INT PRIMARY KEY,
            draft_data LONGTEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()


def ensure_order_feedback_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_feedback (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            order_id INT NOT NULL,
            order_number VARCHAR(64),
            customer_name VARCHAR(255),
            customer_email VARCHAR(255),
            rating TINYINT,
            comment TEXT,
            token VARCHAR(64) UNIQUE,
            submitted_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_order_feedback_project (project_id),
            INDEX idx_order_feedback_token (token)
        )
    """)
    conn.commit()
    cursor.close()


def ensure_projects_is_deleted_column(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'projects'
          AND COLUMN_NAME = 'is_deleted'
    """)
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            ALTER TABLE projects
            ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0
        """)
        conn.commit()
    cursor.close()


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


def ensure_stripe_project_columns(conn):
    cursor = conn.cursor()
    cols = {
        "stripe_account_id":      "ADD COLUMN stripe_account_id VARCHAR(255) NULL",
        "stripe_enabled":         "ADD COLUMN stripe_enabled TINYINT(1) NOT NULL DEFAULT 0",
        "stripe_charges_enabled": "ADD COLUMN stripe_charges_enabled TINYINT(1) NOT NULL DEFAULT 0",
        "stripe_payouts_enabled": "ADD COLUMN stripe_payouts_enabled TINYINT(1) NOT NULL DEFAULT 0",
    }
    for col, sql in cols.items():
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'projects'
              AND COLUMN_NAME = %s
        """, (col,))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE projects {sql}")
    conn.commit()
    cursor.close()


def ensure_feature_requests_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feature_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT,
            client_email VARCHAR(255),
            feature_name VARCHAR(255) NOT NULL,
            description TEXT,
            page_context VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_feature_requests_created (created_at)
        )
    """)
    conn.commit()
    cursor.close()


def ensure_deleted_projects_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deleted_projects (
            id INT AUTO_INCREMENT PRIMARY KEY,
            slug VARCHAR(255) NOT NULL UNIQUE,
            project_name VARCHAR(255),
            client_id INT,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_deleted_projects_slug (slug)
        )
    """)
    conn.commit()
    cursor.close()


def slug_is_reserved(cursor, slug):
    """Return True if the slug exists in either projects or deleted_projects."""
    cursor.execute("SELECT id FROM projects WHERE slug=%s LIMIT 1", (slug,))
    if cursor.fetchone():
        return True
    try:
        cursor.execute("SELECT id FROM deleted_projects WHERE slug=%s LIMIT 1", (slug,))
        if cursor.fetchone():
            return True
    except Exception:
        pass
    return False


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
    return project


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
            wants_json = (
                request.accept_mimetypes.best == 'application/json'
                or request.path.startswith('/admin/')
                and request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            )
            if wants_json:
                return jsonify({"success": False, "error": "Session expired. Please refresh and log in again."}), 401
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

# Server-side source of truth for module pricing/dependencies — mirrors the
# data-price attributes in builder-wizard.html, which only ever validated
# these client-side.
MODULE_PRICES = {
    "online_ordering_system": 30,
    "catering_system": 30,
    "booking_reservation_system": 30,
    "staff_admin_system": 15,
    "delivery_system": 0,
    "pos_system": 0,
}
BASE_PLATFORM_COST = 65

# module_key -> module_key it requires to be enabled
MODULE_DEPENDENCIES = {
    "delivery_system": "online_ordering_system",
}


def compute_module_total_cost(selected_modules: dict) -> int:
    return BASE_PLATFORM_COST + sum(
        price for key, price in MODULE_PRICES.items() if selected_modules.get(key)
    )


def validate_module_dependencies(selected_modules: dict) -> str | None:
    for key, requires in MODULE_DEPENDENCIES.items():
        if selected_modules.get(key) and not selected_modules.get(requires):
            return f"{key} requires {requires} to also be enabled."
    return None


@app.before_request
def detect_project():
    host = request.host.split(":")[0]
    parts = host.split(".")

    # Supported formats (parts[0] is always the slug):
    #   grandpajoes.dinebloc.com        (3 parts)
    #   grandpajoes.dev.dinebloc.com    (4 parts, nginx routes port 8002)
    #   grandpajoes-dev.dinebloc.com    (backwards compat)
    if len(parts) < 3:
        return

    slug = parts[0].strip().lower()

    # Backwards compatibility: grandpajoes-dev.dinebloc.com → grandpajoes
    if slug.endswith("-dev"):
        slug = slug[:-4]

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
def load_locations():
    if hasattr(g, "project"):
        g.locations = get_project_locations(g.project["id"])
        g.multi_location = len(g.locations) > 1
    else:
        g.locations = []
        g.multi_location = False


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
        f"/admin/{slug}/hero-image/",
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

    if _is_bot(request.headers.get("User-Agent", "")):
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


_BOT_UA_FRAGMENTS = (
    "bot", "crawl", "spider", "slurp", "search", "fetch", "scan", "check",
    "monitor", "probe", "http", "python", "java", "ruby", "perl", "curl",
    "wget", "go-http", "axios", "node", "scrapy", "selenium", "headless",
    "phantom", "puppeteer", "playwright", "ahrefs", "semrush", "moz",
    "majestic", "sistrix", "dataprovider", "archive", "facebookexternalhit",
    "twitterbot", "linkedinbot", "whatsapp", "embedly", "preview",
)

def _is_bot(user_agent: str) -> bool:
    if not user_agent:
        return True
    ua = user_agent.lower()
    return any(fragment in ua for fragment in _BOT_UA_FRAGMENTS)




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
    _record_hit("/")
    return render_template("landing.html")  # your builder homepage



# -----------------------------
# AUTHENTICATED ROUTES
# (logic will come later)
# -----------------------------


def build_revenue_series(points, period):
    """Helper function to build revenue chart data for dashboard."""
    today = datetime.now().date()
    
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

    # All time
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


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    ensure_project_visits_table(conn)
    ensure_projects_is_deleted_column(conn)
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
        WHERE client_id=%s AND (is_deleted=0 OR is_deleted IS NULL)
        ORDER BY created_at DESC
        LIMIT 5
    """, (client_id,))
    recent_projects = cursor.fetchall()

    cursor.execute("""
        SELECT p.project_name, p.slug, p.created_at, p.is_deployed, p.is_deploying,
               s.primary_color, s.secondary_color, s.background_color
        FROM projects p
        LEFT JOIN project_settings s ON p.id = s.project_id
        WHERE p.client_id = %s AND (p.is_deleted=0 OR p.is_deleted IS NULL)
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

    # Get order data for revenue calculations
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

    # Calculate revenue metrics
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

    # Check for wizard draft
    wizard_draft = None
    try:
        conn2 = get_db_connection()
        ensure_wizard_drafts_table(conn2)
        cur2 = conn2.cursor(dictionary=True)
        cur2.execute(
            "SELECT draft_data, updated_at FROM wizard_drafts WHERE client_id=%s LIMIT 1",
            (client_id,)
        )
        draft_row = cur2.fetchone()
        cur2.close()
        conn2.close()
        if draft_row:
            import json as _json
            _d = _json.loads(draft_row["draft_data"])
            wizard_draft = {
                "name": _d.get("project_name", "Untitled"),
                "step": _d.get("currentStep", 0),
                "updated_at": draft_row["updated_at"].strftime("%d %b %Y, %H:%M") if draft_row["updated_at"] else ""
            }
    except Exception:
        logging.exception("Failed to load wizard draft for dashboard")

    return render_template(
        "dashboard.html",
        total_projects=total_projects,
        total_modules=total_modules,
        recent_projects=recent_projects,
        projects=projects,
        traffic_today=traffic_today,
        average_weekly_purchase=average_weekly_purchase,
        performance_chart=performance_chart,
        wizard_draft=wizard_draft
    )


def ensure_project_details_qr_asset_columns(conn):
    cursor = conn.cursor()
    for column_name, alter_sql in (
        ("qr_code_path", "ADD COLUMN qr_code_path VARCHAR(255) NULL"),
        ("qr_poster_pdf_path", "ADD COLUMN qr_poster_pdf_path VARCHAR(255) NULL"),
        ("qr_install_url", "ADD COLUMN qr_install_url VARCHAR(255) NULL"),
    ):
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'project_details'
              AND COLUMN_NAME = %s
        """, (column_name,))
        has_column = cursor.fetchone()[0] > 0

        if not has_column:
            cursor.execute(f"ALTER TABLE project_details {alter_sql}")
            conn.commit()

    cursor.close()


def ensure_ordering_hours_columns(conn):
    cursor = conn.cursor()
    for column_name, alter_sql in (
        ("online_ordering_hours",    "ADD COLUMN online_ordering_hours TEXT NULL"),
        ("online_ordering_enabled",  "ADD COLUMN online_ordering_enabled TINYINT(1) NOT NULL DEFAULT 1"),
        ("ordering_follows_op",      "ADD COLUMN ordering_follows_op TINYINT(1) NOT NULL DEFAULT 0"),
    ):
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'project_details' AND COLUMN_NAME = %s
        """, (column_name,))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE project_details {alter_sql}")
            conn.commit()
    cursor.close()


HOURS_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def parse_hours_form(form):
    """Build structured hours JSON from wizard/webconfig form fields."""
    hours = {}
    for day in HOURS_DAYS:
        is_open = form.get(f"hours_{day}_open") in ("1", "on", "true", "yes")
        hours[day] = {
            "open": is_open,
            "from": form.get(f"hours_{day}_from") or None if is_open else None,
            "to":   form.get(f"hours_{day}_to")   or None if is_open else None,
        }
    return hours


def hours_to_display(hours_json_str):
    """Parse stored hours JSON and return a list of (day_label, display_str) tuples."""
    if not hours_json_str:
        return []
    try:
        data = json.loads(hours_json_str)
    except Exception:
        return []
    day_labels = {
        "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
        "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday",
    }
    result = []
    for day in HOURS_DAYS:
        entry = data.get(day, {})
        label = day_labels.get(day, day.capitalize())
        if entry.get("open"):
            result.append((label, f"{entry.get('from','?')} – {entry.get('to','?')}"))
        else:
            result.append((label, "Closed"))
    return result



@app.route('/builder')
@login_required
def builder():
    return render_template('builder-wizard.html')


@app.route('/wizard/draft', methods=['GET'])
@login_required
def wizard_draft_get():
    conn = get_db_connection()
    try:
        ensure_wizard_drafts_table(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT draft_data, updated_at FROM wizard_drafts WHERE client_id=%s LIMIT 1",
            (session["client_id"],)
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            return jsonify({"success": True, "draft": row["draft_data"], "updated_at": str(row["updated_at"])})
        return jsonify({"success": True, "draft": None})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route('/wizard/draft', methods=['POST'])
@login_required
def wizard_draft_save():
    payload = request.get_json(silent=True) or {}
    draft_data = payload.get("draft")
    if not draft_data or not isinstance(draft_data, str):
        return jsonify({"success": False, "error": "Missing draft data"}), 400
    conn = get_db_connection()
    try:
        ensure_wizard_drafts_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO wizard_drafts (client_id, draft_data)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE draft_data=%s, updated_at=CURRENT_TIMESTAMP
        """, (session["client_id"], draft_data, draft_data))
        conn.commit()
        cursor.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route('/wizard/draft', methods=['DELETE'])
@login_required
def wizard_draft_delete():
    conn = get_db_connection()
    try:
        ensure_wizard_drafts_table(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wizard_drafts WHERE client_id=%s", (session["client_id"],))
        conn.commit()
        cursor.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route('/how-it-works')
def how_it_works():
    _record_hit("/how-it-works")
    return render_template('how-it-works.html')


@app.route('/about')
def about_page():
    _record_hit("/about")
    return render_template('about-dinebloc.html')


@app.route('/contact')
def contact_page():
    if hasattr(g, "project"):
        return contact()
    _record_hit("/contact")
    return render_template('contact-dinebloc.html')


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("15 per minute", methods=["POST"])
def login():
    error = None

    if 'client_id' in session:
        return redirect('/dashboard')

    if session.get('worker_id') and session.get('worker_project_slug'):
        return redirect(f"/worker/{session['worker_project_slug']}")

    if request.method == 'GET':
        _record_hit("/login")

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
                session.clear()  # prevent session fixation
                session.permanent = True
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
            session.clear()  # prevent session fixation
            session.permanent = True
            session['worker_id'] = worker['id']
            session['worker_project_slug'] = worker['slug']

            return redirect(f"/worker/{worker['slug']}")

        return render_login_page(error="Invalid credentials")

    return render_login_page(error=error)


@app.route('/forgot-password', methods=['POST'])
@limiter.limit("5 per minute")
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
            "UPDATE clients SET verification_token=%s, password_reset_sent_at=%s WHERE id=%s",
            (token, datetime.now(), client["id"])
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
@limiter.limit("10 per minute")
def reset_password(token):
    error = None
    success = False

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, password_reset_sent_at FROM clients WHERE verification_token=%s", (token,))
    client = cursor.fetchone()

    if not client:
        cursor.close()
        conn.close()
        return "Invalid or expired reset link.", 404

    sent_at = client.get("password_reset_sent_at")
    if sent_at:
        if isinstance(sent_at, str):
            try:
                sent_at = datetime.fromisoformat(sent_at)
            except ValueError:
                sent_at = None
        if sent_at and datetime.now() - sent_at > timedelta(hours=1):
            cursor.execute(
                "UPDATE clients SET verification_token=NULL, password_reset_sent_at=NULL WHERE id=%s",
                (client["id"],)
            )
            conn.commit()
            cursor.close()
            conn.close()
            return "This reset link has expired. Please request a new one.", 400

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            error = "Passwords do not match."
        elif not is_strong_password(password):
            error = "Password must be at least 8 characters and include letters, numbers, and symbols."
        else:
            cursor.execute(
                "UPDATE clients SET password_hash=%s, verification_token=NULL, password_reset_sent_at=NULL WHERE id=%s",
                (generate_password_hash(password), client["id"])
            )
            conn.commit()
            success = True

    cursor.close()
    conn.close()

    return render_template("reset-password.html", error=error, success=success)



@app.route('/sign-up', methods=['GET','POST'])
@limiter.limit("10 per minute", methods=["POST"])
def sign_up():
    error = None

    if 'client_id' in session:
        return redirect('/dashboard')

    if request.method == 'GET':
        _record_hit("/sign-up")
        ref = request.args.get('ref', '').strip()
        if ref:
            try:
                conn = get_db_connection()
                _ensure_email_campaigns_table(conn)
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE email_campaigns SET link_pressed=1, pressed_at=NOW() WHERE token=%s AND link_pressed=0",
                    (ref,)
                )
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"[sign_up ref] ERROR: {e}")

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
        trial_end = datetime.now() + TRIAL_DURATION
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
        ensure_projects_is_deleted_column(db)
        ensure_project_details_initial_menu_column(db)
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
        operating_hours = json.dumps(parse_hours_form(request.form))
        total_cost = int(request.form.get("total_cost") or 65)

        background_color = request.form.get("bg_color")
        primary_color = request.form.get("primary_color")
        secondary_color = request.form.get("secondary_color")

        modules = request.form.getlist("modules")

        slug = re.sub(r'[^a-z0-9]+', '-', project_name.lower()).strip('-')

        # Block slug if it exists in projects OR the deleted archive
        ensure_deleted_projects_table(db)
        _chk = db.cursor()
        if slug_is_reserved(_chk, slug):
            _chk.close()
            return jsonify({"error": "name_taken"}), 409
        _chk.close()

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

        menu_file = request.files.get("menu_file")
        menu_bytes = None
        menu_ext = None
        if menu_file and menu_file.filename != "":
            raw_ext = os.path.splitext(secure_filename(menu_file.filename))[1].lower()
            if raw_ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".docx", ".txt", ".csv"}:
                menu_ext = raw_ext
                menu_bytes = menu_file.read()
                print(f"[WIZARD] Menu file received: '{menu_file.filename}', ext='{menu_ext}', size={len(menu_bytes)} bytes")
                logging.info("[WIZARD] Menu file received: '%s', ext='%s', size=%d bytes", menu_file.filename, menu_ext, len(menu_bytes))
            else:
                print(f"[WIZARD] Menu file rejected (unsupported ext): '{menu_file.filename}' -> ext='{raw_ext}'")
        else:
            print("[WIZARD] No menu file provided in wizard submission")

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
                print(f"[WIZARD] project_details inserted: project_id={project_id}, slug='{slug}', description='{(description or '')[:100]}'")
                logging.info("[WIZARD] project_details saved for project_id=%s slug='%s'", project_id, slug)

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

        # Save initial menu file to disk if provided
        if menu_bytes and menu_ext:
            try:
                project_path = os.path.join(PROJECTS_DIR, slug)
                os.makedirs(project_path, exist_ok=True)
                menu_filename = f"initial_menu{menu_ext}"
                menu_file_path = os.path.join(project_path, menu_filename)
                with open(menu_file_path, 'wb') as f:
                    f.write(menu_bytes)
                print(f"[WIZARD] Menu file saved to disk: '{menu_file_path}' ({len(menu_bytes)} bytes)")
                logging.info("[WIZARD] Menu file saved: '%s' for project_id=%s slug='%s'", menu_file_path, project_id, slug)
                conn3 = get_db_connection()
                cur3 = conn3.cursor()
                try:
                    cur3.execute(
                        "UPDATE project_details SET initial_menu_path=%s WHERE project_id=%s",
                        (menu_file_path, project_id)
                    )
                    conn3.commit()
                    print(f"[WIZARD] initial_menu_path saved to DB: '{menu_file_path}' for project_id={project_id}")
                    logging.info("[WIZARD] initial_menu_path saved to DB for project_id=%s", project_id)
                finally:
                    cur3.close()
                    conn3.close()
            except Exception:
                logging.exception("[WIZARD] Failed to save initial menu file for project_id=%s slug='%s'", project_id, slug)
                print(f"[WIZARD] ERROR: Failed to save menu file for project_id={project_id} slug='{slug}'")

        print(f"[WIZARD] Project '{slug}' (id={project_id}) created successfully — menu={'yes' if menu_bytes else 'no'}, logo={'yes' if logo_bytes else 'no'}")
        logging.info("[WIZARD] Project created: slug='%s' id=%s", slug, project_id)
        return jsonify({
            "success": True,
            "slug": slug,
            "project_id": project_id,
            "url": f"https://{slug}.dinebloc.com/"
        })

    except Exception as e:
        print(f"[WIZARD] ERROR creating project: {e}")
        logging.exception("[WIZARD] Exception in create_project")
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
    ensure_deleted_projects_table(db)

    reserved = slug_is_reserved(cursor, slug)

    cursor.close()
    db.close()

    return jsonify({"available": not reserved})





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
        payload["bundle_selections"] = item.get("bundle_selections") or []

    return payload


def build_validated_order_items(project_id, items, cursor, location_id=None):
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
                "SELECT id, title, price, description, products, type FROM deals "
                "WHERE id=%s AND project_id=%s AND (location_id=%s OR location_id IS NULL)",
                (item_id, project_id, location_id)
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
                "bundle_items": parse_deal_bundle_metadata(deal.get("description")).get("bundle_items", []),
                "bundle_selections": item.get("bundle_selections") or []
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
            WHERE id=%s AND project_id=%s AND (location_id=%s OR location_id IS NULL)
            """,
            (item_id, project_id, location_id)
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


def create_order_record(project_id, data, cursor, location_id=None):
    validated_items, total = build_validated_order_items(
        project_id, data.get("items") or [], cursor, location_id=location_id
    )

    if not validated_items:
        raise ValueError("At least one valid order item is required.")

    cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_num FROM orders WHERE project_id=%s", (project_id,))
    row = cursor.fetchone()
    order_number = str(row["next_num"] if isinstance(row, dict) else row[0])

    customer_name = sanitize_order_text(data.get("name"))
    customer_surname = sanitize_order_text(data.get("surname"))
    customer_phone = sanitize_order_text(data.get("phone"))
    customer_email = sanitize_order_text(data.get("email"))
    customer_note = sanitize_order_text(data.get("note"))

    is_delivery = 1 if data.get("is_delivery") else 0
    delivery_address = sanitize_order_text(data.get("delivery_address")) if is_delivery else None
    delivery_status = "preparing" if is_delivery else None

    raw_payment = sanitize_order_text(data.get("payment_method")) or ""
    allowed_methods = {"instore", "online", "on_delivery", "cash", "card", "in-store", "Online Confirmed", "stripe"}
    payment_method = raw_payment if raw_payment in allowed_methods else "instore"

    table_number   = sanitize_order_text(data.get("table_number")) or None
    table_session_id = sanitize_order_text(data.get("table_session_id")) or None

    cursor.execute("""
        INSERT INTO orders
        (project_id, location_id, order_number, items, total, payment_method, payment_status, status,
         name, surname, phone, email, note, is_delivery, delivery_address, delivery_status,
         table_number, table_session_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        project_id,
        location_id,
        order_number,
        json.dumps(validated_items),
        total,
        payment_method,
        "pending",
        "received",
        customer_name,
        customer_surname,
        customer_phone,
        customer_email,
        customer_note,
        is_delivery,
        delivery_address,
        delivery_status,
        table_number,
        table_session_id,
    ))

    return {
        "order_number": order_number,
        "validated_items": validated_items,
        "total": total,
        "name": customer_name,
        "surname": customer_surname,
        "phone": customer_phone,
        "email": customer_email,
        "note": customer_note,
        "is_delivery": is_delivery,
        "delivery_address": delivery_address,
        "table_number": table_number,
        "table_session_id": table_session_id,
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
    table_number = (order_payload.get("table_number") or "").strip()
    table_badge = ""
    table_info_block = ""
    if table_number:
        safe_table = escape(table_number)
        table_badge = f'&nbsp;<span style="display:inline-block;background:#fef9c3;color:#92400e;border:1px solid #fde047;border-radius:6px;padding:2px 10px;font-size:13px;font-weight:700;vertical-align:middle;">TABLE ORDER · {safe_table}</span>'
        table_info_block = f"""
        <div style="margin-bottom:14px;padding:14px 18px;border-radius:14px;background:#fefce8;border:1.5px solid #fde047;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#92400e;">Dine-In Table Order</div>
          <div style="margin-top:6px;font-size:18px;font-weight:800;color:#78350f;">Table {safe_table}</div>
          <div style="margin-top:2px;font-size:13px;color:#92400e;">Customer is dining at this table — deliver to table.</div>
        </div>
        """
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
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.82;">New {'table ' if table_number else ''}order received{table_badge}</div>
          <h1 style="margin:10px 0 6px;font-size:30px;line-height:1.1;">{safe_project_name}</h1>
          <p style="margin:0;font-size:15px;line-height:1.6;opacity:0.92;">Order #{order_payload['order_number']} has been placed and is waiting for restaurant confirmation.</p>
        </div>
        <div style="padding:28px 30px;">
          {table_info_block}
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
          {f'''<div style="margin-top:14px;padding:16px 18px;border-radius:16px;background:#f0fdf4;border:1px solid #86efac;">
            <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#166534;">Delivery Order</div>
            <div style="margin-top:8px;font-size:15px;font-weight:700;color:#15803d;">&#x1F4CD; {escape(order_payload.get("delivery_address") or "Address not provided")}</div>
          </div>''' if order_payload.get("is_delivery") else ''}
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
    cust_table_number = (order_payload.get("table_number") or "").strip()
    note_block = ""
    if order_payload.get("note"):
        note_block = f"""
        <div style="margin-top:18px;padding:16px 18px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">Note on your order</div>
          <div style="margin-top:8px;font-size:14px;line-height:1.6;color:#0f172a;">{escape(order_payload['note'])}</div>
        </div>
        """

    cust_payment_text = "upon delivery" if order_payload.get("is_delivery") else ("at the table" if cust_table_number else "in-store or upon pickup")
    cust_delivery_block = ""
    if order_payload.get("is_delivery"):
        safe_addr = escape(order_payload.get("delivery_address") or "")
        cust_delivery_block = (
            '<div style="margin-top:14px;padding:20px;border-radius:18px;background:#f0fdf4;border:1px solid #86efac;">'
            '<div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#166534;">Delivery Address</div>'
            f'<div style="margin-top:8px;font-size:16px;font-weight:700;color:#15803d;">&#x1F4CD; {safe_addr}</div>'
            '<p style="margin:8px 0 0;font-size:14px;color:#166534;">A driver will be assigned to deliver your order to this address.</p>'
            '</div>'
        )
    elif cust_table_number:
        cust_delivery_block = (
            f'<div style="margin-top:14px;padding:20px;border-radius:18px;background:#fefce8;border:1.5px solid #fde047;">'
            f'<div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#92400e;">Dine-In Table Order</div>'
            f'<div style="margin-top:8px;font-size:20px;font-weight:900;color:#78350f;">Table {escape(cust_table_number)}</div>'
            f'<p style="margin:8px 0 0;font-size:14px;color:#92400e;">Your order will be brought to your table. Enjoy!</p>'
            f'</div>'
        )

    return f"""
    <div style="margin:0;padding:32px 18px;background:linear-gradient(180deg,#eff6ff 0%,#f8fafc 100%);font-family:Inter,Arial,sans-serif;color:#0f172a;">
      <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:24px;overflow:hidden;box-shadow:0 24px 60px rgba(15,23,42,0.12);border:1px solid #dbeafe;">
        <div style="padding:28px 30px;background:linear-gradient(135deg,#0b63ff 0%,#1d4ed8 55%,#0f172a 100%);color:#ffffff;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.82;">Order confirmation</div>
          <h1 style="margin:10px 0 8px;font-size:30px;line-height:1.1;">{safe_project_name}</h1>
          <p style="margin:0;font-size:15px;line-height:1.6;opacity:0.92;">Your order has been received{f" — Table {escape(cust_table_number)}" if cust_table_number else ""}.</p>
        </div>
        <div style="padding:28px 30px;">
          <div style="padding:18px;border-radius:18px;background:#eff6ff;border:1px solid #bfdbfe;text-align:center;">
            <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#1d4ed8;">Order number</div>
            <div style="margin-top:8px;font-size:36px;font-weight:900;color:#0f172a;">#{escape(order_payload['order_number'])}</div>
          </div>
          <div style="margin-top:18px;padding:20px;border-radius:18px;background:#fff7ed;border:1px solid #fed7aa;">
            <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#7c2d12;">{"Your order will be brought to your table shortly." if cust_table_number else "The restaurant will call you shortly to confirm your order."}</p>
            <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#7c2d12;">Payment will be made {cust_payment_text}.</p>
            {"" if cust_table_number else '<p style="margin:0;font-size:15px;line-height:1.7;color:#7c2d12;">Please keep your phone available.</p>'}
          </div>
          {cust_delivery_block}
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
        return jsonify({"success": False, "error": "Project not found"}), 404

    if getattr(g, "client", None) and not getattr(g, "trial_active", False):
        logging.info("Trial expired for client %s", g.client["id"])

    data = request.get_json(silent=True) or {}
    if not data:
        raw = request.form or {}
        data = dict(raw)

    project_id = project["id"]

    conn = get_db_connection()
    ensure_order_columns(conn)
    ensure_location_id_column(conn, "orders")
    ensure_location_id_column(conn, "products")
    ensure_location_id_column(conn, "deals")
    location_id = resolve_active_location_id(project_id, data.get("location_id"))
    cursor = conn.cursor(dictionary=True)

    # Resolve table session: if this is a table order, find an existing active session
    # (orders placed at the same table within the last 4 hours) or create a new one.
    raw_table_number = (data.get("table_number") or "").strip()
    if raw_table_number:
        cursor.execute("""
            SELECT table_session_id FROM orders
            WHERE project_id=%s AND table_number=%s
              AND table_session_id IS NOT NULL
              AND created_at >= NOW() - INTERVAL 4 HOUR
            ORDER BY created_at DESC LIMIT 1
        """, (project_id, raw_table_number))
        session_row = cursor.fetchone()
        if session_row and session_row.get("table_session_id"):
            data["table_session_id"] = session_row["table_session_id"]
        else:
            import uuid as _uuid
            data["table_session_id"] = str(_uuid.uuid4())

    try:
        order_payload = create_order_record(project_id, data, cursor, location_id=location_id)
    except ValueError as exc:
        cursor.close()
        conn.close()
        return jsonify(success=False, error=str(exc)), 400

    conn.commit()
    cursor.close()
    conn.close()
    send_order_notification(project, order_payload)
    send_customer_order_confirmation(project, order_payload)

    return jsonify({
        "success": True,
        "order_number": order_payload["order_number"],
        "payment_method": "instore",
        "payment_status": "pending",
        "table_number": order_payload.get("table_number"),
        "table_session_id": order_payload.get("table_session_id"),
    })


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
        # Security: password-reset token expiry timestamp
        "password_reset_sent_at": "ADD COLUMN password_reset_sent_at DATETIME NULL",
        # Module-change billing anchor (see project_module_changes)
        "next_billing_date": "ADD COLUMN next_billing_date DATE NULL",
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




STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook_handler():
    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logging.error("[STRIPE_WEBHOOK] STRIPE_WEBHOOK_SECRET not configured")
        return "", 400

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        logging.warning("[STRIPE_WEBHOOK] Invalid signature")
        return "", 400
    except Exception as exc:
        logging.error("[STRIPE_WEBHOOK] construct_event failed: %s", exc)
        return "", 400

    logging.info("[STRIPE_WEBHOOK] Received: %s", event["type"])

    if event["type"] == "payment_intent.succeeded":
        intent            = event["data"]["object"]
        payment_intent_id = intent.get("id", "")
        metadata          = intent.get("metadata") or {}
        order_number      = metadata.get("order_number", "")

        if not order_number:
            logging.warning("[STRIPE_WEBHOOK] No order_number in metadata for intent=%s", payment_intent_id)
            return "", 200

        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, payment_status FROM orders WHERE order_number = %s LIMIT 1",
            (order_number,)
        )
        order = cursor.fetchone()

        if not order:
            logging.warning("[STRIPE_WEBHOOK] Order %s not found", order_number)
            cursor.close()
            conn.close()
            return "", 200

        if order["payment_status"] == "paid":
            logging.info("[STRIPE_WEBHOOK] Order %s already paid — skipping", order_number)
            cursor.close()
            conn.close()
            return "", 200

        cursor.execute(
            "UPDATE orders SET payment_status='paid', payment_intent_id=%s WHERE order_number=%s",
            (payment_intent_id, order_number)
        )
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("[STRIPE_WEBHOOK] Order %s marked paid, intent=%s", order_number, payment_intent_id)

    return "", 200





def ensure_project_module_changes_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_module_changes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            project_id INT NOT NULL,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            online_ordering_system TINYINT(1) NOT NULL DEFAULT 0,
            catering_system TINYINT(1) NOT NULL DEFAULT 0,
            booking_reservation_system TINYINT(1) NOT NULL DEFAULT 0,
            staff_admin_system TINYINT(1) NOT NULL DEFAULT 0,
            delivery_system TINYINT(1) NOT NULL DEFAULT 0,
            POS_system TINYINT(1) NOT NULL DEFAULT 0,
            new_total_cost INT NOT NULL,
            effective_date DATE NOT NULL,
            status ENUM('pending','applied','cancelled') NOT NULL DEFAULT 'pending',
            applied_at DATETIME NULL,
            INDEX idx_project_status (project_id, status)
        )
    """)
    conn.commit()
    cursor.close()


def _next_billing_anniversary(anchor_date, today=None):
    """The next date matching anchor_date's day-of-month, today or later."""
    import calendar
    from datetime import date as _date
    today = today or _date.today()

    def _clamped(y, m, d):
        return min(d, calendar.monthrange(y, m)[1])

    year, month = today.year, today.month
    candidate = _date(year, month, _clamped(year, month, anchor_date.day))
    if candidate < today:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        candidate = _date(year, month, _clamped(year, month, anchor_date.day))
    return candidate


def _apply_due_module_changes(project_id, conn):
    """Lazily applies any module-change request whose effective_date has
    arrived. Runs on every get_project_modules() call — same idempotent,
    check-on-read pattern as the ensure_* migrations already used throughout
    this file. No cron exists in this codebase, so this is how "takes effect
    on your next billing date" actually happens."""
    ensure_project_module_changes_table(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM project_module_changes
        WHERE project_id=%s AND status='pending' AND effective_date <= CURDATE()
        ORDER BY requested_at DESC LIMIT 1
    """, (project_id,))
    due = cursor.fetchone()
    if not due:
        cursor.close()
        return

    cursor.execute("""
        UPDATE project_modules SET
            online_ordering_system=%s, catering_system=%s, booking_reservation_system=%s,
            staff_admin_system=%s, delivery_system=%s, POS_system=%s
        WHERE project_id=%s
    """, (
        due["online_ordering_system"], due["catering_system"], due["booking_reservation_system"],
        due["staff_admin_system"], due["delivery_system"], due["POS_system"], project_id
    ))
    cursor.execute(
        "UPDATE project_details SET total_cost=%s WHERE project_id=%s",
        (due["new_total_cost"], project_id)
    )
    cursor.execute(
        "UPDATE project_module_changes SET status='applied', applied_at=NOW() WHERE id=%s",
        (due["id"],)
    )
    # TODO(billing): sync to a real Stripe subscription here once one exists.
    conn.commit()

    try:
        cursor.execute("""
            SELECT p.project_name, c.email FROM projects p
            JOIN clients c ON c.id = p.client_id
            WHERE p.id=%s LIMIT 1
        """, (project_id,))
        row = cursor.fetchone()
        if row and row.get("email"):
            send_email(
                to=row["email"],
                subject=f"Your module changes are now live — {row.get('project_name') or 'Dinebloc'}",
                html_body=(
                    f"<p>The module changes you requested have taken effect. "
                    f"Your new monthly total is <strong>${due['new_total_cost']}</strong>.</p>"
                ),
                sender=DEFAULT_INFO_EMAIL
            )
    except Exception:
        logging.exception("Failed to send module-change applied email for project %s", project_id)

    cursor.close()


def get_project_modules(project_id):

    conn = get_db_connection()
    _apply_due_module_changes(project_id, conn)
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


def get_project_locations(project_id):
    """All active locations for a project, primary first. Every project always
    has >=1 location — if none exist yet (pre-multi-location projects), a
    primary one is seeded here from project_details, once, lazily."""
    conn = get_db_connection()
    ensure_locations_table(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM locations WHERE project_id=%s AND is_active=1 "
        "ORDER BY is_primary DESC, sort_order ASC, id ASC",
        (project_id,)
    )
    locs = cursor.fetchall()

    if not locs:
        cursor.execute(
            "SELECT address, city, postcode, country, phone FROM project_details "
            "WHERE project_id=%s LIMIT 1",
            (project_id,)
        )
        d = cursor.fetchone() or {}
        cursor.execute("""
            INSERT INTO locations (project_id, name, address, city, postcode, country, phone, is_primary)
            VALUES (%s, 'Main Location', %s, %s, %s, %s, %s, 1)
        """, (
            project_id, d.get('address'), d.get('city'),
            d.get('postcode'), d.get('country'), d.get('phone')
        ))
        conn.commit()
        cursor.execute(
            "SELECT * FROM locations WHERE project_id=%s AND is_active=1 "
            "ORDER BY is_primary DESC, sort_order ASC, id ASC",
            (project_id,)
        )
        locs = cursor.fetchall()

    cursor.close()
    conn.close()
    return locs


def resolve_active_location_id(project_id, requested_location_id=None):
    """Which location a request/order should be scoped to. Single-location
    projects always resolve to that one location regardless of what (if
    anything) was requested — so nothing here can change behavior for the
    common case. Multi-location projects honor a valid requested id, else
    fall back to the customer's remembered choice (dinebloc_loc cookie),
    else the primary location — never fails the request."""
    locs = get_project_locations(project_id)
    if not locs:
        return None
    if len(locs) == 1:
        return locs[0]["id"]

    if requested_location_id is None:
        try:
            requested_location_id = request.cookies.get("dinebloc_loc")
        except RuntimeError:
            requested_location_id = None

    if requested_location_id is not None:
        try:
            requested_location_id = int(requested_location_id)
        except (TypeError, ValueError):
            requested_location_id = None

    if requested_location_id and any(l["id"] == requested_location_id for l in locs):
        return requested_location_id

    primary = next((l for l in locs if l["is_primary"]), None)
    return primary["id"] if primary else locs[0]["id"]





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
    if not get_project_pay_in_store(g.project["id"]):
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

    modules      = g.modules
    session_id   = request.args.get("session_id", "").strip()
    order_number = request.args.get("order_number", "").strip() or None
    payment_method_param = request.args.get("payment_method", "").strip()
    payment_verified = False
    used_stripe_checkout = bool(session_id) or payment_method_param == "stripe"
    logging.info(f"[PAYMENT_SUCCESS] START: session_id={session_id}, order_number={order_number}, project_slug={g.project.get('slug')}")
    logging.info(f"[PAYMENT_SUCCESS] Session ID present: {bool(session_id)}")

    if session_id:
        logging.info(f"[PAYMENT_SUCCESS] Querying database for existing order with session_id={session_id}")
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check for already-confirmed order (webhook or prior page load)
        cursor.execute(
            "SELECT order_number, payment_status FROM orders WHERE order_number = "
            "(SELECT order_number FROM orders WHERE payment_intent_id = %s LIMIT 1) LIMIT 1",
            (session_id,)
        )
        existing = cursor.fetchone()
        logging.info(f"[PAYMENT_SUCCESS] Database query result: existing_order={existing}")

        if existing and existing["payment_status"] == "paid":
            order_number     = existing["order_number"]
            payment_verified = True
            logging.info(f"[PAYMENT_SUCCESS] Found paid order in database: order_number={order_number}")
        else:
            logging.info(f"[PAYMENT_SUCCESS] No paid order found in database, attempting Stripe verification")
            try:
                logging.info(f"[PAYMENT_SUCCESS] Retrieving Stripe session: session_id={session_id}")
                cs = stripe.checkout.Session.retrieve(session_id)
                logging.info(f"[PAYMENT_SUCCESS] Stripe session retrieved: payment_status={cs.payment_status}")
                if cs.payment_status == "paid":
                    on = (cs.metadata or {}).get("order_number", "")
                    pi = cs.payment_intent or ""
                    logging.info(f"[PAYMENT_SUCCESS] Extracted from Stripe: order_number={on}, payment_intent={pi}")
                    if on:
                        logging.info(f"[PAYMENT_SUCCESS] Updating order {on} in database with payment_intent={pi}")
                        cursor.execute(
                            "UPDATE orders SET payment_status='paid', payment_intent_id=%s WHERE order_number=%s",
                            (pi, on)
                        )
                        conn.commit()
                        order_number     = on
                        payment_verified = True
                        logging.info(f"[PAYMENT_SUCCESS] Order {on} updated successfully - payment_verified=True")
                        logging.info("[STRIPE] /payment-success confirmed order %s, session %s", on, session_id)
                    else:
                        logging.info(f"[PAYMENT_SUCCESS] ERROR: No order_number in Stripe metadata")
            except Exception as exc:
                logging.error(f"[PAYMENT_SUCCESS] ERROR: Stripe session verification failed: {exc}")
                logging.error("[STRIPE] /payment-success session verify failed: %s", exc)

        cursor.close()
        conn.close()

    logging.info(f"[PAYMENT_SUCCESS] COMPLETE - Rendering page: order_number={order_number}, payment_verified={payment_verified}")
    ctx = {
        **build_page_context(modules),
        **build_global_context(modules),
        "order_number":     order_number,
        "payment_verified": payment_verified,
        "used_stripe_checkout": used_stripe_checkout,
        "payment_method":   payment_method_param,
    }
    return render_template('payment_success.html', **ctx)



@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    if not hasattr(g, "project"):
        return jsonify({"success": False, "error": "Project not found"}), 404

    if getattr(g, "client", None) and not getattr(g, "trial_active", False):
        logging.info("Trial expired for client %s", g.client["id"])

    data = request.get_json(silent=True) or request.form or {}
    project_slug = g.project.get("slug")
    logging.info(f"[CHECKOUT] START: project_slug={project_slug}, PAYMENTS_ENABLED={PAYMENTS_ENABLED}")
    logging.info(f"[CHECKOUT] Request data: {data}")

    # LEGACY: Stripe payment system (disabled for trial phase)
    logging.info(f"[CHECKOUT] PAYMENTS_ENABLED check: {PAYMENTS_ENABLED}")
    if PAYMENTS_ENABLED:
        logging.info("[CHECKOUT] Entering STRIPE payment flow (PAYMENTS_ENABLED=True)")
        # LEGACY: Stripe checkout flow (disabled for trial phase)
        if not stripe.api_key:
            logging.error("[CHECKOUT] ERROR: stripe.api_key is not configured")
            return jsonify({
                "error": "Stripe is not configured on this server. Set STRIPE_SECRET_KEY and restart the app."
            }), 503

        success = f"https://{project_slug}.dinebloc.com/payment-success"
        cancel = f"https://{project_slug}.dinebloc.com/menu"
        logging.info(f"[CHECKOUT] Creating Stripe session - success_url: {success}, cancel_url: {cancel}")
        logging.info(f"[CHECKOUT] Order total: {data.get('total')}")

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
        logging.info(f"[CHECKOUT] Stripe session created successfully: session_id={session.id}")
        return jsonify({'id': session.id})

    logging.info("[CHECKOUT] PAYMENTS_ENABLED=False, entering in-store payment flow")
    conn = get_db_connection()
    ensure_order_columns(conn)
    ensure_location_id_column(conn, "orders")
    ensure_location_id_column(conn, "products")
    ensure_location_id_column(conn, "deals")
    location_id = resolve_active_location_id(g.project["id"], (data or {}).get("location_id"))
    cursor = conn.cursor(dictionary=True)

    try:
        logging.info(f"[CHECKOUT] Creating order record for project_id={g.project['id']}")
        order_payload = create_order_record(g.project["id"], data or {}, cursor, location_id=location_id)
        logging.info(f"[CHECKOUT] Order record created: order_number={order_payload.get('order_number')}")
    except ValueError as exc:
        logging.error(f"[CHECKOUT] ERROR creating order: {exc}")
        cursor.close()
        conn.close()
        return jsonify(success=False, error=str(exc)), 400

    conn.commit()
    logging.info(f"[CHECKOUT] Database committed for order_number={order_payload.get('order_number')}")
    cursor.close()
    conn.close()

    logging.info(f"[CHECKOUT] Sending notifications for order_number={order_payload.get('order_number')}")
    send_order_notification(g.project, order_payload)
    send_customer_order_confirmation(g.project, order_payload)

    redirect_url = url_for("payment_success", order_number=order_payload["order_number"], payment_method=order_payload.get("payment_method", "instore"))
    logging.info(f"[CHECKOUT] COMPLETE - Returning response with redirect_url={redirect_url}")
    return jsonify({
        "success": True,
        "order_number": order_payload["order_number"],
        "payment_method": order_payload.get("payment_method", "instore"),
        "payment_status": "pending",
        "redirect_url": redirect_url
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
@login_required
def get_orders(slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

    conn = get_db_connection()
    ensure_order_columns(conn)
    ensure_rejection_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM orders WHERE project_id = %s ORDER BY created_at DESC",
        (project["id"],)
    )
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    for order in orders:
        for key in ("created_at", "in_progress_time", "completed_time", "rejected_at", "updated_at"):
            if key in order and hasattr(order[key], "isoformat"):
                order[key] = order[key].isoformat()
    return jsonify(orders)


@app.route('/admin/<slug>/order_catalog')
@login_required
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
VALID_STATUSES = ['received', 'in progress', 'completed', 'rejected']

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
@app.route('/admin/<slug>/update_order_status/<int:order_id>', methods=['POST'])
@login_required
def update_order_status(order_id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.json or {}
    status = data.get('status')

    if status not in ['received', 'in progress', 'completed']:
        return jsonify(success=False, error="Invalid status"), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if status == 'received':
        cursor.execute("""
            UPDATE orders
            SET status=%s
            WHERE id=%s AND project_id=%s
        """, (status, order_id, project["id"]))
    elif status == 'in progress':
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

        # Fetch order details to send feedback email
        try:
            cursor.execute("""
                SELECT id, order_number, name, surname, email
                FROM orders WHERE id=%s AND project_id=%s
            """, (order_id, project["id"]))
            order = cursor.fetchone()

            if order and order.get("email"):
                ensure_order_feedback_table(conn)
                token = secrets.token_urlsafe(32)
                customer_name = " ".join(filter(None, [order.get("name"), order.get("surname")])) or "Customer"
                fc = conn.cursor()
                fc.execute("""
                    INSERT INTO order_feedback
                        (project_id, order_id, order_number, customer_name, customer_email, token)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE token=token
                """, (project["id"], order["id"], order.get("order_number"), customer_name, order["email"], token))
                conn.commit()
                fc.close()

                host = request.host_url.rstrip("/")
                feedback_url = f"{host}/feedback/{token}"
                restaurant_name = project.get("project_name", "")
                send_email(
                    to=order["email"],
                    subject=f"How was your order? — {restaurant_name}",
                    html_body=build_feedback_request_email(
                        restaurant_name, customer_name, order.get("order_number"), feedback_url
                    ),
                    sender=DEFAULT_INFO_EMAIL,
                    reply_to=get_project_client_email(project["id"])
                )
        except Exception as _fb_exc:
            logging.exception("Feedback email failed for order %s", order_id)

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify(success=True)


@app.route('/confirm_instore_payment/<int:order_id>', methods=['POST'])
@app.route('/admin/<slug>/confirm_instore_payment/<int:order_id>', methods=['POST'])
@login_required
def confirm_instore_payment(order_id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, payment_method, payment_status FROM orders WHERE id=%s AND project_id=%s LIMIT 1",
        (order_id, project["id"])
    )
    order = cursor.fetchone()
    if not order:
        cursor.close()
        conn.close()
        return jsonify(success=False, error="Order not found"), 404

    if order.get("payment_method") not in ("instore", "in-store", "cash", "on_delivery"):
        cursor.close()
        conn.close()
        return jsonify(success=False, error="Cannot manually confirm payment for this payment method."), 400

    cursor.execute(
        "UPDATE orders SET payment_status='paid' WHERE id=%s AND project_id=%s",
        (order_id, project["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(success=True)


# =====================
# Service Overrides
# =====================

@app.route('/admin/<slug>/service-status', methods=['GET'])
@login_required
def service_status(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    conn = get_db_connection()
    ensure_service_override_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT ordering_temp_disabled_until, delivery_temp_disabled_until,
               ordering_temp_enabled_until, delivery_temp_enabled_until
        FROM project_details WHERE project_id=%s LIMIT 1
    """, (project["id"],))
    row = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    now = datetime.now()
    # Include local UTC offset so JS Date() parses as server local time, not browser local time
    import time as _time
    _offset_s = -_time.timezone if not _time.daylight else -_time.altzone
    _sign = '+' if _offset_s >= 0 else '-'
    _oh, _om = divmod(abs(_offset_s) // 60, 60)
    _tz_suffix = f'{_sign}{_oh:02d}:{_om:02d}'
    def _fmt(dt):
        return (dt.isoformat() + _tz_suffix) if dt else None
    def _active(dt):
        return bool(dt and dt > now)

    return jsonify({
        "ordering_disabled": _active(row.get("ordering_temp_disabled_until")),
        "ordering_disabled_until": _fmt(row.get("ordering_temp_disabled_until")),
        "ordering_enabled": _active(row.get("ordering_temp_enabled_until")),
        "ordering_enabled_until": _fmt(row.get("ordering_temp_enabled_until")),
        "delivery_disabled": _active(row.get("delivery_temp_disabled_until")),
        "delivery_disabled_until": _fmt(row.get("delivery_temp_disabled_until")),
        "delivery_enabled": _active(row.get("delivery_temp_enabled_until")),
        "delivery_enabled_until": _fmt(row.get("delivery_temp_enabled_until")),
    })


@app.route('/admin/<slug>/service-override', methods=['POST'])
@login_required
def service_override(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    data = request.get_json(silent=True) or {}
    service = data.get('service')   # 'ordering' or 'delivery'
    action = data.get('action')    # 'disable', 'enable', 'cancel_disable', 'cancel_enable'
    try:
        hours = float(data.get('hours') or 0)
    except (TypeError, ValueError):
        hours = 0

    if service not in ('ordering', 'delivery'):
        return jsonify(success=False, error="Invalid service"), 400
    if action not in ('disable', 'enable', 'cancel_disable', 'cancel_enable'):
        return jsonify(success=False, error="Invalid action"), 400
    if action in ('disable', 'enable') and hours <= 0:
        return jsonify(success=False, error="Hours must be greater than 0"), 400

    disable_col = f"{service}_temp_disabled_until"
    enable_col  = f"{service}_temp_enabled_until"

    conn = get_db_connection()
    ensure_service_override_columns(conn)
    cursor = conn.cursor()

    if action == 'disable':
        until = datetime.now() + timedelta(hours=hours)
        cursor.execute(
            f"UPDATE project_details SET {disable_col}=%s, {enable_col}=NULL WHERE project_id=%s",
            (until, project["id"])
        )
    elif action == 'enable':
        until = datetime.now() + timedelta(hours=hours)
        cursor.execute(
            f"UPDATE project_details SET {enable_col}=%s, {disable_col}=NULL WHERE project_id=%s",
            (until, project["id"])
        )
    elif action == 'cancel_disable':
        cursor.execute(
            f"UPDATE project_details SET {disable_col}=NULL WHERE project_id=%s",
            (project["id"],)
        )
    elif action == 'cancel_enable':
        cursor.execute(
            f"UPDATE project_details SET {enable_col}=NULL WHERE project_id=%s",
            (project["id"],)
        )

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(success=True)


# =====================
# Reject Order
# =====================

def build_order_rejection_email(restaurant_name, customer_name, order_number, reason):
    reason_html = f"<p style='margin:0;color:#7f1d1d;'><em>{escape(reason)}</em></p>" if reason else ""
    return f"""
<div style="font-family:Inter,sans-serif;max-width:580px;margin:0 auto;padding:2rem;background:#fff;border-radius:16px;border:1px solid #fee2e2;">
  <h2 style="margin:0 0 0.5rem;color:#7f1d1d;">Your Order Has Been Cancelled</h2>
  <p style="color:#374151;margin:0 0 1rem;">Hi {escape(customer_name or 'there')}, unfortunately your order
  <strong>#{escape(str(order_number))}</strong> at <strong>{escape(restaurant_name)}</strong> could not be fulfilled.</p>
  {reason_html}
  <p style="color:#6b7280;font-size:0.9rem;margin-top:1rem;">Please contact the restaurant directly if you have questions.</p>
</div>"""


@app.route('/admin/<slug>/reject_order/<int:order_id>', methods=['POST'])
@login_required
def reject_order(order_id, slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()[:500]

    conn = get_db_connection()
    ensure_rejection_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, order_number, name, surname, email FROM orders WHERE id=%s AND project_id=%s LIMIT 1",
        (order_id, project["id"])
    )
    order = cursor.fetchone()
    if not order:
        cursor.close(); conn.close()
        return jsonify(success=False, error="Order not found"), 404

    cursor.execute("""
        UPDATE orders SET status='rejected', rejected_at=NOW(), rejection_reason=%s
        WHERE id=%s AND project_id=%s
    """, (reason or None, order_id, project["id"]))
    conn.commit()
    cursor.close()
    conn.close()

    if order.get("email"):
        customer_name = " ".join(filter(None, [order.get("name"), order.get("surname")])) or "Customer"
        restaurant_name = project.get("project_name", "")
        try:
            send_email(
                to=order["email"],
                subject=f"Order #{order.get('order_number')} Cancelled — {restaurant_name}",
                html_body=build_order_rejection_email(restaurant_name, customer_name, order.get("order_number"), reason),
                sender=DEFAULT_INFO_EMAIL,
                reply_to=get_project_client_email(project["id"])
            )
        except Exception:
            logging.exception("Rejection email failed for order %s", order_id)

    return jsonify(success=True)


@app.route('/admin/<slug>/delivery_payment_settings', methods=['GET', 'POST'])
@login_required
def delivery_payment_settings(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    conn = get_db_connection()
    ensure_delivery_settings_columns(conn)
    cursor = conn.cursor(dictionary=True)

    if request.method == 'GET':
        cursor.execute("""
            SELECT delivery_pay_online, delivery_pay_on_delivery
            FROM project_details WHERE project_id=%s LIMIT 1
        """, (project["id"],))
        row = cursor.fetchone() or {}
        cursor.close()
        conn.close()
        return jsonify(
            delivery_pay_online=db_flag(row.get("delivery_pay_online"), default=1),
            delivery_pay_on_delivery=db_flag(row.get("delivery_pay_on_delivery"), default=1)
        )

    # POST — save settings
    data = request.get_json(silent=True) or {}
    pay_online = 1 if data.get("delivery_pay_online") else 0
    pay_on_del = 1 if data.get("delivery_pay_on_delivery") else 0

    # enforce at least one option
    if not pay_online and not pay_on_del:
        cursor.close()
        conn.close()
        return jsonify(success=False, error="At least one payment option must be enabled."), 400

    cursor.execute("""
        UPDATE project_details
        SET delivery_pay_online=%s, delivery_pay_on_delivery=%s
        WHERE project_id=%s
    """, (pay_online, pay_on_del, project["id"]))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(success=True)


VALID_DELIVERY_STATUSES = ['preparing', 'on_the_way', 'delivered']

@app.route('/admin/<slug>/update_delivery_status/<int:order_id>', methods=['POST'])
@app.route('/worker/<slug>/update_delivery_status/<int:order_id>', methods=['POST'])
@app.route('/update_delivery_status/<int:order_id>', methods=['POST'])
def update_delivery_status(order_id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.get_json(silent=True) or {}
    delivery_status = data.get('delivery_status')

    if delivery_status not in VALID_DELIVERY_STATUSES:
        return jsonify(success=False, error="Invalid delivery status"), 400

    conn = get_db_connection()
    ensure_order_columns(conn)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE orders
        SET delivery_status=%s
        WHERE id=%s AND project_id=%s AND is_delivery=1
    """, (delivery_status, order_id, project["id"]))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(success=True)


@app.route('/admin/<slug>/get_delivery_orders')
@app.route('/worker/<slug>/get_delivery_orders')
@app.route('/get_delivery_orders')
def get_delivery_orders(slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify([])

    conn = get_db_connection()
    ensure_order_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM orders
        WHERE project_id=%s AND is_delivery=1
        ORDER BY created_at DESC
    """, (project["id"],))
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    for row in orders:
        for key in ("created_at", "updated_at"):
            if hasattr(row.get(key), "isoformat"):
                row[key] = row[key].isoformat()
    return jsonify(orders)


@app.route('/admin/<slug>/delivery')
@login_required
def admin_delivery_view(slug):
    project = get_project_for_client(slug)
    if not project:
        return "Unauthorized", 403
    if not is_project_live(project):
        return redirect(url_for("webconfig", slug=slug))
    attach_project_context(project)
    modules = get_project_modules(project["id"])
    return render_template("delivery.html", project=project, MODULES=modules, worker_view=False)


@app.route('/worker/<slug>/delivery')
def worker_delivery_view(slug):
    if not session.get('worker_id'):
        return redirect(url_for('login'))
    if session.get('worker_project_slug') != slug:
        return "Unauthorized", 403
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, project_name, slug FROM projects WHERE slug=%s LIMIT 1", (slug,))
    project = cursor.fetchone()
    cursor.close()
    conn.close()
    if not project:
        return "Project not found", 404
    return render_template("delivery.html", project=project, MODULES={}, worker_view=True)


@app.route('/feedback/<token>', methods=['GET', 'POST'])
def submit_feedback(token):
    conn = get_db_connection()
    ensure_order_feedback_table(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.*, p.project_name,
               (SELECT email FROM clients c
                JOIN projects p2 ON p2.client_id=c.id
                WHERE p2.id=f.project_id LIMIT 1) AS client_email
        FROM order_feedback f
        JOIN projects p ON p.id = f.project_id
        WHERE f.token=%s LIMIT 1
    """, (token,))
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        return "Feedback link not found or expired.", 404

    already_submitted = bool(row.get("submitted_at"))

    if request.method == 'POST':
        if already_submitted:
            cursor.close()
            conn.close()
            return jsonify(success=False, error="Already submitted"), 409

        rating = request.form.get("rating") or request.args.get("rating")
        comment = (request.form.get("comment") or "").strip()

        try:
            rating = int(rating)
            if not 1 <= rating <= 5:
                raise ValueError
        except (TypeError, ValueError):
            cursor.close()
            conn.close()
            return jsonify(success=False, error="Invalid rating"), 400

        uc = conn.cursor()
        uc.execute("""
            UPDATE order_feedback
            SET rating=%s, comment=%s, submitted_at=NOW()
            WHERE token=%s
        """, (rating, comment or None, token))
        conn.commit()
        uc.close()

        # Notify the restaurant client
        restaurant_name = row.get("project_name", "")
        client_email = row.get("client_email")
        stars = "★" * rating + "☆" * (5 - rating)
        if client_email:
            rows_html = (
                _row("Customer", row.get("customer_name")) +
                _row("Order", f"#{row['order_number']}" if row.get("order_number") else "") +
                _row("Rating", f"{stars}  ({rating}/5)") +
                _row("Comment", comment or "No comment left")
            )
            send_email(
                to=client_email,
                subject=f"New Feedback — {restaurant_name}",
                html_body=build_client_notification_email("contact", row.get("customer_name"), restaurant_name, rows_html),
                sender=DEFAULT_INFO_EMAIL
            )

        cursor.close()
        conn.close()

        # Show thank-you page
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Thanks for your feedback</title>
        <style>
          body{{margin:0;font-family:Inter,sans-serif;background:#f8fafc;display:flex;align-items:center;
               justify-content:center;min-height:100vh;color:#0f172a;}}
          .card{{background:#fff;border-radius:24px;padding:48px 40px;max-width:440px;text-align:center;
                 box-shadow:0 20px 60px rgba(0,0,0,0.1);}}
          .star{{font-size:3rem;margin-bottom:16px;}}
          h1{{margin:0 0 10px;font-size:1.6rem;}}
          p{{color:#64748b;line-height:1.7;margin:0;}}
        </style></head><body>
        <div class="card">
          <div class="star">{'★' * rating}</div>
          <h1>Thank you!</h1>
          <p>Your feedback has been sent to <strong>{escape(restaurant_name)}</strong>. We really appreciate you taking the time.</p>
        </div></body></html>"""

    # GET — show the rating form (handles ?rating= from email star buttons)
    prefill_rating = request.args.get("rating", "")
    restaurant_name = row.get("project_name", "")
    stars_html = "".join(
        f'<label class="star-label" title="{i} star{"s" if i>1 else ""}">'
        f'<input type="radio" name="rating" value="{i}" {"checked" if str(i)==prefill_rating else ""}>'
        f'<span>{"★" if str(i)==prefill_rating else "☆"}</span></label>'
        for i in range(1, 6)
    )
    already_html = '<p style="color:#64748b;">You have already submitted feedback for this order. Thank you!</p>' if already_submitted else ""
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Leave Feedback — {escape(restaurant_name)}</title>
    <style>
      *{{box-sizing:border-box;}} body{{margin:0;font-family:Inter,sans-serif;background:#f8fafc;
        display:flex;align-items:center;justify-content:center;min-height:100vh;color:#0f172a;}}
      .card{{background:#fff;border-radius:24px;padding:44px 36px;max-width:460px;width:100%;
             box-shadow:0 20px 60px rgba(0,0,0,0.1);}}
      h1{{margin:0 0 6px;font-size:1.5rem;}} .sub{{color:#64748b;margin:0 0 28px;font-size:0.95rem;}}
      .stars{{display:flex;gap:8px;margin-bottom:22px;font-size:2.4rem;cursor:pointer;}}
      .star-label input{{display:none;}} .star-label span{{transition:color 0.12s;color:#d1d5db;}}
      .star-label input:checked ~ span,.star-label:hover span{{color:#f59e0b;}}
      textarea{{width:100%;border:1.5px solid #e2e8f0;border-radius:12px;padding:12px 14px;
                font-size:14px;font-family:inherit;resize:vertical;min-height:90px;
                outline:none;transition:border-color 0.18s;background:#f8fafc;}}
      textarea:focus{{border-color:#f59e0b;background:#fff;}}
      button{{margin-top:18px;width:100%;padding:13px;border:none;border-radius:12px;
              background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff;font-size:15px;
              font-weight:700;font-family:inherit;cursor:pointer;}}
      button:hover{{opacity:0.92;}}
    </style></head><body>
    <div class="card">
      <h1>How was your experience?</h1>
      <p class="sub">Ordering from <strong>{escape(restaurant_name)}</strong></p>
      {already_html}
      {"" if already_submitted else f'''
      <form method="POST">
        <div class="stars">{stars_html}</div>
        <textarea name="comment" placeholder="Leave a comment (optional)..."></textarea>
        <button type="submit">Submit Feedback</button>
      </form>'''}
    </div></body></html>"""


@app.route('/admin/<slug>/orders/<int:order_id>', methods=['POST'])
@login_required
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

    modules = get_project_modules(project["id"])
    return render_template('worker.html', slug=slug, project=project, MODULES=modules)



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

    modules = get_project_modules(project["id"])
    return render_template(
        "admin_orders.html",
        project=project,
        MODULES=modules,
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
          AND (is_deleted=0 OR is_deleted IS NULL)
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
    ensure_menu_sections_table(conn)
    ensure_categories_section_id_column(conn)
    ensure_deal_upload_attempts_column(conn)
    ensure_location_id_column(conn, "menu_sections")
    ensure_location_id_column(conn, "categories")
    ensure_location_id_column(conn, "products")
    ensure_location_id_column(conn, "deals")
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT product_upload_attempts, deal_upload_attempts
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    upload_details = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    product_upload_attempts = int(upload_details.get("product_upload_attempts") or 0)
    deal_upload_attempts = int(upload_details.get("deal_upload_attempts") or 0)

    return render_template(
        "admin_management.html",
        project=project,
        MODULES=modules,
        product_upload_attempts=product_upload_attempts,
        product_upload_limit=BULK_PRODUCT_UPLOAD_LIMIT,
        deal_upload_attempts=deal_upload_attempts,
        deal_upload_limit=BULK_DEAL_UPLOAD_LIMIT,
        bulk_product_max_bytes=BULK_PRODUCT_MAX_BYTES,
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
        SELECT id, order_number, items, total, payment_method, payment_status, status, name, surname, phone, created_at
        FROM orders
        WHERE project_id=%s
          AND NOT (payment_method = 'instore' AND (payment_status IS NULL OR payment_status != 'paid'))
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

    ensure_project_visits_table(conn)
    cursor.execute("""
        SELECT
            path,
            COUNT(*) AS total_all,
            COUNT(DISTINCT ip_address) AS unique_all,
            SUM(CASE WHEN DATE(visited_at) = CURDATE() THEN 1 ELSE 0 END) AS total_day,
            COUNT(DISTINCT CASE WHEN DATE(visited_at) = CURDATE() THEN ip_address END) AS unique_day,
            SUM(CASE WHEN visited_at >= DATE_FORMAT(NOW(), '%%Y-%%m-01') THEN 1 ELSE 0 END) AS total_month,
            COUNT(DISTINCT CASE WHEN visited_at >= DATE_FORMAT(NOW(), '%%Y-%%m-01') THEN ip_address END) AS unique_month
        FROM project_visits
        WHERE project_id = %s
        GROUP BY path
        ORDER BY total_all DESC
    """, (project_id,))
    page_visits_raw = cursor.fetchall()

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
            try:
                if hasattr(created_at, 'strftime'):
                    day_key = created_at.strftime("%d %b")
                    hourly_orders[created_at.strftime("%H:00")] += 1
                else:
                    from datetime import datetime as _dt
                    created_at = _dt.fromisoformat(str(created_at))
                    day_key = created_at.strftime("%d %b")
                    hourly_orders[created_at.strftime("%H:00")] += 1
                daily_revenue[day_key] += float(order.get("total") or 0)
                daily_orders[day_key] += 1
            except Exception:
                pass

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
        ],
        "page_visits": [
            {
                "path": row["path"] or "/",
                "total_day": int(row["total_day"] or 0),
                "unique_day": int(row["unique_day"] or 0),
                "total_month": int(row["total_month"] or 0),
                "unique_month": int(row["unique_month"] or 0),
                "total_all": int(row["total_all"] or 0),
                "unique_all": int(row["unique_all"] or 0),
            }
            for row in page_visits_raw
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
    ensure_upcoming_events_table(conn)
    ensure_order_feedback_table(conn)
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

    cursor.execute("""
        SELECT id, title, description, event_datetime, disable_online_ordering, created_at
        FROM upcoming_events
        WHERE project_id=%s
        ORDER BY event_datetime ASC, id ASC
    """, (project["id"],))
    upcoming_events = cursor.fetchall()

    cursor.execute("""
        SELECT id, order_number, customer_name, customer_email, rating, comment, submitted_at, created_at
        FROM order_feedback
        WHERE project_id=%s AND submitted_at IS NOT NULL
        ORDER BY submitted_at DESC
    """, (project["id"],))
    feedback_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "customers.html",
        project=project,
        MODULES=modules,
        contact_queries=contact_queries,
        catering_queries=catering_queries,
        reservation_queries=reservation_queries,
        upcoming_events=upcoming_events,
        feedback_list=feedback_list
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

    restaurant_name = project.get("project_name")
    send_email(
        to=recipient,
        subject=subject or f"Message from {restaurant_name}",
        html_body=build_followup_email(restaurant_name, message_body),
        sender=DEFAULT_INFO_EMAIL,
        reply_to=client_email
    )
    return jsonify(success=True, response=combined_response)


@app.route('/admin/<slug>/upcoming_events/add', methods=['POST'])
@login_required
def admin_add_upcoming_event(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    data = request.get_json(silent=True) or request.form or {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    event_datetime_str = (data.get("event_datetime") or "").strip()
    start_datetime_str = (data.get("start_datetime") or "").strip()
    end_datetime_str = (data.get("end_datetime") or "").strip()
    disable_ordering = bool(data.get("disable_online_ordering"))

    if not title:
        return jsonify(success=False, error="Title is required"), 400

    event_dt = None
    start_dt = None
    end_dt = None
    
    # Support legacy event_datetime format
    if event_datetime_str:
        try:
            event_dt = datetime.fromisoformat(event_datetime_str)
        except ValueError:
            pass
    
    # Parse new start_datetime and end_datetime
    if start_datetime_str:
        try:
            start_dt = datetime.fromisoformat(start_datetime_str)
        except ValueError:
            pass
    
    if end_datetime_str:
        try:
            end_dt = datetime.fromisoformat(end_datetime_str)
        except ValueError:
            pass

    conn = get_db_connection()
    ensure_upcoming_events_table(conn)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO upcoming_events (project_id, title, description, event_datetime, start_datetime, end_datetime, disable_online_ordering)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (project["id"], title, description or None, event_dt, start_dt, end_dt, 1 if disable_ordering else 0))
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()

    return jsonify(success=True, id=new_id)


@app.route('/admin/<slug>/upcoming_events/<int:event_id>/delete', methods=['POST'])
@login_required
def admin_delete_upcoming_event(slug, event_id):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False, error="Unauthorized"), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM upcoming_events WHERE id=%s AND project_id=%s",
        (event_id, project["id"])
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    cursor.close()
    conn.close()

    if not deleted:
        return jsonify(success=False, error="Event not found"), 404
    return jsonify(success=True)


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
@login_required
def add_category(slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify(success=False, error="Category name is required."), 400

    section_id = data.get('section_id')
    if section_id not in (None, ''):
        try:
            section_id = int(section_id)
        except (TypeError, ValueError):
            section_id = None

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO categories (project_id, name, section_id) VALUES (%s, %s, %s)",
        (project["id"], name, section_id)
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})



@app.route('/categories/<int:id>', methods=['PUT'])
@app.route('/admin/<slug>/categories/<int:id>', methods=['PUT'])
@login_required
def update_category(id, slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify(success=False, error="Category name is required."), 400

    section_id = data.get('section_id')
    has_section_update = 'section_id' in data
    if section_id not in (None, ''):
        try:
            section_id = int(section_id)
        except (TypeError, ValueError):
            section_id = None
    else:
        section_id = None

    conn = get_db_connection()
    cursor = conn.cursor()

    if has_section_update:
        cursor.execute(
            "UPDATE categories SET name=%s, section_id=%s WHERE id=%s AND project_id=%s",
            (name, section_id, id, project["id"])
        )
    else:
        cursor.execute(
            "UPDATE categories SET name=%s WHERE id=%s AND project_id=%s",
            (name, id, project["id"])
        )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})


@app.route('/categories/<int:id>', methods=['DELETE'])
@app.route('/admin/<slug>/categories/<int:id>', methods=['DELETE'])
@login_required
def delete_category(id, slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

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
        return jsonify(success=False, error="Project not found"), 404

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
@login_required
def add_product(slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    title = request.form.get('title')
    description = request.form.get('description')
    price_raw = request.form.get('price') or 0
    try:
        category_id = int(request.form.get('category_id') or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid category."}), 400
    file = request.files.get('image')

    if file and file.filename:
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
            return jsonify({"success": False, "error": "Invalid image format."}), 400

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


@app.route('/debug/upload-limits', methods=['GET'])
def debug_upload_limits():
    return jsonify({
        "MAX_UPLOAD_BYTES": MAX_UPLOAD_BYTES,
        "MAX_UPLOAD_MB": MAX_UPLOAD_BYTES // (1024 * 1024),
        "MAX_UPLOAD_REQUEST_BYTES": MAX_UPLOAD_REQUEST_BYTES,
        "MAX_UPLOAD_REQUEST_MB": MAX_UPLOAD_REQUEST_BYTES // (1024 * 1024),
        "BULK_PRODUCT_MAX_BYTES": BULK_PRODUCT_MAX_BYTES,
        "BULK_PRODUCT_MAX_MB": BULK_PRODUCT_MAX_BYTES // (1024 * 1024),
        "BULK_PRODUCT_MAX_REQUEST_BYTES": BULK_PRODUCT_MAX_REQUEST_BYTES,
        "BULK_PRODUCT_MAX_REQUEST_MB": BULK_PRODUCT_MAX_REQUEST_BYTES // (1024 * 1024),
        "BULK_DEAL_MAX_BYTES": BULK_DEAL_MAX_BYTES,
        "BULK_DEAL_MAX_MB": BULK_DEAL_MAX_BYTES // (1024 * 1024),
        "BULK_DEAL_MAX_REQUEST_BYTES": BULK_DEAL_MAX_REQUEST_BYTES,
        "BULK_DEAL_MAX_REQUEST_MB": BULK_DEAL_MAX_REQUEST_BYTES // (1024 * 1024),
        "Flask_MAX_CONTENT_LENGTH": app.config.get('MAX_CONTENT_LENGTH'),
        "env_MAX_UPLOAD_BYTES": os.getenv("MAX_UPLOAD_BYTES"),
        "env_BULK_PRODUCT_MAX_BYTES": os.getenv("BULK_PRODUCT_MAX_BYTES"),
        "env_BULK_DEAL_MAX_BYTES": os.getenv("BULK_DEAL_MAX_BYTES"),
        "env_UPLOAD_REQUEST_OVERHEAD_BYTES": os.getenv("UPLOAD_REQUEST_OVERHEAD_BYTES"),
    }), 200


@app.route('/debug/routes', methods=['GET'])
def debug_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            "endpoint": rule.endpoint,
            "rule": str(rule),
            "methods": sorted([m for m in rule.methods if m not in ['HEAD', 'OPTIONS']])
        })
    return jsonify(sorted(routes, key=lambda r: r['rule'])), 200


@app.route('/admin/<slug>/bulk-products-upload', methods=['POST'])
@login_required
def bulk_products_upload(slug):
    print(f"[BULK_UPLOAD] {slug}: bulk upload request received content_length={request.content_length}")
    project = get_project_for_client(slug)
    if not project:
        logging.warning(f"[BULK_UPLOAD] {slug}: Unauthorized access attempt")
        print(f"[BULK_UPLOAD] {slug}: unauthorized client")
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    if request.content_length and request.content_length > BULK_PRODUCT_MAX_REQUEST_BYTES:
        logging.warning(f"[BULK_UPLOAD] {slug}: request content_length exceeds limit ({request.content_length} > {BULK_PRODUCT_MAX_REQUEST_BYTES})")
        print(f"[BULK_UPLOAD] {slug}: request too large before parsing form: {request.content_length} bytes")
        return jsonify({
            "success": False,
            "error": f"Upload is too large. Please keep files under {BULK_PRODUCT_MAX_BYTES // (1024 * 1024)}MB."
        }), 413

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

    upload = request.files.get("catalogue")
    if not upload or not upload.filename:
        print(f"[BULK_UPLOAD] {slug}: no upload file found or filename empty. request.files={list(request.files.keys())}")
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Please upload an image, PDF, DOCX, TXT, or CSV file."}), 400

    extension = get_file_extension(upload.filename)
    if extension not in BULK_PRODUCT_ALLOWED_EXTENSIONS:
        print(f"[BULK_UPLOAD] {slug}: unsupported upload extension '{extension}' for file '{upload.filename}'")
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Unsupported file type. Use an image, PDF, DOCX, TXT, or CSV."}), 400

    file_bytes = upload.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)
    print(f"[BULK_UPLOAD] {slug}: upload read complete file={upload.filename} extension={extension} size={len(file_bytes)} bytes ({file_size_mb:.2f}MB) limit={BULK_PRODUCT_MAX_BYTES/(1024*1024):.0f}MB")
    logging.info(f"[BULK_UPLOAD] {slug}: file={upload.filename}, size={file_size_mb:.2f}MB (limit={BULK_PRODUCT_MAX_BYTES/(1024*1024):.0f}MB)")
    
    if not file_bytes:
        print(f"[BULK_UPLOAD] {slug}: upload file read empty")
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "The uploaded file was empty."}), 400

    if upload.content_length and upload.content_length > BULK_PRODUCT_MAX_BYTES:
        print(f"[BULK_UPLOAD] {slug}: upload.content_length too large: {upload.content_length} bytes")
        logging.warning(f"[BULK_UPLOAD] {slug}: content_length exceeds limit ({upload.content_length} > {BULK_PRODUCT_MAX_BYTES})")
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": f"Upload is too large. Please keep files under {BULK_PRODUCT_MAX_BYTES // (1024 * 1024)}MB."
        }), 413

    if len(file_bytes) > BULK_PRODUCT_MAX_BYTES:
        print(f"[BULK_UPLOAD] {slug}: actual file size too large: {len(file_bytes)} bytes")
        logging.warning(f"[BULK_UPLOAD] {slug}: file_bytes exceeds limit ({len(file_bytes)} > {BULK_PRODUCT_MAX_BYTES})")
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": f"Upload is too large. Please keep files under {BULK_PRODUCT_MAX_BYTES // (1024 * 1024)}MB."
        }), 413

    attempts += 1
    cursor.execute("""
        UPDATE project_details
        SET product_upload_attempts=%s
        WHERE project_id=%s
    """, (attempts, project["id"]))
    conn.commit()
    cursor.close()
    conn.close()

    job_id = secrets.token_urlsafe(16)
    with _bulk_upload_jobs_lock:
        _bulk_upload_jobs[job_id] = {"status": "processing"}

    t = threading.Thread(
        target=_run_bulk_upload_background,
        args=(job_id, project, file_bytes, extension, attempts, BULK_PRODUCT_UPLOAD_LIMIT),
        daemon=True
    )
    t.start()

    return jsonify({"status": "processing", "job_id": job_id}), 202


@app.route('/admin/<slug>/bulk-products-status/<job_id>', methods=['GET'])
@login_required
def bulk_products_status(slug, job_id):
    project = get_project_for_client(slug)
    if not project:
        return jsonify({"error": "Unauthorized"}), 403

    with _bulk_upload_jobs_lock:
        job = _bulk_upload_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] == "done":
        with _bulk_upload_jobs_lock:
            _bulk_upload_jobs.pop(job_id, None)
        return jsonify({"status": "done", "success": True, **job})

    if job["status"] == "error":
        with _bulk_upload_jobs_lock:
            _bulk_upload_jobs.pop(job_id, None)
        return jsonify({"status": "error", "success": False, **job})

    return jsonify({"status": "processing"})



@app.route('/products/<int:id>', methods=['PUT'])
@app.route('/admin/<slug>/products/<int:id>', methods=['PUT'])
@login_required
def update_product(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

    title = request.form.get('title')
    description = request.form.get('description')
    try:
        price = float(request.form.get('price') or 0)
        category_id = int(request.form.get('category_id') or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid price or category."}), 400
    file = request.files.get('image')

    if file and file.filename:
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
            return jsonify({"success": False, "error": "Invalid image format."}), 400
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
@login_required
def delete_product(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

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
BULK_DEAL_UPLOAD_LIMIT = 5


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
        section = compact_whitespace(item.get("section") or "")[:90]
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
            "section": section,
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
      "section": "Broad menu group, e.g. Pizzas, Burgers, Drinks",
      "category": "Specific sub-category, e.g. Traditional Pizzas, Loaded Pizzas",
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
- section is a broad grouping that sits ABOVE category (e.g. "Pizzas" contains "Traditional Pizzas" and "Loaded Pizzas"). Use section when the menu has visible top-level headings or natural groupings. If there is no clear broader grouping, leave section as an empty string "".
- category is the direct sub-group the product belongs to. Create sensible names from visible menu sections. If none are visible, use "Menu".
- Products map to products.title, products.description, products.price, and category_id.
- Ranking maps to products.has_ranking plus rank1_name/rank1_price through rank4_name/rank4_price.
- If a product has ranking or sizes, put every visible size/variant in ranks and use the first rank price as product price.
- If a product has no ranking, ranks must be [] and price must be the visible product price.
- Details/descriptions must be at least 10 words. If missing, write a natural product description.
- Extract products only. Do not include deals, bundles, business hours, headings, contact info, or notes as products.
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
    print(f"[MENU_AI] Sending menu file to AI for extraction: project='{project_name}', extension='{extension}', size={len(file_bytes)} bytes")
    logging.info("[MENU_AI] extract_bulk_products_with_ai: project='%s', ext='%s', bytes=%d", project_name, extension, len(file_bytes))

    messages = build_bulk_product_openai_messages(project_name, file_bytes, extension)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or "{}"
    print(f"[MENU_AI] Received AI response for '{project_name}': {len(raw_content)} chars")
    payload = json.loads(raw_content)
    products = normalize_bulk_product_payload(payload)
    print(f"[MENU_AI] Normalized {len(products)} products from AI response for project='{project_name}'")
    logging.info("[MENU_AI] Extracted %d products for project='%s'", len(products), project_name)
    return products


def get_or_create_section_id(cursor, project_id, section_name, section_cache):
    if not section_name or not section_name.strip():
        return None
    lookup_key = section_name.strip().lower()
    if lookup_key in section_cache:
        return section_cache[lookup_key]

    cursor.execute(
        "SELECT id FROM menu_sections WHERE project_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1",
        (project_id, section_name)
    )
    row = cursor.fetchone()

    if row:
        section_id = row[0] if not isinstance(row, dict) else row["id"]
    else:
        cursor.execute(
            "INSERT INTO menu_sections (project_id, name) VALUES (%s, %s)",
            (project_id, section_name)
        )
        section_id = cursor.lastrowid

    section_cache[lookup_key] = section_id
    return section_id


def get_or_create_category_id(cursor, project_id, category_name, category_cache, section_id=None):
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
        if section_id:
            cursor.execute(
                "UPDATE categories SET section_id=%s WHERE id=%s AND section_id IS NULL",
                (section_id, category_id)
            )
    else:
        cursor.execute(
            "INSERT INTO categories (project_id, name, section_id) VALUES (%s, %s, %s)",
            (project_id, category_name, section_id)
        )
        category_id = cursor.lastrowid

    category_cache[lookup_key] = category_id
    return category_id


def insert_bulk_products(cursor, project_id, products):
    cursor.execute("SELECT id, name FROM categories WHERE project_id=%s", (project_id,))
    category_cache = {str(row[1]).strip().lower(): row[0] for row in cursor.fetchall()}
    section_cache = {}

    inserted_count = 0
    category_names = set()

    for product in products:
        section_name = product.get("section", "")
        section_id = get_or_create_section_id(cursor, project_id, section_name, section_cache) if section_name else None
        category_id = get_or_create_category_id(cursor, project_id, product["category"], category_cache, section_id=section_id)
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


def _serialize_or_options(or_options):
    safe = []
    for opt in (or_options or []):
        section_id = opt.get("section_id")
        if section_id not in (None, ""):
            try:
                section_id = int(section_id)
            except (TypeError, ValueError):
                section_id = None
            if section_id and section_id > 0:
                safe.append({"product_id": None, "category_id": None, "section_id": section_id,
                              "product_title": (opt.get("product_title") or "").strip(),
                              "rank_name": (opt.get("rank_name") or "").strip() or None, "rank_price": None})
                continue

        category_id = opt.get("category_id")
        if category_id not in (None, ""):
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                category_id = None
            if category_id and category_id > 0:
                safe.append({"product_id": None, "category_id": category_id,
                              "product_title": (opt.get("product_title") or "").strip(),
                              "rank_name": (opt.get("rank_name") or "").strip() or None, "rank_price": None})
                continue

        try:
            product_id = int(opt.get("product_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if product_id > 0:
            rank_name = (opt.get("rank_name") or "").strip() or None
            rank_price = (float(opt.get("rank_price")) if opt.get("rank_price") not in (None, "") else None)
            safe.append({"product_id": product_id, "product_title": (opt.get("product_title") or "").strip(),
                         "rank_name": rank_name, "rank_price": rank_price})
    return safe


def validate_bundle_or_options(bundle_items):
    for item in (bundle_items or []):
        or_options = item.get("or_options") or []
        if not or_options:
            continue
        all_options = [item] + list(or_options)
        ranks = [(o.get("rank_name") or "").strip().lower() for o in all_options]
        if len(set(ranks)) > 1:
            titles = " OR ".join(
                f"{o.get('product_title', 'Item')} ({o.get('rank_name') or 'no variant'})"
                for o in all_options
            )
            return f"All OR alternatives in a bundle row must use the same variant: {titles}"
    return None


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

        section_id = item.get("section_id")
        if section_id not in (None, ""):
            try:
                section_id = int(section_id)
            except (TypeError, ValueError):
                section_id = None

            if section_id and section_id > 0:
                safe_items.append({
                    "product_id": None,
                    "category_id": None,
                    "section_id": section_id,
                    "quantity": quantity,
                    "product_title": (item.get("product_title") or "").strip(),
                    "rank_name": (item.get("rank_name") or "").strip() or None,
                    "rank_price": None,
                    "or_options": _serialize_or_options(item.get("or_options") or [])
                })
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
                    "rank_name": (item.get("rank_name") or "").strip() or None,
                    "rank_price": None,
                    "or_options": _serialize_or_options(item.get("or_options") or [])
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
            ),
            "or_options": _serialize_or_options(item.get("or_options") or [])
        })

    if not safe_items:
        return base_description

    return f"{base_description}{DEAL_BUNDLE_MARKER}{json.dumps(safe_items, separators=(',', ':'))}"


# ======================
# Bulk Deals AI Upload
# ======================


def build_bulk_deals_prompt(project_name):
    return f"""
You are extracting promotional deals and combo offers from a restaurant menu image or document for WebBuilderMD.

Return ONLY valid JSON with this exact shape:
{{
  "deals": [
    {{
      "title": "Combo or deal name",
      "price": 29.99,
      "type": "deal",
      "description": "A natural one-sentence summary of what this deal includes.",
      "bundle_items": [
        {{"label": "Item description", "quantity": 1}}
      ]
    }}
  ]
}}

Rules you must follow:
- title must be the exact name of the deal or combo as shown.
- price must be the total deal price as a number. No currency symbols.
- type must be "deal" or "hot". Use "hot" only if the deal is explicitly labelled as a special, featured, or hot deal. Otherwise use "deal".
- description: write a natural one-sentence summary of everything included in the deal.
- bundle_items: list every distinct item or item group in the deal. Each label should describe the item clearly (e.g. "Large Classic Pizza", "Garlic Bread", "1.25L Drink", "300ML Drink"). Use the quantity field for how many of that item are in the deal.
- Only extract actual deals, combos, or bundles. Do not extract individual products, business hours, headings, contact info, or notes as deals.
- Prefer accuracy over guessing. Skip any deal without a clear name and price.

Business/project name: {project_name}
""".strip()


def build_bulk_deals_openai_messages(project_name, file_bytes, extension):
    prompt = build_bulk_deals_prompt(project_name)

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
        "content": f"{prompt}\n\nUploaded deals/menu text:\n{extracted_text[:18000]}",
    }]


def normalize_bulk_deal_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("The AI response was not valid deal data.")

    raw_deals = payload.get("deals")
    if not isinstance(raw_deals, list):
        raise ValueError("No deal list was returned.")

    normalized = []
    seen_titles = set()

    for item in raw_deals:
        if not isinstance(item, dict):
            continue

        title = compact_whitespace(item.get("title") or "")[:140]
        price = normalize_price(item.get("price"))
        deal_type = str(item.get("type") or "deal").strip().lower()
        if deal_type not in ("deal", "hot"):
            deal_type = "deal"
        description = compact_whitespace(item.get("description") or "")[:600]

        bundle_items = []
        for bi in (item.get("bundle_items") or []):
            if not isinstance(bi, dict):
                continue
            label = compact_whitespace(bi.get("label") or "")[:200]
            try:
                quantity = max(1, int(bi.get("quantity") or 1))
            except (TypeError, ValueError):
                quantity = 1
            if label:
                bundle_items.append({"label": label, "quantity": quantity})

        if not title or price is None:
            continue

        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)

        normalized.append({
            "title": title,
            "price": price,
            "type": deal_type,
            "description": description,
            "bundle_items": bundle_items,
        })

    if not normalized:
        raise ValueError("No usable deals were found in the upload.")

    return normalized


def match_bundle_label_to_category_or_section(label, categories, sections):
    label_lower = label.strip().lower()
    for section in sections:
        sname = str(section.get("name") or "").strip().lower()
        if sname and (sname in label_lower or label_lower in sname):
            return "section", section["id"], section["name"]
    for cat in categories:
        cname = str(cat.get("name") or "").strip().lower()
        if cname and (cname in label_lower or label_lower in cname):
            return "category", cat["id"], cat["name"]
    return None, None, None


def insert_bulk_deals(cursor, project_id, deals):
    cursor.execute("SELECT id, name FROM categories WHERE project_id=%s", (project_id,))
    categories = [{"id": r[0] if not isinstance(r, dict) else r["id"],
                   "name": r[1] if not isinstance(r, dict) else r["name"]}
                  for r in cursor.fetchall()]
    cursor.execute("SELECT id, name FROM menu_sections WHERE project_id=%s", (project_id,))
    sections = [{"id": r[0] if not isinstance(r, dict) else r["id"],
                 "name": r[1] if not isinstance(r, dict) else r["name"]}
                for r in cursor.fetchall()]

    upserted = 0
    for deal in deals:
        bundle_items = []
        for bi in deal.get("bundle_items", []):
            label = bi.get("label", "")
            quantity = bi.get("quantity", 1)
            match_type, match_id, match_name = match_bundle_label_to_category_or_section(label, categories, sections)
            if match_type == "section":
                bundle_items.append({
                    "product_id": None,
                    "category_id": None,
                    "section_id": match_id,
                    "quantity": quantity,
                    "product_title": f"Any {match_name}",
                    "rank_name": None,
                    "rank_price": None,
                })
            elif match_type == "category":
                bundle_items.append({
                    "product_id": None,
                    "category_id": match_id,
                    "quantity": quantity,
                    "product_title": f"Any {match_name}",
                    "rank_name": None,
                    "rank_price": None,
                })

        serialized_description = serialize_deal_description(deal["description"], bundle_items)

        cursor.execute(
            "SELECT id FROM deals WHERE project_id=%s AND LOWER(title)=LOWER(%s) LIMIT 1",
            (project_id, deal["title"])
        )
        existing = cursor.fetchone()
        if existing:
            existing_id = existing[0] if not isinstance(existing, dict) else existing["id"]
            cursor.execute(
                """
                UPDATE deals
                SET title=%s, description=%s, price=%s, type=%s
                WHERE id=%s AND project_id=%s
                """,
                (deal["title"], serialized_description, deal["price"], deal["type"], existing_id, project_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO deals (project_id, title, description, price, type, products)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (project_id, deal["title"], serialized_description, deal["price"], deal["type"], "")
            )

        upserted += 1

    return upserted


def extract_bulk_deals_with_ai(project_name, file_bytes, extension):
    print(f"[DEALS_AI] Sending file to AI for deal extraction: project='{project_name}', ext='{extension}', size={len(file_bytes)} bytes")
    messages = build_bulk_deals_openai_messages(project_name, file_bytes, extension)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or "{}"
    print(f"[DEALS_AI] Received AI response for '{project_name}': {len(raw_content)} chars")
    payload = json.loads(raw_content)
    deals = normalize_bulk_deal_payload(payload)
    print(f"[DEALS_AI] Normalized {len(deals)} deals from AI response for project='{project_name}'")
    return deals


_bulk_deal_jobs: dict[str, dict] = {}
_bulk_deal_jobs_lock = threading.Lock()


def _run_bulk_deals_background(job_id, project, file_bytes, extension, attempts, attempt_limit):
    try:
        extracted = extract_bulk_deals_with_ai(project["project_name"], file_bytes, extension)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            upserted = insert_bulk_deals(cursor, project["id"], extracted)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        with _bulk_deal_jobs_lock:
            _bulk_deal_jobs[job_id] = {
                "status": "done",
                "success": True,
                "upserted_deals": upserted,
                "attempts_used": attempts,
                "attempts_remaining": max(attempt_limit - attempts, 0),
                "disabled": attempts >= attempt_limit,
            }
    except Exception as exc:
        logging.exception("Background bulk deal upload failed for job %s", job_id)
        with _bulk_deal_jobs_lock:
            _bulk_deal_jobs[job_id] = {
                "status": "error",
                "error": str(exc) or "Extraction or import failed.",
                "attempts_used": attempts,
                "attempts_remaining": max(attempt_limit - attempts, 0),
                "disabled": attempts >= attempt_limit,
            }


@app.route('/admin/<slug>/bulk-deals-upload', methods=['POST'])
@login_required
def bulk_deals_upload(slug):
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

    if len(file_bytes) > BULK_DEAL_MAX_BYTES:
        return jsonify({"success": False, "error": f"Upload is too large. Please keep files under {BULK_DEAL_MAX_BYTES // (1024 * 1024)}MB."}), 400

    conn = get_db_connection()
    ensure_deal_upload_attempts_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT deal_upload_attempts
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone()

    if not details:
        cursor.execute(
            "INSERT INTO project_details (project_id, deal_upload_attempts) VALUES (%s, 0)",
            (project["id"],)
        )
        conn.commit()
        attempts = 0
    else:
        attempts = int(details.get("deal_upload_attempts") or 0)

    if attempts >= BULK_DEAL_UPLOAD_LIMIT:
        cursor.close()
        conn.close()
        return jsonify({
            "success": False,
            "error": "Bulk deal upload limit reached.",
            "attempts_used": attempts,
            "attempts_remaining": 0,
            "disabled": True,
        }), 403

    attempts += 1
    cursor.execute("""
        UPDATE project_details
        SET deal_upload_attempts=%s
        WHERE project_id=%s
    """, (attempts, project["id"]))
    conn.commit()
    cursor.close()
    conn.close()

    job_id = secrets.token_urlsafe(16)
    with _bulk_deal_jobs_lock:
        _bulk_deal_jobs[job_id] = {"status": "processing"}

    t = threading.Thread(
        target=_run_bulk_deals_background,
        args=(job_id, project, file_bytes, extension, attempts, BULK_DEAL_UPLOAD_LIMIT),
        daemon=True
    )
    t.start()

    return jsonify({"status": "processing", "job_id": job_id}), 202


@app.route('/admin/<slug>/bulk-deals-status/<job_id>', methods=['GET'])
@login_required
def bulk_deals_status(slug, job_id):
    project = get_project_for_client(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    with _bulk_deal_jobs_lock:
        job = _bulk_deal_jobs.get(job_id)

    if not job:
        return jsonify({"status": "error", "error": "Job not found."}), 404

    if job.get("status") == "done":
        with _bulk_deal_jobs_lock:
            _bulk_deal_jobs.pop(job_id, None)
        return jsonify({**job, "success": True})

    if job.get("status") == "error":
        with _bulk_deal_jobs_lock:
            _bulk_deal_jobs.pop(job_id, None)
        return jsonify({**job, "success": False}), 400

    return jsonify(job)


@app.route('/categories', methods=['GET'])
@app.route('/admin/<slug>/categories', methods=['GET'])
def get_categories(slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    conn = get_db_connection()
    ensure_categories_section_id_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT c.id, c.name, c.section_id, ms.name AS section_name
        FROM categories c
        LEFT JOIN menu_sections ms ON c.section_id = ms.id
        WHERE c.project_id=%s
        ORDER BY c.id
        """,
        (project["id"],)
    )

    data = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(data)


# ======================
# API — Menu Sections
# ======================


@app.route('/menu-sections', methods=['GET'])
@app.route('/admin/<slug>/menu-sections', methods=['GET'])
def get_menu_sections(slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    conn = get_db_connection()
    ensure_menu_sections_table(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name FROM menu_sections WHERE project_id=%s ORDER BY id",
        (project["id"],)
    )
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(data)


@app.route('/menu-sections', methods=['POST'])
@app.route('/admin/<slug>/menu-sections', methods=['POST'])
@login_required
def add_menu_section(slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify(success=False, error="Section name is required."), 400

    conn = get_db_connection()
    ensure_menu_sections_table(conn)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO menu_sections (project_id, name) VALUES (%s, %s)",
        (project["id"], name)
    )
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True, 'id': new_id})


@app.route('/menu-sections/<int:id>', methods=['PUT'])
@app.route('/admin/<slug>/menu-sections/<int:id>', methods=['PUT'])
@login_required
def update_menu_section(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify(success=False, error="Section name is required."), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE menu_sections SET name=%s WHERE id=%s AND project_id=%s",
        (name, id, project["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})


@app.route('/menu-sections/<int:id>', methods=['DELETE'])
@app.route('/admin/<slug>/menu-sections/<int:id>', methods=['DELETE'])
@login_required
def delete_menu_section(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE categories SET section_id=NULL WHERE section_id=%s AND project_id=%s",
        (id, project["id"])
    )
    cursor.execute(
        "DELETE FROM menu_sections WHERE id=%s AND project_id=%s",
        (id, project["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})



@app.route('/deals', methods=['GET'])
@app.route('/admin/<slug>/deals', methods=['GET'])
def get_deals(slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify(success=False, error="Project not found"), 404

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
@login_required
def add_deal(slug=None):

    project = resolve_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

    title = request.form.get('title')
    description = request.form.get('description')
    price = request.form.get('price')
    type_ = request.form.get('type')
    if not title or not type_:
        return jsonify({"success": False, "error": "Title and type are required."}), 400
    bundle_items_raw = request.form.get('bundle_items', '[]')
    file = request.files.get('image')

    try:
        bundle_items = json.loads(bundle_items_raw)
    except json.JSONDecodeError:
        bundle_items = []

    or_error = validate_bundle_or_options(bundle_items)
    if or_error:
        return jsonify({"error": or_error}), 400

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
@login_required
def delete_deal(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

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
@login_required
def update_deal(id, slug=None):
    project = resolve_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404

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

    or_error = validate_bundle_or_options(bundle_items)
    if or_error:
        return jsonify({"error": or_error}), 400

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
                data.get('title'),
                serialized_description,
                data.get('price'),
                data.get('type'),
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
                data.get('title'),
                serialized_description,
                data.get('price'),
                data.get('type'),
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
        LIMIT 1
    """, (slug,))
    details = cursor.fetchone() or {}
    cursor.fetchall()

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


@app.route('/site.webmanifest')
def site_webmanifest():
    """Generate web app manifest for PWA support."""
    project_name = "Restaurant"
    primary_color = "#111827"
    background_color = "#ffffff"
    
    if hasattr(g, "project") and g.project:
        settings = get_project_settings(g.project["id"])
        project_name = g.project.get("project_name") or "Restaurant"
        primary_color = settings.get("primary_color") or "#111827"
        background_color = settings.get("background_color") or "#ffffff"
    
    payload = {
        "name": project_name,
        "short_name": project_name[:12],
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": background_color,
        "theme_color": primary_color,
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


@app.route("/project_qr_code/<slug>")
@login_required
def project_qr_code(slug):
    conn = get_db_connection()
    ensure_projects_deployment_column(conn)
    ensure_project_details_qr_asset_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.is_deployed, d.qr_code_path
        FROM projects p
        LEFT JOIN project_details d ON p.id = d.project_id
        WHERE p.slug = %s AND p.client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))
    details = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    if not is_project_deployed(details):
        return ("", 404)

    qr_code_path = resolve_uploaded_asset_path(details.get("qr_code_path"))
    if not qr_code_path:
        return ("", 204)

    return redirect(url_for("uploads", filename=qr_code_path.split("uploads/", 1)[1]))


@app.route("/project_qr_poster/<slug>")
@login_required
def project_qr_poster(slug):
    conn = get_db_connection()
    ensure_projects_deployment_column(conn)
    ensure_project_details_qr_asset_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.is_deployed, d.qr_poster_pdf_path
        FROM projects p
        LEFT JOIN project_details d ON p.id = d.project_id
        WHERE p.slug = %s AND p.client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))
    details = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    if not is_project_deployed(details):
        return ("", 404)

    pdf_path = resolve_uploaded_asset_path(details.get("qr_poster_pdf_path"))
    if not pdf_path:
        return ("", 204)

    return redirect(url_for("uploads", filename=pdf_path.split("uploads/", 1)[1]))


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
    ensure_project_details_qr_asset_columns(conn)
    ensure_stripe_project_columns(conn)
    ensure_ordering_hours_columns(conn)
    ensure_project_settings_css_theme_column(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.id, p.project_name, p.slug, p.created_at, p.is_deployed, p.is_deploying,
               p.stripe_account_id, p.stripe_enabled,
               d.slogan, d.story, d.address, d.phone, d.contact_email, d.pay_in_store,
               d.operating_hours, d.online_ordering_hours, d.online_ordering_enabled, d.ordering_follows_op,
               d.hero_image, d.hero_image_path, d.hero_image_regen_attempts, d.hero_image_history,
               d.qr_code_path, d.qr_poster_pdf_path, d.qr_install_url,
               s.primary_color, s.secondary_color, s.background_color,
               s.logo_path, s.css_theme
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
    _stored_hero_path = resolve_hero_image_path(project.get("hero_image_path"))
    project["hero_image_path"] = resolve_hero_image_path(project.get("hero_image_path") or project.get("hero_image"))
    if _stored_hero_path:
        project["hero_image_preview_url"] = resolve_uploaded_asset_url(_stored_hero_path)
    elif project.get("hero_image"):
        project["hero_image_preview_url"] = url_for("project_hero_image", slug=project["slug"])
    else:
        project["hero_image_preview_url"] = ""
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
    project["qr_code_path"] = resolve_uploaded_asset_path(project.get("qr_code_path"))
    project["qr_poster_pdf_path"] = resolve_uploaded_asset_path(project.get("qr_poster_pdf_path"))
    project["qr_install_url"] = (project.get("qr_install_url") or build_mobile_install_url(project.get("slug"))).strip()
    project["qr_code_url"] = url_for("project_qr_code", slug=project["slug"]) if project["qr_code_path"] else ""
    project["qr_poster_url"] = url_for("project_qr_poster", slug=project["slug"]) if project["qr_poster_pdf_path"] else ""

    cursor.execute("""
        SELECT *
        FROM project_modules
        WHERE project_id = %s
        LIMIT 1
    """, (project["id"],))

    modules = cursor.fetchone() or {}

    cursor.close()
    conn.close()

    raw_op_hours  = project.get("operating_hours") or ""
    raw_ord_hours = project.get("online_ordering_hours") or ""

    try:
        op_hours_obj = json.loads(raw_op_hours) if raw_op_hours else {}
    except Exception:
        op_hours_obj = {}
    try:
        ord_hours_obj = json.loads(raw_ord_hours) if raw_ord_hours else {}
    except Exception:
        ord_hours_obj = {}

    module_change_conn = get_db_connection()
    ensure_project_module_changes_table(module_change_conn)
    mc_cursor = module_change_conn.cursor(dictionary=True)
    mc_cursor.execute("""
        SELECT new_total_cost, effective_date FROM project_module_changes
        WHERE project_id=%s AND status='pending' LIMIT 1
    """, (project["id"],))
    pending_module_change = mc_cursor.fetchone()
    mc_cursor.close()
    module_change_conn.close()

    return render_template(
        "webconfig.html",
        project=project,
        modules=modules,
        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
        op_hours=op_hours_obj,
        ord_hours=ord_hours_obj,
        hours_days=HOURS_DAYS,
        locations=get_project_locations(project["id"]),
        pending_module_change=pending_module_change,
    )


@app.route("/admin/<slug>/config/update", methods=["POST"])
@login_required
def update_webconfig(slug):
    payload = request.get_json(silent=True) or {} or request.form

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

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

    pay_in_store_enabled = payload.get("pay_in_store_enabled")

    _valid_themes = {"main", "main2", "main3"}
    css_theme = (payload.get("css_theme") or "main").strip()
    if css_theme not in _valid_themes:
        css_theme = "main"

    conn2 = get_db_connection()
    ensure_project_settings_css_theme_column(conn2)
    conn2.close()

    cursor.execute("""
        UPDATE project_settings
        SET primary_color = %s,
            secondary_color = %s,
            background_color = %s,
            css_theme = %s,
            updated_at = NOW()
        WHERE project_id = %s
    """, (
        payload.get("primary_color") or "#2563eb",
        payload.get("secondary_color") or "#0f172a",
        payload.get("background_color") or "#111111",
        css_theme,
        project["id"]
    ))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_settings (
                project_id, primary_color, secondary_color, background_color, css_theme, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (
            project["id"],
            payload.get("primary_color") or "#2563eb",
            payload.get("secondary_color") or "#0f172a",
            payload.get("background_color") or "#111111",
            css_theme,
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


@app.route("/admin/<slug>/config/update-details", methods=["POST"])
@login_required
def update_business_details(slug):
    payload = request.get_json(silent=True) or {}

    slogan = (payload.get("slogan") or "").strip()
    story = (payload.get("story") or "").strip()
    address = (payload.get("address") or "").strip()
    phone = (payload.get("phone") or "").strip()
    contact_email = (payload.get("contact_email") or "").strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM projects WHERE slug = %s AND client_id = %s LIMIT 1",
                   (slug, session["client_id"]))
    project = cursor.fetchone()
    if not project:
        cursor.close(); conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    cursor.execute("""
        UPDATE project_details
        SET slogan = %s, story = %s, address = %s, phone = %s, contact_email = %s
        WHERE project_id = %s
    """, (slogan, story, address, phone, contact_email, project["id"]))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO project_details (project_id, slogan, story, address, phone, contact_email)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (project["id"], slogan, story, address, phone, contact_email))

    # Keep the primary location's address/phone in sync — this is the field
    # most clients edit, and single/primary-location projects should never
    # need to visit the newer Locations UI just to update their address.
    ensure_locations_table(conn)
    cursor.execute(
        "UPDATE locations SET address=%s, phone=%s WHERE project_id=%s AND is_primary=1",
        (address, phone, project["id"])
    )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"success": True})


def _get_owned_project(slug):
    """Ownership-checked project lookup shared by the Locations admin routes."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM projects WHERE slug=%s AND client_id=%s LIMIT 1",
                   (slug, session["client_id"]))
    project = cursor.fetchone()
    cursor.close()
    return project, conn


@app.route("/admin/<slug>/locations/add", methods=["POST"])
@login_required
def admin_add_location(slug):
    payload = request.get_json(silent=True) or {}
    project, conn = _get_owned_project(slug)
    if not project:
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    ensure_locations_table(conn)
    cursor = conn.cursor(dictionary=True)

    name = (payload.get("name") or "").strip()[:150] or "New Location"
    address = (payload.get("address") or "").strip()[:255]
    city = (payload.get("city") or "").strip()[:100]
    postcode = (payload.get("postcode") or "").strip()[:20]
    country = (payload.get("country") or "").strip()[:100]
    phone = (payload.get("phone") or "").strip()[:30]

    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM locations WHERE project_id=%s AND is_active=1",
        (project["id"],)
    )
    is_first = (cursor.fetchone() or {}).get("cnt", 0) == 0

    cursor.execute("""
        INSERT INTO locations (project_id, name, address, city, postcode, country, phone, is_primary)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (project["id"], name, address, city, postcode, country, phone, 1 if is_first else 0))
    conn.commit()
    new_id = cursor.lastrowid

    # Adding a 2nd+ location is the real-world trigger for backfilling every
    # location-scoped table for this project — idempotent no-ops for tables
    # already fully backfilled, so it's safe to call broadly here.
    for table in ("orders", "products", "deals", "menu_sections", "categories",
                  "restaurant_tables", "table_bookings", "table_booking_blocked",
                  "table_booking_config", "table_booking_hours",
                  "reservations", "catering_inquiries"):
        ensure_location_id_column(conn, table)

    cursor.close()
    conn.close()
    return jsonify({"success": True, "id": new_id})


@app.route("/admin/<slug>/locations/<int:location_id>/update", methods=["POST"])
@login_required
def admin_update_location(slug, location_id):
    payload = request.get_json(silent=True) or {}
    project, conn = _get_owned_project(slug)
    if not project:
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    ensure_locations_table(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id FROM locations WHERE id=%s AND project_id=%s LIMIT 1",
        (location_id, project["id"])
    )
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Location not found"}), 404

    name = (payload.get("name") or "").strip()[:150] or "Location"
    address = (payload.get("address") or "").strip()[:255]
    city = (payload.get("city") or "").strip()[:100]
    postcode = (payload.get("postcode") or "").strip()[:20]
    country = (payload.get("country") or "").strip()[:100]
    phone = (payload.get("phone") or "").strip()[:30]

    cursor.execute("""
        UPDATE locations SET name=%s, address=%s, city=%s, postcode=%s, country=%s, phone=%s
        WHERE id=%s AND project_id=%s
    """, (name, address, city, postcode, country, phone, location_id, project["id"]))

    if payload.get("make_primary"):
        cursor.execute("UPDATE locations SET is_primary=0 WHERE project_id=%s", (project["id"],))
        cursor.execute(
            "UPDATE locations SET is_primary=1 WHERE id=%s AND project_id=%s",
            (location_id, project["id"])
        )

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/admin/<slug>/locations/<int:location_id>/deactivate", methods=["POST"])
@login_required
def admin_deactivate_location(slug, location_id):
    project, conn = _get_owned_project(slug)
    if not project:
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    ensure_locations_table(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, is_primary FROM locations WHERE id=%s AND project_id=%s AND is_active=1 LIMIT 1",
        (location_id, project["id"])
    )
    loc = cursor.fetchone()
    if not loc:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Location not found"}), 404

    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM locations WHERE project_id=%s AND is_active=1",
        (project["id"],)
    )
    active_count = (cursor.fetchone() or {}).get("cnt", 0)
    if active_count <= 1:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "A project must always have at least one location."}), 400

    cursor.execute(
        "UPDATE locations SET is_active=0, is_primary=0 WHERE id=%s AND project_id=%s",
        (location_id, project["id"])
    )

    if loc["is_primary"]:
        # Promote the next-oldest active location so the project never ends
        # up with zero primary locations.
        cursor.execute(
            "SELECT id FROM locations WHERE project_id=%s AND is_active=1 ORDER BY sort_order ASC, id ASC LIMIT 1",
            (project["id"],)
        )
        nxt = cursor.fetchone()
        if nxt:
            cursor.execute("UPDATE locations SET is_primary=1 WHERE id=%s", (nxt["id"],))

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/admin/<slug>/modules/request-change", methods=["POST"])
@login_required
def admin_request_module_change(slug):
    payload = request.get_json(silent=True) or {}
    project, conn = _get_owned_project(slug)
    if not project:
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    desired = {key: bool(payload.get(key)) for key in MODULE_COLUMN_MAP}
    error = validate_module_dependencies(desired)
    if error:
        conn.close()
        return jsonify({"success": False, "error": error}), 400

    new_total_cost = compute_module_total_cost(desired)

    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT trial_start, created_at FROM clients WHERE id=%s LIMIT 1",
        (session["client_id"],)
    )
    client_row = cursor.fetchone() or {}
    anchor = client_row.get("trial_start") or client_row.get("created_at")
    from datetime import date as _date
    effective_date = _next_billing_anniversary(anchor.date() if anchor else _date.today())

    ensure_project_module_changes_table(conn)
    cursor.execute(
        "UPDATE project_module_changes SET status='cancelled' WHERE project_id=%s AND status='pending'",
        (project["id"],)
    )
    cursor.execute("""
        INSERT INTO project_module_changes
            (project_id, online_ordering_system, catering_system, booking_reservation_system,
             staff_admin_system, delivery_system, POS_system, new_total_cost, effective_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        project["id"],
        desired["online_ordering_system"], desired["catering_system"], desired["booking_reservation_system"],
        desired["staff_admin_system"], desired["delivery_system"], desired["pos_system"],
        new_total_cost, effective_date
    ))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "success": True,
        "new_total_cost": new_total_cost,
        "effective_date": effective_date.isoformat(),
    })


@app.route("/admin/<slug>/modules/cancel-pending-change", methods=["POST"])
@login_required
def admin_cancel_pending_module_change(slug):
    project, conn = _get_owned_project(slug)
    if not project:
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    ensure_project_module_changes_table(conn)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE project_module_changes SET status='cancelled' WHERE project_id=%s AND status='pending'",
        (project["id"],)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/admin/<slug>/config/save-hours", methods=["POST"])
@login_required
def save_operating_hours(slug):
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    ensure_ordering_hours_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM projects WHERE slug=%s AND client_id=%s LIMIT 1",
                   (slug, session["client_id"]))
    project = cursor.fetchone()
    if not project:
        cursor.close(); conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    hours_data = data.get("hours") or data
    hours_obj = {day: {
        "open": bool(hours_data.get(day, {}).get("open")),
        "from": hours_data.get(day, {}).get("from") or None,
        "to":   hours_data.get(day, {}).get("to")   or None,
    } for day in HOURS_DAYS}

    hours_json = json.dumps(hours_obj)
    details_read = conn.cursor(dictionary=True)
    details_read.execute("""
        SELECT id, ordering_follows_op
        FROM project_details
        WHERE project_id=%s
        ORDER BY id ASC
    """, (project["id"],))
    detail_rows = details_read.fetchall()
    details_read.close()

    primary_detail_id = detail_rows[0]["id"] if detail_rows else None
    follows_op = bool(detail_rows and detail_rows[0].get("ordering_follows_op"))

    if primary_detail_id is None:
        cursor.execute("""
            INSERT INTO project_details (project_id, operating_hours, online_ordering_hours, ordering_follows_op)
            VALUES (%s, %s, %s, %s)
        """, (
            project["id"],
            hours_json,
            hours_json if follows_op else None,
            1 if follows_op else 0,
        ))
    elif follows_op:
        cursor.execute(
            "UPDATE project_details SET operating_hours=%s, online_ordering_hours=%s WHERE id=%s",
            (hours_json, hours_json, primary_detail_id)
        )
    else:
        cursor.execute(
            "UPDATE project_details SET operating_hours=%s WHERE id=%s",
            (hours_json, primary_detail_id)
        )
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"success": True, "ordering_synced": follows_op})


@app.route("/admin/<slug>/config/save-ordering-hours", methods=["POST"])
@login_required
def save_ordering_hours(slug):
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    ensure_ordering_hours_columns(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM projects WHERE slug=%s AND client_id=%s LIMIT 1",
                   (slug, session["client_id"]))
    project = cursor.fetchone()
    if not project:
        cursor.close(); conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    enabled    = bool(data.get("enabled", True))
    follows_op = data.get("follows_op")  # True = follow op hours, False = custom, None = legacy (unchanged)
    details_read = conn.cursor(dictionary=True)
    details_read.execute("""
        SELECT id, operating_hours
        FROM project_details
        WHERE project_id=%s
        ORDER BY id ASC
    """, (project["id"],))
    detail_rows = details_read.fetchall()
    details_read.close()

    primary_detail_id = detail_rows[0]["id"] if detail_rows else None

    if follows_op is True:
        hours_json = (detail_rows[0] or {}).get("operating_hours") if detail_rows else None
        hours_json = hours_json or json.dumps({
            day: {"open": True, "from": "09:00", "to": "21:00"} for day in HOURS_DAYS
        })
        if primary_detail_id is None:
            cursor.execute("""
                INSERT INTO project_details (project_id, operating_hours, online_ordering_hours, online_ordering_enabled, ordering_follows_op)
                VALUES (%s, %s, %s, %s, 1)
            """, (project["id"], hours_json, hours_json, 1 if enabled else 0))
        else:
            cursor.execute(
                "UPDATE project_details SET online_ordering_hours=%s, online_ordering_enabled=%s, ordering_follows_op=1 WHERE id=%s",
                (hours_json, 1 if enabled else 0, primary_detail_id)
            )
    else:
        hours_obj = {day: {
            "open": bool(data.get("hours", {}).get(day, {}).get("open")),
            "from": data.get("hours", {}).get(day, {}).get("from") or None,
            "to":   data.get("hours", {}).get(day, {}).get("to")   or None,
        } for day in HOURS_DAYS}
        hours_json = json.dumps(hours_obj)
        if follows_op is False:
            if primary_detail_id is None:
                cursor.execute("""
                    INSERT INTO project_details (project_id, online_ordering_hours, online_ordering_enabled, ordering_follows_op)
                    VALUES (%s, %s, %s, 0)
                """, (project["id"], hours_json, 1 if enabled else 0))
            else:
                cursor.execute(
                    "UPDATE project_details SET online_ordering_hours=%s, online_ordering_enabled=%s, ordering_follows_op=0 WHERE id=%s",
                    (hours_json, 1 if enabled else 0, primary_detail_id)
                )
        else:
            if primary_detail_id is None:
                cursor.execute("""
                    INSERT INTO project_details (project_id, online_ordering_hours, online_ordering_enabled)
                    VALUES (%s, %s, %s)
                """, (project["id"], hours_json, 1 if enabled else 0))
            else:
                cursor.execute(
                    "UPDATE project_details SET online_ordering_hours=%s, online_ordering_enabled=%s WHERE id=%s",
                    (hours_json, 1 if enabled else 0, primary_detail_id)
                )
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"success": True})


@app.route("/delete_project/<slug>", methods=["POST"])
@login_required
def delete_project(slug):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch the project first to confirm ownership and get the name
    cursor.execute("""
        SELECT id, project_name, client_id FROM projects
        WHERE slug = %s AND client_id = %s
        LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Project not found"}), 404

    ensure_deleted_projects_table(conn)

    # Archive the slug permanently so it can never be reused
    archive_cursor = conn.cursor()
    archive_cursor.execute("""
        INSERT IGNORE INTO deleted_projects (slug, project_name, client_id)
        VALUES (%s, %s, %s)
    """, (slug, project["project_name"], project["client_id"]))

    # Hard delete from projects
    archive_cursor.execute("""
        DELETE FROM projects WHERE slug = %s AND client_id = %s
    """, (slug, session["client_id"]))

    conn.commit()
    archive_cursor.close()
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
    ("our_story", "About", None),
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

def build_upcoming_section_html(events):
    if not events:
        return ""
    parts = []
    for ev in events:
        dt_str = ""
        if ev.get("event_datetime"):
            try:
                dt_str = ev["event_datetime"].strftime("%-d %B %Y at %-I:%M %p")
            except Exception:
                dt_str = str(ev["event_datetime"])
        desc_html = f'<p class="upcoming-desc">{escape(ev["description"])}</p>' if ev.get("description") else ""
        date_html = f'<p class="upcoming-date">{escape(dt_str)}</p>' if dt_str else ""
        parts.append(f"""
    <div class="upcoming-event">
      <h3 class="upcoming-title">{escape(ev["title"])}</h3>
      {date_html}
      {desc_html}
    </div>""")
    events_html = "\n".join(parts)
    return f"""
<section class="upcoming-section">
  <div class="container upcoming-inner">
    <p class="upcoming-kicker">Upcoming</p>
    {events_html}
  </div>
</section>"""


def build_upcoming_notice_html(events):
    if not events:
        return ""
    ev = events[0]
    dt_str = ""
    if ev.get("event_datetime"):
        try:
            dt_str = ev["event_datetime"].strftime("%-d %B %Y")
        except Exception:
            dt_str = str(ev["event_datetime"])
    date_part = f" &mdash; {escape(dt_str)}" if dt_str else ""
    return f"""
<div class="upcoming-menu-notice">
  <span class="upcoming-menu-notice-icon">&#128197;</span>
  <strong>{escape(ev["title"])}</strong>{date_part}
</div>"""


def build_page_context(modules):
    pay_in_store_enabled = (
        get_project_pay_in_store(g.project["id"])
        if hasattr(g, "project")
        else False
    )
    pay_in_store_section = """
      <div class="checkout-divider">
        <span>or</span>
      </div>

      <button class="btn btn-secondary order-btn" onclick="goToInstoreCheckout()">
        Pay-in-store
      </button>
    """ if pay_in_store_enabled else ""

    upcoming_events = []
    disable_ordering = False
    force_ordering_enabled = False
    if hasattr(g, "project"):
        upcoming_events = get_upcoming_events(g.project["id"])
        disable_ordering = any(e.get("disable_online_ordering") for e in upcoming_events)
        if not disable_ordering:
            try:
                _ov_conn = get_db_connection()
                ensure_service_override_columns(_ov_conn)
                _ov_cur = _ov_conn.cursor(dictionary=True)
                _ov_cur.execute(
                    "SELECT ordering_temp_disabled_until, ordering_temp_enabled_until FROM project_details WHERE project_id=%s LIMIT 1",
                    (g.project["id"],)
                )
                _ov_row = _ov_cur.fetchone() or {}
                _ov_cur.close()
                _ov_conn.close()
                _now = datetime.now()
                _disabled_until = _ov_row.get("ordering_temp_disabled_until")
                _enabled_until = _ov_row.get("ordering_temp_enabled_until")
                if _disabled_until and _disabled_until > _now:
                    disable_ordering = True
                elif _enabled_until and _enabled_until > _now:
                    disable_ordering = False
                    force_ordering_enabled = True
            except Exception:
                pass

    ctx = {
        "NAVBAR": build_navbar(modules),

        "ORDER_CTA": "",
        "CART_ICON": "",
        "CART_SIDEBAR": "",

        "FEATURED_SECTION": load_html("sections/featured.html"),
        "MAP_SECTION": load_html("sections/map.html"),
        "CATERING_TEASER": "",
        "RESERVATIONS_TEASER": "",
        "UPCOMING_SECTION": Markup(build_upcoming_section_html(upcoming_events)),
        "UPCOMING_NOTICE": Markup(build_upcoming_notice_html(upcoming_events)),
        # SCRIPTS will be rendered below with module-specific script tags
        "SCRIPTS": "",
    }

    if modules.get("online_ordering_system"):
        ctx["ORDER_CTA"] = load_html("layout/ordering_cta.html").replace("{{MENU_LINK}}", "/menu")
        if disable_ordering:
            closed_notice = '<p class="ordering-closed-notice">&#128683; Online ordering is currently unavailable.</p>'
            ctx["CART_ICON"] = load_html("layout/cart_icon.html").replace(
                '<button class="btn btn-primary order-btn" onclick="checkout()">\n        Checkout\n      </button>',
                closed_notice
            ).replace("<!-- PAY_IN_STORE_SECTION -->", "")
            ctx["CART_SIDEBAR"] = load_html("layout/cart_sidebar.html").replace(
                '<button class="btn btn-primary order-btn" onclick="checkout()">\n        Checkout\n      </button>',
                closed_notice
            ).replace("<!-- PAY_IN_STORE_SECTION -->", "")
        else:
            ctx["CART_ICON"] = load_html("layout/cart_icon.html").replace("<!-- PAY_IN_STORE_SECTION -->", pay_in_store_section)
            ctx["CART_SIDEBAR"] = load_html("layout/cart_sidebar.html").replace("<!-- PAY_IN_STORE_SECTION -->", pay_in_store_section)
        ctx["ORDERING_ENABLED"] = modules.get("online_ordering_system")
        ctx["PAY_IN_STORE_ENABLED"] = pay_in_store_enabled
        ctx["ORDERING_DISABLED"] = disable_ordering

    # Menu data should always load; ordering extras stay conditional.
    ordering_flag_script = ""
    if modules.get("online_ordering_system"):
        _online_ordering_enabled = True
        _ord_hours_data = {}
        if hasattr(g, "project"):
            try:
                _conn = get_db_connection()
                ensure_ordering_hours_columns(_conn)
                _cur = _conn.cursor(dictionary=True)
                _cur.execute(
                    "SELECT online_ordering_hours, online_ordering_enabled FROM project_details WHERE project_id=%s LIMIT 1",
                    (g.project["id"],)
                )
                _row = _cur.fetchone() or {}
                _cur.close()
                _conn.close()
                _online_ordering_enabled = bool(_row.get("online_ordering_enabled", 1))
                _s = _row.get("online_ordering_hours") or ""
                _ord_hours_data = json.loads(_s) if _s and _s.strip().startswith("{") else {}
            except Exception:
                pass
        ordering_enabled_js = "true" if _online_ordering_enabled else "false"
        ord_hours_json = json.dumps(_ord_hours_data)
        ordering_disabled_js = "true" if disable_ordering else "false"
        ordering_force_js = "true" if force_ordering_enabled else "false"
        ordering_flag_script = (
            "<script>"
            f"window.ORDERING_ENABLED={ordering_enabled_js};"
            f"window.ORDERING_DISABLED={ordering_disabled_js};"
            f"window.ORDERING_FORCE_ENABLED={ordering_force_js};"
            f"window.ORDERING_HOURS={ord_hours_json};"
            "</script>"
        )

    ordering_scripts = f'{ordering_flag_script}<script src="{url_for("client_static", filename="js/menu.js")}"></script>'

    if modules.get("online_ordering_system"):
        ordering_scripts = (
            f'{ordering_flag_script}<script src="{url_for("client_static", filename="js/cart.js")}"></script>'
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

    if disable_ordering and modules.get("online_ordering_system"):
        ctx["SCRIPTS"] = Markup(
            str(ctx["SCRIPTS"]) +
            """
            <script>
            document.querySelectorAll('.order-btn').forEach((btn) => {
                btn.disabled = true;
                btn.style.opacity = '0.45';
                btn.style.cursor = 'not-allowed';
                btn.setAttribute('aria-disabled', 'true');
                btn.setAttribute('title', 'Online ordering is currently closed. Please come back during ordering hours.');
            });
            </script>
            """
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


@app.route("/table/<int:table_id>")
def table_order(table_id):
    if not hasattr(g, "project"):
        return "Project not found", 404
    modules = g.modules
    project_id = g.project["id"]

    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, table_number, capacity FROM restaurant_tables "
        "WHERE id=%s AND project_id=%s AND is_active=1 LIMIT 1",
        (table_id, project_id)
    )
    table_row = cursor.fetchone()

    if not table_row:
        cursor.close()
        conn.close()
        return redirect(url_for("menu"))

    # Check whether online payment is enabled for table orders
    cursor.execute(
        "SELECT table_order_online_payment FROM table_booking_config WHERE project_id=%s LIMIT 1",
        (project_id,)
    )
    cfg_row = cursor.fetchone() or {}
    table_order_payment_on = bool(cfg_row.get("table_order_online_payment", 0))

    # Check Stripe connection
    cursor.execute(
        "SELECT stripe_account_id, stripe_enabled FROM projects WHERE id=%s LIMIT 1",
        (project_id,)
    )
    proj_row = cursor.fetchone() or {}
    stripe_ready = bool(
        proj_row.get("stripe_enabled") and
        proj_row.get("stripe_account_id") and
        stripe.api_key
    )

    cursor.close()
    conn.close()

    table_label = (table_row.get("table_number") or f"T{table_id}").strip()
    # Payment mode: 'stripe' only if both settings agree; otherwise 'instore'
    payment_mode = "stripe" if (table_order_payment_on and stripe_ready) else "instore"

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules),
        "table_id": table_id,
        "table_label": table_label,
        "table_capacity": table_row.get("capacity", 2),
        "table_payment_mode": payment_mode,
    }

    return render_template("table_order.html", **ctx)


@app.route("/table/<int:table_id>/payment-success")
def table_order_payment_success(table_id):
    """Stripe returns here after a successful table order payment.
    Verifies the session, marks the order paid, sends notifications,
    then re-renders the table order page in a 'paid' success state."""
    if not hasattr(g, "project"):
        return "Project not found", 404

    modules    = g.modules
    project_id = g.project["id"]
    session_id = request.args.get("session_id", "").strip()
    order_number = request.args.get("order_number", "").strip()

    # Fetch table info (needed for page context)
    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, table_number, capacity FROM restaurant_tables "
        "WHERE id=%s AND project_id=%s AND is_active=1 LIMIT 1",
        (table_id, project_id)
    )
    table_row = cursor.fetchone()
    if not table_row:
        cursor.close(); conn.close()
        return redirect(url_for("menu"))

    table_label = (table_row.get("table_number") or f"T{table_id}").strip()

    paid_order      = None
    payment_verified = False
    notifications_sent = False

    # Verify with Stripe and mark order paid
    if session_id:
        # Check if already confirmed (idempotent — page may be reloaded)
        cursor.execute(
            "SELECT * FROM orders WHERE order_number=%s AND project_id=%s LIMIT 1",
            (order_number, project_id)
        )
        existing = cursor.fetchone()

        if existing and existing.get("payment_status") == "paid":
            paid_order       = existing
            payment_verified = True
        else:
            try:
                cs = stripe.checkout.Session.retrieve(session_id)
                if cs.payment_status == "paid":
                    on = (cs.metadata or {}).get("order_number", "") or order_number
                    pi = cs.payment_intent or ""
                    cursor.execute(
                        "UPDATE orders SET payment_status='paid', payment_method='stripe', "
                        "payment_intent_id=%s WHERE order_number=%s AND project_id=%s",
                        (pi, on, project_id)
                    )
                    conn.commit()
                    # Re-fetch full order row for notifications
                    cursor.execute(
                        "SELECT * FROM orders WHERE order_number=%s AND project_id=%s LIMIT 1",
                        (on, project_id)
                    )
                    paid_order       = cursor.fetchone()
                    payment_verified = True
                    order_number     = on
            except Exception as exc:
                logging.error("[TABLE_PAY_SUCCESS] Stripe verify failed: %s", exc)

    cursor.close(); conn.close()

    # Send kitchen + customer notifications (once, after payment confirmed)
    if payment_verified and paid_order and not notifications_sent:
        import json as _json
        try:
            items_raw = paid_order.get("items") or "[]"
            items = _json.loads(items_raw) if isinstance(items_raw, str) else items_raw
        except Exception:
            items = []

        order_payload = {
            "order_number":   paid_order.get("order_number", order_number),
            "validated_items": items,
            "total":          float(paid_order.get("total") or 0),
            "name":           paid_order.get("name") or "",
            "surname":        paid_order.get("surname") or "",
            "phone":          paid_order.get("phone") or "",
            "email":          paid_order.get("email") or "",
            "note":           paid_order.get("note") or "",
            "payment_method": "stripe",
            "is_delivery":    0,
            "table_number":   paid_order.get("table_number") or table_label,
            "table_session_id": paid_order.get("table_session_id") or "",
        }
        try:
            send_order_notification(g.project, order_payload)
            send_customer_order_confirmation(g.project, order_payload)
        except Exception as exc:
            logging.error("[TABLE_PAY_SUCCESS] Notification send failed: %s", exc)

    table_session_id = (paid_order or {}).get("table_session_id") or ""

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules),
        "table_id":          table_id,
        "table_label":       table_label,
        "table_capacity":    table_row.get("capacity", 2),
        "table_payment_mode": "stripe",
        # These tell the template to auto-show the done overlay
        "stripe_paid":         payment_verified,
        "paid_order_number":   order_number,
        "paid_table_session_id": table_session_id,
    }
    return render_template("table_order.html", **ctx)


@app.route("/api/table-live/<int:table_id>")
def table_live_orders(table_id):
    """Returns all active orders for this table's current session (last 4 hours).
    Used for the live table view on the ordering page."""
    if not hasattr(g, "project"):
        return jsonify({"session_id": None, "orders": [], "table_total": 0, "order_count": 0})

    project_id = g.project["id"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT table_number FROM restaurant_tables "
        "WHERE id=%s AND project_id=%s AND is_active=1 LIMIT 1",
        (table_id, project_id)
    )
    table_row = cursor.fetchone()
    if not table_row:
        cursor.close(); conn.close()
        return jsonify({"session_id": None, "orders": [], "table_total": 0, "order_count": 0})

    table_number = (table_row.get("table_number") or f"T{table_id}").strip()

    # Find the most recent active session in the last 4 hours
    cursor.execute("""
        SELECT table_session_id, MAX(created_at) AS last_at
        FROM orders
        WHERE project_id=%s
          AND table_number=%s
          AND table_session_id IS NOT NULL
          AND table_session_id != ''
          AND status != 'checkout_pending'
          AND created_at >= NOW() - INTERVAL 4 HOUR
        GROUP BY table_session_id
        ORDER BY last_at DESC
        LIMIT 1
    """, (project_id, table_number))
    session_row = cursor.fetchone()

    if not session_row or not session_row.get("table_session_id"):
        cursor.close(); conn.close()
        return jsonify({"session_id": None, "orders": [], "table_total": 0, "order_count": 0})

    session_id = session_row["table_session_id"]

    # Fetch all non-pending orders in this session
    cursor.execute("""
        SELECT order_number, name, items, total, payment_method, payment_status, status, created_at
        FROM orders
        WHERE project_id=%s
          AND table_session_id=%s
          AND status != 'checkout_pending'
        ORDER BY created_at ASC
    """, (project_id, session_id))
    rows = cursor.fetchall()
    cursor.close(); conn.close()

    import json as _json
    result = []
    total_sum = 0.0
    for o in rows:
        items_raw = o.get("items") or "[]"
        try:
            items = _json.loads(items_raw) if isinstance(items_raw, str) else items_raw
        except Exception:
            items = []
        t = float(o.get("total") or 0)
        total_sum += t
        result.append({
            "order_number":   str(o.get("order_number") or ""),
            "name":           o.get("name") or "Guest",
            "items":          items,
            "total":          t,
            "payment_method": o.get("payment_method") or "",
            "payment_status": o.get("payment_status") or "",
            "status":         o.get("status") or "",
        })

    return jsonify({
        "session_id":  session_id,
        "orders":      result,
        "table_total": round(total_sum, 2),
        "order_count": len(result),
    })


@app.route("/our-story")
def our_story():
    if not hasattr(g, "project"):
        return "Project not found", 404
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

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

    return render_template("client_about.html", **ctx)


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
        name = (request.form.get("name") or "")[:255]
        contact_info = (request.form.get("email") or "")[:255]
        message = (request.form.get("message") or "")[:5000]
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

        restaurant_name = g.project.get("project_name")
        rows = (
            _row("Name", name) +
            _row("Email", contact_info) +
            _row("Message", message)
        )
        send_email(
            to=client_email,
            subject=f"New Enquiry — {restaurant_name}",
            html_body=build_client_notification_email("contact", name, restaurant_name, rows),
            sender=DEFAULT_INFO_EMAIL
        )
        if contact_info:
            send_email(
                to=contact_info,
                subject=f"We received your message — {restaurant_name}",
                html_body=build_customer_confirmation_email("contact", name, restaurant_name, rows),
                sender=DEFAULT_INFO_EMAIL,
                reply_to=client_email
            )
        ctx["success"] = True

    return render_template("contact.html", **ctx)



@app.route('/catering', methods=['GET', 'POST'])
@require_module("catering_system")
def catering():
    if not hasattr(g, "project"):
        return "Project not found", 404    
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    if request.method == "POST":
        name = (request.form.get("name") or "")[:255]
        phone = (request.form.get("phone") or "")[:50]
        email = (request.form.get("email") or "")[:255]
        event_date = (request.form.get("event_date") or "")[:50]
        guests = (request.form.get("guests") or "")[:50]
        event_type = (request.form.get("event_type") or "")[:255]
        details = (request.form.get("details") or "")[:5000]
        client_email = get_project_client_email(g.project["id"])

        conn = get_db_connection()
        ensure_location_id_column(conn, "catering_inquiries")
        location_id = resolve_active_location_id(g.project["id"], request.form.get("location_id"))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO catering_inquiries
            (project_id, location_id, name, phone, email, event_date, guests, event_type, details)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (g.project["id"], location_id, name, phone, email, event_date, guests, event_type, details))

        conn.commit()
        cursor.close()
        conn.close()

        restaurant_name = g.project.get("project_name")
        rows = (
            _row("Name", name) +
            _row("Phone", phone) +
            _row("Email", email) +
            _row("Event Date", event_date) +
            _row("Guests", guests) +
            _row("Event Type", event_type) +
            _row("Details", details)
        )
        send_email(
            to=client_email,
            subject=f"New Catering Request — {restaurant_name}",
            html_body=build_client_notification_email("catering", name, restaurant_name, rows),
            sender=DEFAULT_INFO_EMAIL
        )
        if email:
            send_email(
                to=email,
                subject=f"We received your catering request — {restaurant_name}",
                html_body=build_customer_confirmation_email("catering", name, restaurant_name, rows),
                sender=DEFAULT_INFO_EMAIL,
                reply_to=client_email
            )

        ctx["success"] = True

    return render_template("catering.html", **ctx)


@app.route('/reservations', methods=['GET', 'POST'])
@require_module("booking_reservation_system")
def reservations():
    if not hasattr(g, "project"):
        return "Project not found", 404    
    modules = g.modules

    ctx = {
        **build_page_context(modules),
        **build_global_context(modules)
    }

    if request.method == "POST":
        name = (request.form.get("name") or "")[:255]
        email = (request.form.get("email") or "")[:255]
        phone = (request.form.get("phone") or "")[:50]
        reservation_date = (request.form.get("reservation_date") or "")[:50]
        reservation_time = (request.form.get("reservation_time") or "")[:50]
        guests = (request.form.get("guests") or "")[:50]
        special_requests = (request.form.get("special_requests") or "")[:2000]
        client_email = get_project_client_email(g.project["id"])

        conn = get_db_connection()
        ensure_location_id_column(conn, "reservations")
        location_id = resolve_active_location_id(g.project["id"], request.form.get("location_id"))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO reservations
            (project_id, location_id, name, email, phone, reservation_date, reservation_time, guests, special_requests)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (g.project["id"], location_id, name, email, phone, reservation_date, reservation_time, guests, special_requests))

        conn.commit()
        cursor.close()
        conn.close()

        restaurant_name = g.project.get("project_name")
        rows = (
            _row("Name", name) +
            _row("Email", email) +
            _row("Phone", phone) +
            _row("Date", reservation_date) +
            _row("Time", reservation_time) +
            _row("Guests", guests) +
            _row("Special Requests", special_requests)
        )
        send_email(
            to=client_email,
            subject=f"New Reservation Request — {restaurant_name}",
            html_body=build_client_notification_email("reservation", name, restaurant_name, rows),
            sender=DEFAULT_INFO_EMAIL
        )
        if email:
            send_email(
                to=email,
                subject=f"We received your reservation request — {restaurant_name}",
                html_body=build_customer_confirmation_email("reservation", name, restaurant_name, rows),
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
    ensure_delivery_settings_columns(conn)
    ensure_stripe_project_columns(conn)
    ensure_ordering_hours_columns(conn)
    cursor = conn.cursor(dictionary=True)

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
        SELECT address, phone, slogan, contact_email, operating_hours, image, hero_image, hero_image_path,
               delivery_pay_online, delivery_pay_on_delivery,
               online_ordering_hours, online_ordering_enabled
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (g.project["id"],))
    details = cursor.fetchone() or {}

    address = details.get("address", "")
    phone = details.get("phone", "")

    # --- LOCATIONS ---
    # Single-location projects: address/phone stay exactly as they are today
    # (project_details), no picker markup. Multi-location: the picker/pill
    # renders and the *selected* location's own address/phone take over.
    location_picker_html = ""
    active_location_id = None
    if getattr(g, "multi_location", False):
        active_location_id = resolve_active_location_id(g.project["id"])
        active_location = next(
            (l for l in g.locations if l["id"] == active_location_id),
            g.locations[0] if g.locations else None
        )
        if active_location:
            address = active_location.get("address") or address
            phone = active_location.get("phone") or phone
            location_picker_html = render_template_string(
                load_html("sections/location_picker.html"),
                LOCATIONS=g.locations,
                ACTIVE_LOCATION_ID=active_location["id"],
                ACTIVE_LOCATION_NAME=active_location.get("name") or "Select location",
                PROJECT_NAME=g.project.get("project_name") or "us",
            )

    # --- STRIPE ---
    cursor.execute(
        "SELECT stripe_account_id, stripe_enabled FROM projects WHERE id=%s LIMIT 1",
        (g.project["id"],)
    )
    stripe_row = cursor.fetchone() or {}
    stripe_enabled  = bool(stripe_row.get("stripe_enabled"))
    stripe_pub_key  = STRIPE_PUBLISHABLE_KEY if stripe_enabled else ""

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

        "theme_css_file": theme_css_file,

        # project
        "project_name": g.project.get("project_name"),
        "slogan": details.get("slogan"),

        # contact
        "address": address,
        "phone": phone,
        "CONTACT_EMAIL": details.get("contact_email"),

        # locations
        "LOCATION_PICKER": location_picker_html,
        "MULTI_LOCATION": getattr(g, "multi_location", False),
        "ACTIVE_LOCATION_ID": active_location_id,
        "operating_hours": details.get("operating_hours", ""),
        "op_hours": (lambda s: {day: {"open": bool((entry or {}).get("open")), "from": format_display_time((entry or {}).get("from")), "to": format_display_time((entry or {}).get("to"))} for day, entry in json.loads(s).items()} if s and s.strip().startswith("{") else None)(details.get("operating_hours", "")),
        "online_ordering_enabled": bool(details.get("online_ordering_enabled", 1)),
        "online_ordering_hours_json": details.get("online_ordering_hours") or "",
        "ord_hours_context": (lambda s: json.loads(s) if s and s.strip().startswith("{") else {})(details.get("online_ordering_hours") or ""),

        # modules
        "MODULES": modules,

        "PROJECT_SLUG": g.project["slug"],

        # delivery payment flags
        "delivery_pay_online":      db_flag(details.get("delivery_pay_online"),      default=1),
        "delivery_pay_on_delivery": db_flag(details.get("delivery_pay_on_delivery"), default=1),

        # stripe
        "stripe_enabled":        stripe_enabled,
        "stripe_publishable_key": stripe_pub_key,

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



# ── Bulk upload async state ──────────────────────────────────────────────────
# job_id → {"status": "processing"|"done"|"error", ...result fields}
_bulk_upload_jobs: dict[str, dict] = {}
_bulk_upload_jobs_lock = threading.Lock()

# ── Hero image regen async state (file-based so all gunicorn workers can read) ─
# Each job writes BASE_DIR/.regen_jobs/<job_id>.json  so that any worker can
# answer status polls regardless of which worker started the background thread.

_REGEN_JOB_DIR = os.path.join(BASE_DIR, ".regen_jobs")


def _write_regen_job(job_id: str, data: dict) -> None:
    os.makedirs(_REGEN_JOB_DIR, exist_ok=True)
    path = os.path.join(_REGEN_JOB_DIR, f"{job_id}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _read_regen_job(job_id: str) -> dict | None:
    path = os.path.join(_REGEN_JOB_DIR, f"{job_id}.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _delete_regen_job(job_id: str) -> None:
    path = os.path.join(_REGEN_JOB_DIR, f"{job_id}.json")
    try:
        os.remove(path)
    except Exception:
        pass


def _run_hero_regen_background(
    job_id: str,
    project_id: int,
    project_name: str,
    description: str,
    history: list,
    current_image: str,
    revision_comment: str,
    theme: dict,
    attempts_used: int,
) -> None:
    try:
        reference_image_bytes, reference_image_mime = load_local_hero_reference(current_image)
        reference_image_summary = summarize_reference_hero_image(
            reference_image_bytes,
            reference_image_mime,
            project_name,
            revision_comment,
        )
        new_image = generate_hero_image(
            description,
            project_name,
            project_id,
            primary_color=theme.get("primary_color"),
            secondary_color=theme.get("secondary_color"),
            background_color=theme.get("background_color"),
            revision_comment=revision_comment,
            reference_image_summary=reference_image_summary,
        )

        if not new_image:
            _write_regen_job(job_id, {
                "status": "error",
                "error": "Hero image generation failed.",
                "attempts_remaining": max(HERO_IMAGE_REGEN_LIMIT - attempts_used, 0),
            })
            return

        new_attempts = attempts_used + 1
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE project_details
                SET hero_image_path=%s, hero_image=NULL,
                    hero_image_regen_attempts=%s, hero_image_history=%s
                WHERE project_id=%s
            """, (new_image, new_attempts, serialize_hero_image_history(history), project_id))
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO project_details
                        (project_id, hero_image_path, hero_image, hero_image_regen_attempts, hero_image_history)
                    VALUES (%s, %s, NULL, %s, %s)
                """, (project_id, new_image, new_attempts, serialize_hero_image_history(history)))
            conn.commit()
        except Exception as exc:
            logging.exception("[REGEN] DB update failed for project_id=%s job=%s: %s", project_id, job_id, exc)
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

        _write_regen_job(job_id, {
            "status": "done",
            "attempts_remaining": max(HERO_IMAGE_REGEN_LIMIT - new_attempts, 0),
        })
    except Exception as exc:
        logging.exception("[REGEN] Background hero regen failed for project_id=%s job=%s: %s", project_id, job_id, exc)
        _write_regen_job(job_id, {
            "status": "error",
            "error": "Hero image generation failed. Please try again.",
            "attempts_remaining": max(HERO_IMAGE_REGEN_LIMIT - attempts_used, 0),
        })


def _run_bulk_upload_background(job_id: str, project: dict,
                                 file_bytes: bytes, extension: str,
                                 attempts: int, attempt_limit: int) -> None:
    try:
        extracted = extract_bulk_products_with_ai(project["project_name"], file_bytes, extension)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            inserted_count, category_count = insert_bulk_products(cursor, project["id"], extracted)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        with _bulk_upload_jobs_lock:
            _bulk_upload_jobs[job_id] = {
                "status": "done",
                "inserted_products": inserted_count,
                "touched_categories": category_count,
                "attempts_used": attempts,
                "attempts_remaining": max(attempt_limit - attempts, 0),
                "disabled": attempts >= attempt_limit,
            }
    except Exception as exc:
        logging.exception("Background bulk upload failed for job %s", job_id)
        with _bulk_upload_jobs_lock:
            _bulk_upload_jobs[job_id] = {
                "status": "error",
                "error": str(exc) or "Extraction or import failed.",
                "attempts_used": attempts,
                "attempts_remaining": max(attempt_limit - attempts, 0),
                "disabled": attempts >= attempt_limit,
            }


_deploy_errors: dict[int, str] = {}
_deploy_stages: dict[int, str] = {}  # project_id → "assets" | "menu_import"
_deploy_has_menu: dict[int, bool] = {}  # project_id → True if initial menu file exists


def _run_deploy_background(project_id: int, project: dict) -> None:
    conn = None
    cursor = None
    slug = project.get("slug", str(project_id))
    print(f"[DEPLOY] Starting deploy for project '{slug}' (id={project_id})")
    logging.info("[DEPLOY] Starting deploy for project '%s' (id=%s)", slug, project_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check for initial menu file before running assets (to set has_menu flag)
        cursor.execute(
            "SELECT initial_menu_path FROM project_details WHERE project_id=%s LIMIT 1",
            (project_id,)
        )
        det = cursor.fetchone() or {}
        initial_menu_path = (det.get("initial_menu_path") or "").strip()
        file_exists = bool(initial_menu_path and os.path.isfile(initial_menu_path))
        _deploy_has_menu[project_id] = file_exists
        print(f"[DEPLOY] initial_menu_path='{initial_menu_path}' | file_exists={file_exists}")
        logging.info("[DEPLOY] initial_menu_path='%s' | file_exists=%s", initial_menu_path, file_exists)

        _deploy_stages[project_id] = "assets"
        finalize_project_assets(project, conn, cursor)
        try:
            generate_project_qr_assets(project, conn, cursor)
        except Exception:
            logging.exception("[DEPLOY] QR asset generation failed for project '%s'; continuing deploy", slug)
        conn.commit()
        print(f"[DEPLOY] Assets finalized and committed for project '{slug}'")

        if _deploy_has_menu.get(project_id):
            _deploy_stages[project_id] = "menu_import"
            try:
                ext = os.path.splitext(initial_menu_path)[1].lstrip(".").lower() or "jpg"
                print(f"[DEPLOY] Reading menu file '{initial_menu_path}' (ext={ext})")
                with open(initial_menu_path, "rb") as mf:
                    file_bytes = mf.read()
                print(f"[DEPLOY] Menu file read: {len(file_bytes)} bytes — sending to AI for extraction")
                extracted = extract_bulk_products_with_ai(project["project_name"], file_bytes, ext)
                print(f"[DEPLOY] AI extracted {len(extracted)} products from menu")
                inserted_count, category_count = insert_bulk_products(cursor, project_id, extracted)
                conn.commit()
                print(f"[DEPLOY] Menu imported: {inserted_count} products across {category_count} categories saved to project '{slug}'")
                logging.info("[DEPLOY] Menu imported: %d products, %d categories for project '%s'", inserted_count, category_count, slug)
            except Exception:
                logging.exception("[DEPLOY] Initial menu bulk import failed for project '%s'; continuing deploy", slug)
                print(f"[DEPLOY] ERROR: Menu import failed for project '{slug}' — see logs for details")
                try:
                    conn.rollback()
                except Exception:
                    pass
        else:
            print(f"[DEPLOY] No valid menu file found for project '{slug}' — skipping menu import")

        _deploy_stages.pop(project_id, None)
        cursor.execute(
            "UPDATE projects SET is_deployed=TRUE, is_deploying=FALSE WHERE id=%s",
            (project_id,)
        )
        conn.commit()
        _deploy_errors.pop(project_id, None)
        print(f"[DEPLOY] Project '{slug}' marked as deployed successfully")
        logging.info("[DEPLOY] Project '%s' (id=%s) deploy complete", slug, project_id)

        # ── Send deployment notification emails ───────────────────────────
        try:
            slug = project.get("slug", "")
            project_name = project.get("project_name", "")
            site_url = f"https://{slug}.dinebloc.com/"
            email_html = build_deployment_email(project_name, site_url)
            subject = f"{project_name} is now live on Dinebloc!"

            # 1. Account (registered) email
            cursor.execute("""
                SELECT c.email AS account_email
                FROM projects p
                JOIN clients c ON p.client_id = c.id
                WHERE p.id = %s LIMIT 1
            """, (project_id,))
            row = cursor.fetchone()
            account_email = (row or {}).get("account_email", "")

            # 2. Business contact email from project details
            cursor.execute("""
                SELECT contact_email FROM project_details
                WHERE project_id = %s LIMIT 1
            """, (project_id,))
            det = cursor.fetchone()
            contact_email = (det or {}).get("contact_email", "") or ""

            # Deduplicate — only send once if both are the same address
            recipients = []
            if account_email:
                recipients.append(account_email.strip().lower())
            if contact_email and contact_email.strip().lower() not in recipients:
                recipients.append(contact_email.strip().lower())

            for addr in recipients:
                send_email(to=addr, subject=subject, html_body=email_html,
                           sender=DEFAULT_INFO_EMAIL)
        except Exception:
            logging.exception("Deployment email failed for project %s", project_id)
        # ─────────────────────────────────────────────────────────────────

    except Exception as e:
        _deploy_errors[project_id] = str(e)
        print(f"[DEPLOY] ERROR in deploy for project '{slug}' (id={project_id}): {e}")
        logging.exception("[DEPLOY] Unhandled error in deploy for project '%s' (id=%s)", slug, project_id)
        if conn:
            try:
                rc = conn.cursor()
                rc.execute(
                    "UPDATE projects SET is_deploying=FALSE WHERE id=%s",
                    (project_id,)
                )
                conn.commit()
                rc.close()
            except Exception:
                pass
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/deploy_project/<slug>', methods=['POST'])
@login_required
def deploy_project(slug):
    conn = None
    cursor = None
    try:
        data = request.get_json(silent=True) or {}

        if data.get("type") != "subdomain":
            return jsonify({"success": False, "message": "Only subdomains supported"}), 400

        conn = get_db_connection()
        ensure_projects_deployment_column(conn)
        ensure_project_details_featured_column(conn)
        ensure_project_details_hero_image_column(conn)

        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, project_name, slug, is_deployed, is_deploying
            FROM projects WHERE slug=%s AND client_id=%s LIMIT 1
        """, (slug, session["client_id"]))
        project = cursor.fetchone()

        if not project:
            return jsonify({"success": False, "message": "Project not found"}), 404

        if is_project_live(project):
            return jsonify({"success": False, "message": "This project is already deployed."}), 409

        if is_project_deploying(project):
            return jsonify({"success": True, "status": "deploying"}), 202

        _deploy_errors.pop(project["id"], None)
        cursor.execute("UPDATE projects SET is_deploying=TRUE WHERE id=%s", (project["id"],))
        conn.commit()

        threading.Thread(
            target=_run_deploy_background,
            args=(project["id"], dict(project)),
            daemon=True
        ).start()

        return jsonify({"success": True, "status": "deploying"}), 202

    except Exception as e:
        print("DEPLOY ERROR:", str(e))
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/deploy_status/<slug>', methods=['GET'])
@login_required
def deploy_status(slug):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, is_deployed, is_deploying
        FROM projects WHERE slug=%s AND client_id=%s LIMIT 1
    """, (slug, session["client_id"]))
    project = cursor.fetchone()
    cursor.close()
    conn.close()

    if not project:
        return jsonify({"success": False}), 404

    error = _deploy_errors.get(project["id"])
    deployed = is_project_deployed(project)
    deploying = is_project_deploying(project)
    return jsonify({
        "success": True,
        "deployed": deployed,
        "deploying": deploying,
        "error": error,
        "stage": _deploy_stages.get(project["id"]),
        "has_menu": _deploy_has_menu.get(project["id"], False),
        "url": f"https://{slug}.dinebloc.com/" if deployed else None
    })



@app.route('/admin/<slug>/create_worker', methods=['POST'])
@login_required
def create_worker(slug):
    project = get_project_for_client(slug)
    if not project:
        return jsonify(success=False), 403

    # generate username (10 chars) — use secrets for cryptographically safe randomness
    _upool = string.ascii_lowercase + string.digits
    username = ''.join(secrets.choice(_upool) for _ in range(10))

    # generate strong password (12 chars)
    _ppool = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(_ppool) for _ in range(12))

    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    ensure_worker_password_column(conn)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO workers (project_id, username, password_hash, password_visible)
        VALUES (%s, %s, %s, %s)
    """, (project["id"], username, password_hash, _fernet_encrypt(password)))

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

    for w in workers:
        if w.get('password_visible'):
            w['password_visible'] = _fernet_decrypt(w['password_visible'])

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

    print(f"[FEATURED] Generating featured section for business='{business_name}'")
    logging.info("[FEATURED] Requesting featured section from OpenAI for business='%s'", business_name)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )

    result = response.choices[0].message.content
    print(f"[FEATURED] Featured section received for '{business_name}': {len(result or '')} chars")
    logging.info("[FEATURED] Featured section generated for '%s': %d chars", business_name, len(result or ""))
    return result


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
    slug = project.get("slug", str(project.get("id", "?")))
    print(f"[ASSETS] finalize_project_assets started for project '{slug}'")
    logging.info("[ASSETS] finalize_project_assets started for project '%s'", slug)

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
    print(f"[ASSETS] description for '{slug}': '{description[:120]}{'...' if len(description) > 120 else ''}'")
    if not description:
        raise ValueError("Add a business description before deploying so we can generate the featured section and hero image.")

    featured_html = sanitize_featured_html(details.get("featured_html"))
    hero_image = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
    generated_featured = False
    generated_hero = False
    theme = get_project_settings(project["id"])

    print(f"[ASSETS] existing featured_html={'yes' if featured_html else 'no'} | existing hero_image={'yes' if hero_image else 'no'}")

    if not featured_html:
        print(f"[ASSETS] Generating featured section for '{slug}' using description")
        try:
            featured_html = sanitize_featured_html(
                generate_featured_section(description, project["project_name"])
            )
        except Exception as feat_err:
            logging.exception("[ASSETS] Featured section generation FAILED for project '%s'", slug)
            print(f"[ASSETS] ERROR: Featured section generation failed for project '{slug}': {feat_err}")
            featured_html = ""
        generated_featured = bool(featured_html)
        print(f"[ASSETS] Featured section generated: {generated_featured} | length={len(featured_html) if featured_html else 0}")

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
            print(f"[ASSETS] Featured section saved to DB for project '{slug}'")
    else:
        print(f"[ASSETS] Using existing featured section for project '{slug}'")

    if not hero_image:
        print(f"[ASSETS] Generating hero image for project '{slug}'")
        print(f"[ASSETS] Image generation text: '{description[:200]}{'...' if len(description) > 200 else ''}'")
        try:
            hero_image = generate_hero_image(
                description,
                project["project_name"],
                project["id"],
                primary_color=theme.get("primary_color"),
                secondary_color=theme.get("secondary_color"),
                background_color=theme.get("background_color"),
            )
            print(f"[ASSETS] Hero image generated and saved: '{hero_image}'")
            logging.info("[ASSETS] Hero image generated for project '%s': %s", slug, hero_image)
        except Exception as img_err:
            logging.exception("[ASSETS] Hero image generation FAILED for project '%s'", slug)
            print(f"[ASSETS] ERROR: Hero image generation failed for project '{slug}': {img_err}")
            hero_image = ""
        generated_hero = bool(hero_image)
    else:
        print(f"[ASSETS] Using existing hero image for project '{slug}': '{hero_image}'")

    if not featured_html:
        featured_html = get_default_featured_section_html()
        print(f"[ASSETS] Using default featured section for project '{slug}'")

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

    print(f"[ASSETS] project_details updated: featured_html={'set' if featured_html else 'empty'}, hero_image_path='{hero_image or 'NULL'}'")
    logging.info("[ASSETS] finalize_project_assets complete for project '%s' — featured=%s, hero_image_ready=%s", slug, generated_featured, bool(hero_image))

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

    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value

    value = value.lstrip("/")
    return value


def save_hero_image_bytes(image_bytes, project_id):
    if not image_bytes:
        print(f"[SAVE_IMAGE] No image bytes to save for project_id={project_id}")
        return ""

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    filename = f"hero_{project_id}_{int(time.time())}.png"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    with open(filepath, "wb") as f:
        f.write(image_bytes)

    print(f"[SAVE_IMAGE] Hero image saved: '{filepath}' ({len(image_bytes)} bytes) for project_id={project_id}")
    logging.info("[SAVE_IMAGE] Hero image saved to '%s' for project_id=%s", filepath, project_id)
    return f"uploads/{filename}"


def save_upload_bytes(file_bytes, filename):
    if not file_bytes:
        return ""

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    safe_name = secure_filename(filename or f"asset_{int(time.time())}")
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)

    with open(filepath, "wb") as f:
        f.write(file_bytes)

    return f"uploads/{safe_name}"


def resolve_uploaded_asset_path(value):
    normalized = str(value or "").strip()
    if not normalized:
        return ""

    if normalized.startswith(("http://", "https://")):
        return normalized

    normalized = normalized.lstrip("/")

    if normalized.startswith("uploads/"):
        return normalized

    return f"uploads/{normalized}"


def resolve_uploaded_asset_url(value):
    normalized = resolve_uploaded_asset_path(value)
    if not normalized:
        return ""

    if normalized.startswith(("http://", "https://", "/")):
        return normalized

    return f"/{normalized}"


def build_mobile_install_url(slug):
    safe_slug = re.sub(r"[^a-z0-9-]", "", (slug or "").strip().lower())
    return f"https://{safe_slug}.dinebloc.com/" if safe_slug else ""


def generate_qr_png_bytes(data):
    payload = (data or "").strip()
    if not payload:
        return b""

    if qrcode is not None and ERROR_CORRECT_M is not None:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=12,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    remote_url = (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size=700x700&format=png&data={quote(payload, safe='')}"
    )
    with urlopen(remote_url, timeout=20) as response:
        return response.read()


def generate_table_qr_card_bytes(menu_url, restaurant_name, table_label):
    """
    Returns PNG bytes of a branded QR card:
      • restaurant name at top
      • QR code in the middle
      • table label below QR
      • small 'Powered by Dinebloc' at bottom
    Falls back to a plain QR if PIL isn't available.
    """
    plain = generate_qr_png_bytes(menu_url)
    if not plain:
        return b""

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return plain

    if qrcode is None:
        return plain

    # --- build QR PIL image ---
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(menu_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1e293b", back_color="white").convert("RGBA")
    qr_size = qr_img.size[0]

    # --- card geometry ---
    card_w    = qr_size + 80
    header_h  = 80   # restaurant name
    gap_top   = 16
    label_h   = 46   # table label below QR
    footer_h  = 32   # Dinebloc
    card_h    = header_h + gap_top + qr_size + label_h + footer_h

    card = Image.new("RGB", (card_w, card_h), (255, 255, 255))
    draw = ImageDraw.Draw(card)

    # --- draw light separator line at bottom of header ---
    draw.line([(30, header_h - 1), (card_w - 30, header_h - 1)], fill="#e2e8f0", width=1)

    # --- try to load a real font, fall back gracefully ---
    _font_paths = [
        "arial.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]

    def _load_font(size, bold=False):
        candidates = _font_paths if bold else [p.replace("Bold", "").replace("-B.", ".") for p in _font_paths] + _font_paths
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    name_font  = _load_font(26, bold=True)
    label_font = _load_font(20, bold=False)
    hint_font  = _load_font(13, bold=False)

    def _text_center(draw_obj, y, text, font, color):
        bbox = draw_obj.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw_obj.text(((card_w - w) / 2, y), text, fill=color, font=font)

    # --- restaurant name ---
    name_text = (restaurant_name or "Restaurant").strip()[:38]
    _text_center(draw, 18, name_text, name_font, "#0f172a")

    # blue underline accent
    draw.rectangle([(card_w // 2 - 45, 52), (card_w // 2 + 45, 54)], fill="#3b82f6")

    # --- QR code ---
    qr_x = (card_w - qr_size) // 2
    qr_y = header_h + gap_top
    card.paste(qr_img.convert("RGB"), (qr_x, qr_y))

    # --- table label ---
    label_y = qr_y + qr_size + 10
    _text_center(draw, label_y, table_label, label_font, "#334155")

    # --- footer ---
    footer_y = card_h - footer_h + 8
    # subtle divider
    draw.line([(30, card_h - footer_h), (card_w - 30, card_h - footer_h)], fill="#f1f5f9", width=1)
    _text_center(draw, footer_y, "Powered by Dinebloc", hint_font, "#cbd5e1")

    buf = BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _json_from_model_text(raw_text):
    cleaned = (raw_text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def generate_qr_poster_copy_with_ai(project_name, site_url, slogan="", description="", address=""):
    fallback = {
        "headline": f"Scan to open {project_name}",
        "subheadline": "Add this restaurant to your phone for faster repeat visits, ordering, and contact details.",
        "reasons": [
            "Open the live menu and homepage in one scan.",
            "Keep the restaurant one tap away from the home screen.",
            "Share a simple mobile entry point with customers at the counter or table.",
        ],
        "instructions": [
            "Scan the QR code with your phone camera.",
            "When the site opens, tap Share or your browser menu.",
            "Choose Add to Home Screen to save it like an app shortcut.",
        ],
        "footer": "Perfect for counters, takeaway bags, tables, and shop windows.",
    }

    prompt = f"""
Create concise marketing copy for a one-page restaurant QR poster.

Return valid JSON only using this exact shape:
{{
  "headline": "short heading",
  "subheadline": "one short sentence",
  "reasons": ["reason 1", "reason 2", "reason 3"],
  "instructions": ["step 1", "step 2", "step 3"],
  "footer": "short footer line"
}}

Rules:
- Keep it polished, premium, and restaurant-friendly.
- Mention convenience, repeat visits, and quick access.
- Do not mention any unsupported technical promise like automatic installation.
- The instructions must explain that the customer scans, opens the site, then uses Add to Home Screen.
- Keep each item under 18 words.

Restaurant name: {project_name}
Restaurant slogan: {slogan}
Restaurant address: {address}
Website URL: {site_url}
Business description: {description}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        parsed = _json_from_model_text(response.choices[0].message.content)
        return {
            "headline": (parsed.get("headline") or fallback["headline"]).strip(),
            "subheadline": (parsed.get("subheadline") or fallback["subheadline"]).strip(),
            "reasons": [str(item).strip() for item in (parsed.get("reasons") or fallback["reasons"])[:3] if str(item).strip()],
            "instructions": [str(item).strip() for item in (parsed.get("instructions") or fallback["instructions"])[:3] if str(item).strip()],
            "footer": (parsed.get("footer") or fallback["footer"]).strip(),
        }
    except Exception:
        logging.exception("[QR] AI poster copy generation failed for %s", project_name)
        return fallback


def _safe_hex(value, default):
    candidate = str(value or "").strip()
    return candidate if re.fullmatch(r"#[0-9a-fA-F]{6}", candidate) else default


def generate_qr_poster_pdf(project, details, theme, qr_image_bytes, install_url, copy):
    if not qr_image_bytes or canvas is None or A4 is None or ImageReader is None or HexColor is None:
        return ""

    page_width, page_height = A4   # 595.27 x 841.89
    cx = page_width / 2
    margin = 40

    # ── DineBloc brand palette (never uses restaurant theme colours) ──
    theme_blue   = _safe_hex((theme or {}).get("primary_color"), "#0B63FF")
    DB_WHITE     = "#FFFFFF"
    DB_SOFT_BG   = "#F8FBFF"
    DB_TEXT      = "#10213F"
    DB_TEXT_SUB  = "#456287"
    DB_LINE      = "#BFD8FF"
    DB_LIGHT     = "#DBEAFE"
    DB_MUTED     = "#93C5FD"
    DB_PALE      = "#BFDBFE"
    DB_PALE_2    = "#EAF3FF"

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    # ── Full-page deep-navy background ────────────────────────────────
    pdf.setFillColor(HexColor(DB_WHITE))
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    # Decorative accent circles — top-right
    for r, col in [(220, DB_PALE_2), (150, DB_LIGHT), (90, theme_blue)]:
        pdf.setFillColor(HexColor(col))
        pdf.circle(page_width - 18, page_height - 18, r, fill=1, stroke=0)

    # Decorative accent circles — bottom-left
    for r, col in [(170, DB_PALE_2), (105, DB_PALE)]:
        pdf.setFillColor(HexColor(col))
        pdf.circle(0, 0, r, fill=1, stroke=0)

    for r, col, x, y in [(56, DB_LIGHT, margin + 8, page_height - 150), (42, DB_PALE, page_width - 90, 160)]:
        pdf.setFillColor(HexColor(col))
        pdf.circle(x, y, r, fill=1, stroke=0)

    # ── Top brand bar ─────────────────────────────────────────────────
    top_bar_h = 68
    pdf.setFillColor(HexColor(DB_SOFT_BG))
    pdf.rect(0, page_height - top_bar_h, page_width, top_bar_h, fill=1, stroke=0)

    # Subtle inner shine line at bottom of bar
    pdf.setStrokeColor(HexColor(DB_LINE))
    pdf.setLineWidth(1)
    pdf.line(0, page_height - top_bar_h, page_width, page_height - top_bar_h)

    pdf.setFillColor(HexColor(theme_blue))
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawCentredString(cx, page_height - top_bar_h + 26, "DINEBLOC")
    pdf.setFillColor(HexColor(DB_TEXT_SUB))
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(cx, page_height - top_bar_h + 11, "Restaurant Web Platform")

    # ── Restaurant name block ─────────────────────────────────────────
    project_name = (project.get("project_name") or "Restaurant").strip()[:38]
    slogan       = (details.get("slogan") or "").strip()
    headline     = (copy.get("headline") or "Scan to visit our site").strip()
    subheadline  = (copy.get("subheadline") or "").strip()

    name_y = page_height - top_bar_h - 54
    pdf.setFillColor(HexColor(DB_TEXT))
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawCentredString(cx, name_y, project_name)

    # Decorative underline
    name_w = pdf.stringWidth(project_name, "Helvetica-Bold", 30)
    underline_half = min(name_w / 2 + 10, 160)
    pdf.setStrokeColor(HexColor(theme_blue))
    pdf.setLineWidth(2.5)
    pdf.line(cx - underline_half, name_y - 8, cx + underline_half, name_y - 8)

    if slogan:
        pdf.setFillColor(HexColor(DB_TEXT_SUB))
        pdf.setFont("Helvetica", 12)
        pdf.drawCentredString(cx, name_y - 30, slogan[:72])

    headline_y = name_y - (52 if slogan else 38)
    pdf.setFillColor(HexColor(DB_TEXT))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(cx, headline_y, headline[:60])

    pdf.setFillColor(HexColor(DB_TEXT_SUB))
    pdf.setFont("Helvetica", 10)
    for i, line in enumerate(wrap(subheadline, 74)[:2]):
        pdf.drawCentredString(cx, headline_y - 18 - (i * 14), line)

    # ── QR code card (centered) ───────────────────────────────────────
    qr_size   = 220
    card_pad  = 22
    card_size = qr_size + card_pad * 2      # 264
    card_x    = (page_width - card_size) / 2
    card_btm  = 316
    qr_x      = card_x + card_pad
    qr_y      = card_btm + card_pad

    # Shadow layers (darker rects behind card)
    for depth, shade in [(10, DB_PALE_2), (6, DB_LIGHT), (3, DB_PALE)]:
        pdf.setFillColor(HexColor(shade))
        pdf.roundRect(
            card_x - depth * 0.4,
            card_btm - depth,
            card_size + depth * 0.8,
            card_size + depth,
            22, fill=1, stroke=0
        )

    # White card
    pdf.setFillColor(HexColor(DB_WHITE))
    pdf.roundRect(card_x, card_btm, card_size, card_size, 20, fill=1, stroke=0)

    # Blue accent border ring
    pdf.setStrokeColor(HexColor(theme_blue))
    pdf.setLineWidth(2.5)
    pdf.roundRect(card_x, card_btm, card_size, card_size, 20, fill=0, stroke=1)

    # QR image
    pdf.drawImage(
        ImageReader(BytesIO(qr_image_bytes)),
        qr_x, qr_y, width=qr_size, height=qr_size, mask="auto"
    )

    # "SCAN ME" label below card
    scan_label_y = card_btm - 24
    pdf.setFillColor(HexColor(theme_blue))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawCentredString(cx, scan_label_y, "* SCAN ME *")

    # ── 3-step instruction row ────────────────────────────────────────
    instructions = copy.get("instructions") or []
    steps_header_y = card_btm - 52

    pdf.setFillColor(HexColor(DB_TEXT_SUB))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(cx, steps_header_y, "HOW TO SAVE IT LIKE AN APP")

    # Hairline dividers either side of header
    label_w = pdf.stringWidth("HOW TO SAVE IT LIKE AN APP", "Helvetica-Bold", 9)
    pdf.setStrokeColor(HexColor(DB_LINE))
    pdf.setLineWidth(0.75)
    pdf.line(margin, steps_header_y + 4, cx - label_w / 2 - 8, steps_header_y + 4)
    pdf.line(cx + label_w / 2 + 8, steps_header_y + 4, page_width - margin, steps_header_y + 4)

    col_w   = (page_width - 2 * margin) / 3
    step_cy = steps_header_y - 28
    for i, step_text in enumerate(instructions[:3]):
        scx = margin + col_w * i + col_w / 2

        # Number bubble
        pdf.setFillColor(HexColor(theme_blue))
        pdf.circle(scx, step_cy, 13, fill=1, stroke=0)
        pdf.setFillColor(HexColor(DB_WHITE))
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawCentredString(scx, step_cy - 4, str(i + 1))

        # Step text
        pdf.setFillColor(HexColor(DB_TEXT_SUB))
        pdf.setFont("Helvetica", 8)
        for j, line in enumerate(wrap(step_text, 24)[:3]):
            pdf.drawCentredString(scx, step_cy - 22 - (j * 11), line)

    # ── URL badge ─────────────────────────────────────────────────────
    url_bar_y  = 78
    url_bar_h  = 40
    url_bar_w  = page_width - 2 * margin
    pdf.setFillColor(HexColor(DB_SOFT_BG))
    pdf.roundRect(margin, url_bar_y, url_bar_w, url_bar_h, 14, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor(theme_blue))
    pdf.setLineWidth(1)
    pdf.roundRect(margin, url_bar_y, url_bar_w, url_bar_h, 14, fill=0, stroke=1)

    pdf.setFillColor(HexColor(theme_blue))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(cx, url_bar_y + url_bar_h - 12, "VISIT US ONLINE")
    pdf.setFillColor(HexColor(DB_TEXT))
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(cx, url_bar_y + 10, (install_url or "")[:80])

    # ── Bottom brand bar ──────────────────────────────────────────────
    btm_h = 56
    pdf.setFillColor(HexColor(DB_SOFT_BG))
    pdf.rect(0, 0, page_width, btm_h, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor(DB_LINE))
    pdf.setLineWidth(1)
    pdf.line(0, btm_h, page_width, btm_h)

    footer_text = (copy.get("footer") or "").strip()
    pdf.setFillColor(HexColor(DB_TEXT))
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(cx, 30, footer_text[:90] if footer_text else "Scan, open, and add to your home screen for one-tap access.")
    pdf.setFillColor(HexColor(DB_TEXT_SUB))
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(cx, 14, "Powered by Dinebloc  |  dinebloc.com")

    pdf.showPage()
    pdf.save()

    filename = f"qr_poster_{project['id']}_{int(time.time())}.pdf"
    return save_upload_bytes(buffer.getvalue(), filename)


def generate_project_qr_assets(project, conn, cursor):
    ensure_project_details_qr_asset_columns(conn)
    cursor.execute("""
        SELECT slogan, address, description, qr_code_path, qr_poster_pdf_path, qr_install_url
        FROM project_details
        WHERE project_id=%s
        LIMIT 1
    """, (project["id"],))
    details = cursor.fetchone() or {}

    theme = get_project_settings(project["id"])
    install_url = build_mobile_install_url(project.get("slug"))
    qr_code_path = resolve_uploaded_asset_path(details.get("qr_code_path"))
    qr_poster_pdf_path = resolve_uploaded_asset_path(details.get("qr_poster_pdf_path"))

    qr_image_bytes = b""
    if qr_code_path:
        qr_filename = qr_code_path.split("uploads/", 1)[1]
        qr_file = os.path.join(app.config["UPLOAD_FOLDER"], qr_filename)
        if os.path.exists(qr_file):
            with open(qr_file, "rb") as f:
                qr_image_bytes = f.read()

    if not qr_image_bytes:
        qr_image_bytes = generate_qr_png_bytes(install_url)
        if qr_image_bytes:
            qr_code_path = save_upload_bytes(
                qr_image_bytes,
                f"qr_code_{project['id']}_{int(time.time())}.png",
            )

    # Always regenerate the PDF so the latest design is used on every deploy.
    # Wrapped so a poster/AI-copy failure can never block saving qr_code_path
    # below — the QR code itself has already been generated above.
    if qr_image_bytes:
        try:
            poster_copy = generate_qr_poster_copy_with_ai(
                project.get("project_name", ""),
                install_url,
                slogan=details.get("slogan") or "",
                description=details.get("description") or "",
                address=details.get("address") or "",
            )
            qr_poster_pdf_path = generate_qr_poster_pdf(
                project,
                details,
                theme,
                qr_image_bytes,
                install_url,
                poster_copy,
            )
        except Exception:
            logging.exception(
                "[QR] Poster PDF generation failed for project '%s'; QR code itself is unaffected",
                project.get("slug")
            )

    if details:
        cursor.execute("""
            UPDATE project_details
            SET qr_code_path=%s, qr_poster_pdf_path=%s, qr_install_url=%s
            WHERE project_id=%s
        """, (qr_code_path or None, qr_poster_pdf_path or None, install_url or None, project["id"]))
    else:
        cursor.execute("""
            INSERT INTO project_details (project_id, qr_code_path, qr_poster_pdf_path, qr_install_url)
            VALUES (%s, %s, %s, %s)
        """, (project["id"], qr_code_path or None, qr_poster_pdf_path or None, install_url or None))

    conn.commit()
    return {
        "qr_code_path": qr_code_path,
        "qr_poster_pdf_path": qr_poster_pdf_path,
        "qr_install_url": install_url,
    }


def get_hero_image_css(hero_image, slug=None):
    image_value = normalize_hero_image_value(hero_image)

    if isinstance(image_value, (bytes, bytearray)):
        if not slug:
            return "none"
        image_url = url_for("project_hero_image", slug=slug)
    else:
        image_url = resolve_uploaded_asset_url(image_value) if image_value else ""

    return f'url("{image_url}")' if image_url else "none"


def load_local_hero_reference(hero_image):
    resolved_path = resolve_hero_image_path(hero_image)
    if not resolved_path or not resolved_path.startswith("uploads/"):
        return b"", ""

    local_path = os.path.join(app.config["UPLOAD_FOLDER"], resolved_path.split("uploads/", 1)[1])
    if not os.path.exists(local_path):
        return b"", ""

    with open(local_path, "rb") as f:
        image_bytes = f.read()

    mime_type = mimetypes.guess_type(local_path)[0] or "image/png"
    return image_bytes, mime_type


def summarize_reference_hero_image(image_bytes, mime_type, project_name, revision_comment):
    if not image_bytes:
        return ""

    try:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are reviewing the current website hero image before regenerating it.\n"
                            f"Business: {project_name}\n"
                            f"Requested change: {revision_comment or 'No specific change requested.'}\n\n"
                            "Summarize the current hero image in 5 short lines with strict focus on:\n"
                            "- subject and scene\n"
                            "- composition and framing\n"
                            "- lighting and mood\n"
                            "- color accents and negative space\n"
                            "- details that should stay consistent unless the requested change requires otherwise\n"
                            "Be concrete and concise. Do not invent text in the image."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url}
                    },
                ],
            }],
            temperature=0.1,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logging.warning("[IMAGE_GEN] Failed to summarize current hero image for '%s': %s", project_name, exc)
        return ""


def generate_hero_image(
    description,
    project_name,
    project_id=0,
    primary_color=None,
    secondary_color=None,
    background_color=None,
    revision_comment="",
    reference_image_summary="",
):
    primary_color = (primary_color or "#2563eb").strip()
    secondary_color = (secondary_color or "#0f172a").strip()
    background_color = (background_color or "#111111").strip()
    revision_comment = (revision_comment or "").strip()
    reference_image_summary = (reference_image_summary or "").strip()
    revision_block = ""

    if revision_comment:
        revision_block = f"""

Requested change from the user:
{revision_comment}

Strict focus instructions:
- STRICTLY focus on the requested change above all other changes
- compare the new image against the current hero image and make the requested difference intentional and visible
- preserve business relevance and homepage usability unless the requested change requires a different direction
- avoid unrelated changes or random stylistic drift
"""
        if reference_image_summary:
            revision_block += f"""

Current hero image summary:
{reference_image_summary}
"""

    prompt = f"""
A realistic website hero image for a business website.

Business: {project_name}
Description: {description}
Primary colour: {primary_color}
Secondary colour: {secondary_color}
Background colour: {background_color}
{revision_block}

Requirements:
- realistic photography style
- clearly relevant to the business description
- clean, modern, believable, and premium and a nice background blurry effect
- NO WRITING or TEXT or FRONT OF THE HUMAN FACE in this image WHATSOEVER
- suitable for a homepage hero with text overlay
- leave calm negative space for a headline and button (around the middle)
- image contrast must keep white or near-white hero text readable
- not too dramatic yet not too simple, there must be noise
- realistic lighting and materials
- use the listed brand colours as gentle scene accents, styling cues, or environmental tones
- avoid placing key detail where hero text would normally sit
- no text, no logos, no watermarks
- composition should feel trustworthy, polished, and commercially usable
"""

    print(f"[IMAGE_GEN] Received image generation text for project_id={project_id}:")
    print(f"[IMAGE_GEN] --- PROMPT START ---")
    print(prompt.strip())
    print(f"[IMAGE_GEN] --- PROMPT END ---")
    logging.info("[IMAGE_GEN] Sending image generation request for project_id=%s (business='%s')", project_id, project_name)

    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1536x1024"
    )

    print(f"[IMAGE_GEN] Received response from OpenAI image API for project_id={project_id}")
    logging.info("[IMAGE_GEN] OpenAI image response received for project_id=%s", project_id)

    image_bytes = b""
    image_data = response.data[0] if getattr(response, "data", None) else None

    if image_data and getattr(image_data, "b64_json", None):
        image_bytes = base64.b64decode(image_data.b64_json)
        print(f"[IMAGE_GEN] Image decoded from b64_json: {len(image_bytes)} bytes")
    elif image_data and getattr(image_data, "url", None):
        print(f"[IMAGE_GEN] Downloading image from URL: {image_data.url}")
        with urlopen(image_data.url) as remote:
            image_bytes = remote.read()
        print(f"[IMAGE_GEN] Image downloaded from URL: {len(image_bytes)} bytes")
    else:
        print(f"[IMAGE_GEN] WARNING: No image data in response for project_id={project_id}. response.data={getattr(response, 'data', None)}")

    if not image_bytes:
        print(f"[IMAGE_GEN] ERROR: image_bytes is empty for project_id={project_id} — returning empty string")
        return ""

    saved_path = save_hero_image_bytes(image_bytes, project_id)
    print(f"[IMAGE_GEN] Image generated using following text (first 200 chars): '{description[:200]}'")
    print(f"[IMAGE_GEN] Image saved to: '{saved_path}'")
    logging.info("[IMAGE_GEN] Hero image saved: '%s' for project_id=%s", saved_path, project_id)
    return saved_path


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
    revision_comment = (request.get_json(silent=True) or {}).get("comment", "")
    revision_comment = str(revision_comment or "").strip()
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
    cursor.close()
    conn.close()

    job_id = secrets.token_urlsafe(16)
    _write_regen_job(job_id, {"status": "processing"})

    t = threading.Thread(
        target=_run_hero_regen_background,
        args=(
            job_id, project["id"], project["project_name"],
            description, history, current_image, revision_comment,
            theme, attempts_used,
        ),
        daemon=True,
    )
    t.start()

    return jsonify({"status": "processing", "job_id": job_id}), 202


@app.route("/admin/<slug>/hero-image/regen-status/<job_id>", methods=["GET"])
@login_required
def hero_regen_status(slug, job_id):
    job = _read_regen_job(job_id)
    if job is None:
        # File not written yet (thread just started) — tell client to keep polling.
        return jsonify({"status": "processing"})

    if job.get("status") in ("done", "error"):
        _delete_regen_job(job_id)
        return jsonify({"success": job.get("status") == "done", **job})

    return jsonify({"status": "processing"})


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


@app.route("/admin/<slug>/hero-image/upload", methods=["POST"])
@login_required
def upload_project_hero_image(slug):
    file = request.files.get("hero_image")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "No file provided."}), 400

    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in allowed_extensions:
        return jsonify({"success": False, "error": "Only JPEG, PNG, WebP, and GIF images are allowed."}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        ensure_project_details_hero_image_path_column(conn)
        ensure_project_details_hero_image_column(conn)
        ensure_project_details_hero_image_history_column(conn)
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT p.id FROM projects p WHERE p.slug=%s AND p.client_id=%s LIMIT 1",
            (slug, session["client_id"])
        )
        project = cursor.fetchone()
        if not project:
            return jsonify({"success": False, "error": "Project not found."}), 404

        cursor.execute(
            "SELECT hero_image_path, hero_image, hero_image_history FROM project_details WHERE project_id=%s LIMIT 1",
            (project["id"],)
        )
        details = cursor.fetchone() or {}

        ext = os.path.splitext(secure_filename(file.filename))[1].lower() or ".png"
        filename = f"hero_{project['id']}_{int(time.time())}{ext}"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        file.save(filepath)
        new_path = f"uploads/{filename}"

        current_image = resolve_hero_image_path(details.get("hero_image_path") or details.get("hero_image"))
        history = parse_hero_image_history(details.get("hero_image_history"))
        if current_image and current_image not in history:
            history.insert(0, current_image)

        serialized_history = serialize_hero_image_history(history)
        cursor.execute("""
            UPDATE project_details
            SET hero_image_path=%s, hero_image=NULL, hero_image_history=%s
            WHERE project_id=%s
        """, (new_path, serialized_history, project["id"]))

        if cursor.rowcount == 0:
            cursor.execute("""
                INSERT INTO project_details (project_id, hero_image_path, hero_image, hero_image_history)
                VALUES (%s, %s, NULL, %s)
            """, (project["id"], new_path, serialized_history))

        conn.commit()
        return jsonify({"success": True, "url": f"/{new_path}"})
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.exception("Hero image upload failed for slug '%s'", slug)
        return jsonify({"success": False, "error": f"Upload error: {exc}"}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  TABLE BOOKINGS — ADMIN ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

def _get_tb_project(slug):
    """Return project dict if current client owns it and it is live."""
    project = get_project_for_client(slug)
    if not project or not is_project_live(project):
        return None
    return project


@app.route("/admin/<slug>/table-bookings")
@login_required
def admin_table_bookings(slug):
    project = _get_tb_project(slug)
    if not project:
        return redirect(url_for("webconfig", slug=slug))
    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    ensure_restaurant_tables_qr_column(conn)
    location_id = resolve_active_location_id(project['id'], request.args.get("location_id"))
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM table_booking_config WHERE project_id=%s AND location_id=%s LIMIT 1",
        (project['id'], location_id)
    )
    cfg = cursor.fetchone() or {}

    # Check Stripe connection for the payment toggle UI
    cursor.execute(
        "SELECT stripe_account_id, stripe_enabled FROM projects WHERE id=%s LIMIT 1",
        (project['id'],)
    )
    proj_stripe = cursor.fetchone() or {}
    stripe_connected = bool(
        proj_stripe.get("stripe_enabled") and
        proj_stripe.get("stripe_account_id") and
        stripe.api_key
    )

    cursor.execute(
        "SELECT * FROM table_booking_hours WHERE project_id=%s AND location_id=%s ORDER BY day_of_week",
        (project['id'], location_id)
    )
    hours_rows = cursor.fetchall()
    hours_map = {h['day_of_week']: h for h in hours_rows}

    cursor.execute(
        "SELECT * FROM restaurant_tables WHERE project_id=%s AND location_id=%s AND is_active=1 ORDER BY sort_order, capacity",
        (project['id'], location_id)
    )
    tables = cursor.fetchall()

    cursor.execute(
        "SELECT tb.*, rt.capacity, rt.table_number FROM table_bookings tb "
        "LEFT JOIN restaurant_tables rt ON rt.id=tb.table_id "
        "WHERE tb.project_id=%s AND tb.location_id=%s ORDER BY tb.booking_date DESC, tb.start_time DESC LIMIT 200",
        (project['id'], location_id)
    )
    bookings = cursor.fetchall()
    for b in bookings:
        for k in ('start_time', 'end_time'):
            if b.get(k) is not None:
                b[k] = _td_to_str(b[k])

    cursor.execute(
        "SELECT * FROM table_booking_blocked WHERE project_id=%s AND location_id=%s ORDER BY blocked_date DESC",
        (project['id'], location_id)
    )
    blocked = cursor.fetchall()
    for bl in blocked:
        for k in ('start_time', 'end_time'):
            if bl.get(k) is not None:
                bl[k] = _td_to_str(bl[k])

    cursor.close(); conn.close()

    days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    hours_list = []
    for i, day in enumerate(days):
        h = hours_map.get(i, {})
        hours_list.append({
            'dow': i, 'day': day,
            'open_time': _td_to_str(h['open_time']) if h.get('open_time') else '09:00',
            'close_time': _td_to_str(h['close_time']) if h.get('close_time') else '22:00',
            'is_closed': bool(h.get('is_closed', False))
        })

    capacity_summary = {}
    for t in tables:
        c = t['capacity']
        capacity_summary[c] = capacity_summary.get(c, 0) + 1

    locations = get_project_locations(project['id'])
    return render_template(
        "admin_table_bookings.html",
        project=project,
        cfg=cfg,
        tables=tables,
        hours_list=hours_list,
        bookings=bookings,
        blocked=blocked,
        capacity_summary=capacity_summary,
        total_seats=sum(t['capacity'] for t in tables),
        stripe_connected=stripe_connected,
        locations=locations,
        active_location_id=location_id,
        multi_location=len(locations) > 1,
    )


@app.route("/admin/<slug>/table-bookings/save-config", methods=["POST"])
@login_required
def admin_tb_save_config(slug):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    location_id = resolve_active_location_id(project['id'], request.form.get("location_id"))
    cursor = conn.cursor()
    try:
        slot_duration = int(request.form.get("slot_duration_minutes", 60))
        advance_days = int(request.form.get("advance_booking_days", 60))
        min_party = int(request.form.get("min_party_size", 1))
        max_party = int(request.form.get("max_party_size", 12))
        high_chairs = 1 if request.form.get("high_chairs_enabled") else 0
        max_hc = int(request.form.get("max_high_chairs", 4))
        numbering = 1 if request.form.get("table_numbering_enabled") else 0
        lead_mins = int(request.form.get("booking_lead_minutes", 30))
        notes = request.form.get("notes_for_customers", "").strip()
        table_order_payment = 1 if request.form.get("table_order_online_payment") else 0

        cursor.execute("""
            INSERT INTO table_booking_config
                (project_id, location_id, slot_duration_minutes, advance_booking_days,
                 min_party_size, max_party_size, high_chairs_enabled, max_high_chairs,
                 table_numbering_enabled, booking_lead_minutes, notes_for_customers,
                 table_order_online_payment)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                slot_duration_minutes=%s, advance_booking_days=%s,
                min_party_size=%s, max_party_size=%s, high_chairs_enabled=%s,
                max_high_chairs=%s, table_numbering_enabled=%s,
                booking_lead_minutes=%s, notes_for_customers=%s,
                table_order_online_payment=%s
        """, (
            project['id'], location_id, slot_duration, advance_days, min_party, max_party,
            high_chairs, max_hc, numbering, lead_mins, notes, table_order_payment,
            slot_duration, advance_days, min_party, max_party,
            high_chairs, max_hc, numbering, lead_mins, notes, table_order_payment
        ))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/save-hours", methods=["POST"])
@login_required
def admin_tb_save_hours(slug):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    location_id = resolve_active_location_id(project['id'], request.form.get("location_id"))
    cursor = conn.cursor()
    try:
        for dow in range(7):
            open_t = request.form.get(f"open_{dow}", "09:00")
            close_t = request.form.get(f"close_{dow}", "22:00")
            closed = 1 if request.form.get(f"closed_{dow}") else 0
            cursor.execute("""
                INSERT INTO table_booking_hours (project_id, location_id, day_of_week, open_time, close_time, is_closed)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE open_time=%s, close_time=%s, is_closed=%s
            """, (project['id'], location_id, dow, open_t, close_t, closed, open_t, close_t, closed))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/add-tables", methods=["POST"])
@login_required
def admin_tb_add_tables(slug):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    location_id = resolve_active_location_id(project['id'], request.form.get("location_id"))
    cursor = conn.cursor(dictionary=True)
    try:
        capacity = int(request.form.get("capacity", 0))
        count = int(request.form.get("count", 1))
        if capacity < 1 or count < 1:
            return jsonify({"success": False, "error": "Invalid capacity or count"}), 400

        cursor.execute(
            "SELECT MAX(sort_order) AS mx FROM restaurant_tables WHERE project_id=%s AND location_id=%s",
            (project['id'], location_id)
        )
        row = cursor.fetchone()
        sort_base = (row['mx'] or 0) + 1

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM restaurant_tables WHERE project_id=%s AND location_id=%s AND is_active=1",
            (project['id'], location_id)
        )
        existing_count = (cursor.fetchone() or {}).get('cnt', 0)

        ensure_restaurant_tables_qr_column(conn)
        restaurant_name = (project.get("project_name") or slug).strip()
        added = []
        for i in range(count):
            auto_num = f"T{existing_count + i + 1}"
            cursor.execute(
                "INSERT INTO restaurant_tables (project_id, location_id, capacity, table_number, sort_order) VALUES (%s,%s,%s,%s,%s)",
                (project['id'], location_id, capacity, auto_num, sort_base + i)
            )
            table_id = cursor.lastrowid
            table_url = f"https://{slug}.dinebloc.com/table/{table_id}"
            qr_path = ""
            try:
                table_label = f"Table {auto_num}  ·  {capacity} seat{'s' if capacity != 1 else ''}"
                qr_bytes = generate_table_qr_card_bytes(table_url, restaurant_name, table_label)
                if qr_bytes:
                    qr_filename = f"table_qr_{table_id}_{int(time.time())}.png"
                    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
                    qr_filepath = os.path.join(app.config["UPLOAD_FOLDER"], qr_filename)
                    with open(qr_filepath, "wb") as f:
                        f.write(qr_bytes)
                    qr_path = f"uploads/{qr_filename}"
                    cursor.execute(
                        "UPDATE restaurant_tables SET qr_code_path=%s WHERE id=%s",
                        (qr_path, table_id)
                    )
            except Exception:
                logging.exception("[QR] Failed to generate QR card for table %s", table_id)
            added.append({"id": table_id, "capacity": capacity, "table_number": auto_num, "qr_code_path": qr_path})
        conn.commit()
        return jsonify({"success": True, "added": added})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/delete-table/<int:table_id>", methods=["POST"])
@login_required
def admin_tb_delete_table(slug, table_id):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE restaurant_tables SET is_active=0 WHERE id=%s AND project_id=%s",
            (table_id, project['id'])
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/update-table-number/<int:table_id>", methods=["POST"])
@login_required
def admin_tb_update_table_number(slug, table_id):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    new_number = request.form.get("table_number", "").strip()[:20]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE restaurant_tables SET table_number=%s WHERE id=%s AND project_id=%s",
            (new_number or None, table_id, project['id'])
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/cancel/<int:booking_id>", methods=["POST"])
@login_required
def admin_tb_cancel_booking(slug, booking_id):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM table_bookings WHERE id=%s AND project_id=%s LIMIT 1",
            (booking_id, project['id'])
        )
        booking = cursor.fetchone()
        if not booking:
            return jsonify({"success": False, "error": "Booking not found"}), 404

        cursor.execute(
            "UPDATE table_bookings SET status='cancelled', cancelled_at=NOW(), cancelled_by='admin' "
            "WHERE id=%s",
            (booking_id,)
        )
        conn.commit()

        # Notify customer
        html = f"""<p>Hi {booking['customer_name']},</p>
<p>Your table booking at <strong>{project['project_name']}</strong> has been cancelled by the restaurant.</p>
<p><strong>Date:</strong> {booking['booking_date']}<br>
<strong>Time:</strong> {_td_to_str(booking['start_time'])}<br>
<strong>Booking ref:</strong> {booking['booking_ref']}</p>
<p>Please contact us if you have any questions.</p>"""
        send_email(booking['customer_email'], f"Booking Cancelled – {project['project_name']}", html)
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/add-note/<int:booking_id>", methods=["POST"])
@login_required
def admin_tb_add_note(slug, booking_id):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    note = request.form.get("note", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE table_bookings SET admin_notes=%s WHERE id=%s AND project_id=%s",
            (note, booking_id, project['id'])
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/block", methods=["POST"])
@login_required
def admin_tb_block(slug):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    cursor = conn.cursor()
    try:
        blocked_date = request.form.get("blocked_date", "")
        start_time = request.form.get("start_time") or None
        end_time = request.form.get("end_time") or None
        reason = request.form.get("reason", "").strip()[:255]
        cursor.execute(
            "INSERT INTO table_booking_blocked (project_id, blocked_date, start_time, end_time, reason) "
            "VALUES (%s,%s,%s,%s,%s)",
            (project['id'], blocked_date, start_time, end_time, reason or None)
        )
        conn.commit()
        return jsonify({"success": True, "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/unblock/<int:block_id>", methods=["POST"])
@login_required
def admin_tb_unblock(slug, block_id):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM table_booking_blocked WHERE id=%s AND project_id=%s",
            (block_id, project['id'])
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/mark-complete/<int:booking_id>", methods=["POST"])
@login_required
def admin_tb_mark_complete(slug, booking_id):
    project = _get_tb_project(slug)
    if not project:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE table_bookings SET status='completed' WHERE id=%s AND project_id=%s",
            (booking_id, project['id'])
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/admin/<slug>/table-bookings/table-qr/<int:table_id>")
@login_required
def admin_tb_table_qr(slug, table_id):
    project = _get_tb_project(slug)
    if not project:
        return ("", 403)
    conn = get_db_connection()
    ensure_restaurant_tables_qr_column(conn)
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, table_number, capacity, qr_code_path "
            "FROM restaurant_tables WHERE id=%s AND project_id=%s AND is_active=1 LIMIT 1",
            (table_id, project['id'])
        )
        row = cursor.fetchone()
    except Exception:
        cursor.close(); conn.close()
        return ("", 500)

    if not row:
        cursor.close(); conn.close()
        return ("", 404)

    qr_path = (row.get("qr_code_path") or "").strip()
    full_path = os.path.join(app.config["UPLOAD_FOLDER"], qr_path.replace("uploads/", "", 1)) if qr_path else ""

    if not qr_path or not os.path.exists(full_path):
        # Generate-on-demand for tables created before this feature
        try:
            table_url = f"https://{slug}.dinebloc.com/table/{table_id}"
            restaurant_name = (project.get("project_name") or slug).strip()
            table_num = (row.get("table_number") or f"T{table_id}").strip()
            capacity  = row.get("capacity", 2)
            table_label = f"Table {table_num}  ·  {capacity} seat{'s' if int(capacity) != 1 else ''}"
            qr_bytes = generate_table_qr_card_bytes(table_url, restaurant_name, table_label)
            if qr_bytes:
                qr_filename = f"table_qr_{table_id}_{int(time.time())}.png"
                os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
                qr_filepath = os.path.join(app.config["UPLOAD_FOLDER"], qr_filename)
                with open(qr_filepath, "wb") as f:
                    f.write(qr_bytes)
                qr_path = f"uploads/{qr_filename}"
                cursor.execute(
                    "UPDATE restaurant_tables SET qr_code_path=%s WHERE id=%s",
                    (qr_path, table_id)
                )
                conn.commit()
        except Exception:
            logging.exception("[QR] On-demand generation failed for table %s", table_id)
            cursor.close(); conn.close()
            return ("", 500)

    cursor.close(); conn.close()

    if not qr_path:
        return ("", 204)
    return send_from_directory(app.config["UPLOAD_FOLDER"], qr_path.replace("uploads/", "", 1))


@app.route("/admin/<slug>/table-bookings/qr-pdf")
@login_required
def admin_tb_qr_pdf(slug):
    project = _get_tb_project(slug)
    if not project:
        return ("", 403)
    conn = get_db_connection()
    ensure_restaurant_tables_qr_column(conn)
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, table_number, capacity, qr_code_path FROM restaurant_tables "
            "WHERE project_id=%s AND is_active=1 ORDER BY sort_order, capacity",
            (project['id'],)
        )
        tables = cursor.fetchall()
    finally:
        cursor.close(); conn.close()

    if not tables:
        return ("No tables found", 404)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.colors import HexColor
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        return ("PDF generation unavailable: reportlab not installed", 503)

    page_w, page_h = A4
    margin = 40
    cols = 2
    rows_per_page = 2
    per_page = cols * rows_per_page

    cell_w = (page_w - margin * 2) / cols
    cell_h = (page_h - margin * 2) / rows_per_page

    buf = BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=A4)

    project_name = (project.get("project_name") or "").strip()

    def draw_page_header(c):
        c.setFillColor(HexColor("#f8fafc"))
        c.rect(0, page_h - 36, page_w, 36, fill=1, stroke=0)
        c.setFillColor(HexColor("#2563eb"))
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(page_w / 2, page_h - 24, project_name + " — Table QR Codes")
        c.setStrokeColor(HexColor("#e2e8f0"))
        c.setLineWidth(0.5)
        c.line(margin, page_h - 36, page_w - margin, page_h - 36)

    draw_page_header(pdf)

    menu_url = f"https://{slug}.dinebloc.com/menu"

    for idx, table in enumerate(tables):
        if idx > 0 and idx % per_page == 0:
            pdf.showPage()
            draw_page_header(pdf)

        pos = idx % per_page
        col_idx = pos % cols
        row_idx = pos // cols

        cell_x = margin + col_idx * cell_w
        cell_y = page_h - margin - 36 - (row_idx + 1) * cell_h

        cx = cell_x + cell_w / 2

        # Cell border
        pdf.setFillColor(HexColor("#ffffff"))
        pdf.setStrokeColor(HexColor("#e2e8f0"))
        pdf.setLineWidth(0.5)
        pdf.roundRect(cell_x + 10, cell_y + 10, cell_w - 20, cell_h - 20, 10, fill=1, stroke=1)

        # Load the stored styled card image; generate on-demand if missing
        qr_path = (table.get("qr_code_path") or "").strip()
        card_bytes = None
        if qr_path:
            full = os.path.join(app.config["UPLOAD_FOLDER"], qr_path.replace("uploads/", "", 1))
            if os.path.exists(full):
                with open(full, "rb") as f:
                    card_bytes = f.read()
        if not card_bytes:
            try:
                table_num   = (table.get("table_number") or f"T{idx + 1}").strip()
                capacity    = table.get("capacity", 2)
                table_label = f"Table {table_num}  ·  {capacity} seat{'s' if int(capacity) != 1 else ''}"
                t_url = f"https://{slug}.dinebloc.com/table/{table.get('id', idx + 1)}"
                card_bytes  = generate_table_qr_card_bytes(t_url, project_name, table_label)
            except Exception:
                pass

        if card_bytes:
            # Fit the card image inside the cell with padding
            img_pad  = 24
            img_w    = cell_w - img_pad * 2
            img_h    = cell_h - img_pad * 2
            img_x    = cell_x + img_pad
            img_y    = cell_y + img_pad
            pdf.drawImage(
                ImageReader(BytesIO(card_bytes)),
                img_x, img_y, width=img_w, height=img_h,
                preserveAspectRatio=True, anchor="c", mask="auto"
            )

    pdf.setFillColor(HexColor("#94a3b8"))
    pdf.setFont("Helvetica", 7)
    pdf.drawCentredString(page_w / 2, 18, f"Generated by Dinebloc  ·  {project_name}")

    pdf.save()
    buf.seek(0)

    safe_name = re.sub(r"[^a-z0-9_-]", "_", (project_name or slug).lower())
    filename = f"table_qr_codes_{safe_name}.pdf"
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TABLE BOOKINGS — CLIENT-FACING API  (runs under g.project subdomain context)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/table-order-stripe-checkout", methods=["POST"])
def table_order_stripe_checkout():
    """Create a pending order then a Stripe Checkout Session for a table order.
    Returns {"url": stripe_checkout_url} on success."""
    if not hasattr(g, "project"):
        return jsonify({"error": "Project not found"}), 404

    project_id   = g.project["id"]
    project_name = g.project.get("project_name", "Restaurant")
    data         = request.get_json(silent=True) or {}

    # Guard: verify Stripe is actually connected for this project
    conn = get_db_connection()
    ensure_order_columns(conn)
    ensure_table_booking_tables(conn)
    ensure_location_id_column(conn, "orders")
    ensure_location_id_column(conn, "products")
    ensure_location_id_column(conn, "deals")
    location_id = resolve_active_location_id(project_id, data.get("location_id"))
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT stripe_account_id, stripe_enabled FROM projects WHERE id=%s LIMIT 1",
        (project_id,)
    )
    proj_row = cursor.fetchone() or {}
    if not proj_row.get("stripe_enabled") or not proj_row.get("stripe_account_id"):
        cursor.close(); conn.close()
        return jsonify({"error": "Online payment not enabled for this restaurant"}), 400
    if not stripe.api_key:
        cursor.close(); conn.close()
        return jsonify({"error": "Stripe is not configured on this server"}), 503

    account_id = proj_row["stripe_account_id"]
    table_id   = int(data.get("table_id") or 0)

    # Resolve table session UUID
    raw_table_number = (data.get("table_number") or "").strip()
    if raw_table_number:
        cursor.execute("""
            SELECT table_session_id FROM orders
            WHERE project_id=%s AND table_number=%s
              AND table_session_id IS NOT NULL
              AND created_at >= NOW() - INTERVAL 4 HOUR
            ORDER BY created_at DESC LIMIT 1
        """, (project_id, raw_table_number))
        sess_row = cursor.fetchone()
        if sess_row and sess_row.get("table_session_id"):
            data["table_session_id"] = sess_row["table_session_id"]
        else:
            import uuid as _uuid
            data["table_session_id"] = str(_uuid.uuid4())

    # Create a pending order record first so we have an order_number
    try:
        order_payload = create_order_record(project_id, data, cursor, location_id=location_id)
    except ValueError as exc:
        cursor.close(); conn.close()
        return jsonify({"error": str(exc)}), 400

    order_number = order_payload["order_number"]
    total        = order_payload["total"]

    base_url = get_base_url()
    try:
        cs = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency":     "aud",
                    "product_data": {"name": f"Table Order — {project_name}"},
                    "unit_amount":  int(round(total * 100)),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=(
                f"{base_url}/table/{table_id}/payment-success"
                f"?session_id={{CHECKOUT_SESSION_ID}}&order_number={order_number}"
            ),
            cancel_url=f"{base_url}/table/{table_id}",
            payment_intent_data={
                "on_behalf_of":  account_id,
                "transfer_data": {"destination": account_id},
                "metadata":      {"project_id": str(project_id), "order_number": order_number},
            },
            metadata={"project_id": str(project_id), "order_number": order_number},
        )
    except Exception as exc:
        logging.error("[TABLE_STRIPE] Session creation failed for order %s: %s", order_number, exc)
        cursor.close(); conn.close()
        return jsonify({"error": str(exc)}), 500

    # Mark order checkout_pending with Stripe session ID
    cursor.execute(
        "UPDATE orders SET payment_status='checkout_pending', payment_method='stripe', "
        "payment_intent_id=%s WHERE order_number=%s",
        (cs.id, order_number)
    )
    conn.commit()
    cursor.close(); conn.close()

    logging.info("[TABLE_STRIPE] Session %s created for order %s project %s", cs.id, order_number, project_id)
    return jsonify({"url": cs.url, "order_number": order_number})


@app.route("/api/table-session-count")
def table_session_count():
    if not hasattr(g, "project"):
        return jsonify({"count": 0}), 404
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"count": 0})
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE project_id=%s AND table_session_id=%s",
            (g.project["id"], session_id)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return jsonify({"count": int(row["cnt"]) if row else 0})
    except Exception as e:
        return jsonify({"count": 0, "error": str(e)})


@app.route("/api/table-availability")
def table_availability():
    if not hasattr(g, "project"):
        return jsonify({"error": "Not found"}), 404
    date_str = request.args.get("date", "")
    party_size = int(request.args.get("party_size", 1))
    try:
        conn = get_db_connection()
        ensure_table_booking_tables(conn)
        location_id = resolve_active_location_id(g.project['id'], request.args.get("location_id"))
        slots = _get_available_slots(g.project['id'], date_str, party_size, conn, location_id=location_id)
        conn.close()
        return jsonify({"slots": slots})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/table-book", methods=["POST"])
def table_book():
    if not hasattr(g, "project"):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(force=True) or {}
    required = ['date', 'start_time', 'party_size', 'customer_name', 'customer_email', 'customer_phone']
    if any(not data.get(f) for f in required):
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    conn = get_db_connection()
    ensure_table_booking_tables(conn)
    location_id = resolve_active_location_id(g.project['id'], data.get("location_id"))
    cursor = conn.cursor(dictionary=True)
    try:
        pid = g.project['id']
        cursor.execute(
            "SELECT * FROM table_booking_config WHERE project_id=%s AND location_id=%s LIMIT 1",
            (pid, location_id)
        )
        cfg = cursor.fetchone() or {}
        duration_min = int(cfg.get('slot_duration_minutes', 60))

        from datetime import datetime, timedelta
        start_dt = datetime.strptime(f"{data['date']} {data['start_time']}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration_min)
        end_str = end_dt.strftime('%H:%M')

        # Find an available table
        cursor.execute(
            "SELECT * FROM restaurant_tables WHERE project_id=%s AND location_id=%s AND is_active=1 AND capacity>=%s ORDER BY capacity ASC",
            (pid, location_id, int(data['party_size']))
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
                chosen_table = t
                break

        if not chosen_table:
            return jsonify({"success": False, "error": "Sorry, no tables are available for that slot anymore. Please choose another time."}), 409

        import secrets as _sec
        ref = _sec.token_hex(6).upper()

        cursor.execute("""
            INSERT INTO table_bookings
                (project_id, location_id, table_id, booking_date, start_time, end_time, party_size,
                 customer_name, customer_email, customer_phone, special_requests,
                 high_chairs_needed, booking_ref)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            pid, location_id, chosen_table['id'], data['date'], data['start_time'], end_str,
            int(data['party_size']), data['customer_name'].strip(), data['customer_email'].strip(),
            data['customer_phone'].strip(), (data.get('special_requests') or '').strip(),
            int(data.get('high_chairs_needed', 0)), ref
        ))
        conn.commit()
        booking_id = cursor.lastrowid

        pname = g.project.get('project_name', 'the restaurant')
        table_label = chosen_table.get('table_number') or f"Table {chosen_table['id']}"

        # Email customer
        cust_html = f"""
<div style="font-family:sans-serif;max-width:540px;margin:auto">
  <h2 style="color:#111">Booking Confirmed ✓</h2>
  <p>Hi <strong>{data['customer_name']}</strong>, your table is reserved at <strong>{pname}</strong>.</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0">
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Date</td><td style="padding:8px">{data['date']}</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Time</td><td style="padding:8px">{data['start_time']} – {end_str}</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Party size</td><td style="padding:8px">{data['party_size']} guests</td></tr>
    <tr><td style="padding:8px;background:#f5f5f5;font-weight:600">Booking ref</td><td style="padding:8px"><strong>{ref}</strong></td></tr>
  </table>
  <p style="color:#555;font-size:0.9rem">Keep your booking reference — you may need it to modify or cancel.</p>
</div>"""
        send_email(data['customer_email'], f"Table Booking Confirmed – {pname}", cust_html)

        # Email admin
        admin_email = g.project.get('email') or g.project.get('contact_email')
        if admin_email:
            admin_html = f"""
<div style="font-family:sans-serif;max-width:540px;margin:auto">
  <h2>New Table Booking</h2>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Customer</td><td style="padding:6px">{data['customer_name']}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Email</td><td style="padding:6px">{data['customer_email']}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Phone</td><td style="padding:6px">{data['customer_phone']}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Date</td><td style="padding:6px">{data['date']}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Time</td><td style="padding:6px">{data['start_time']} – {end_str}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Party size</td><td style="padding:6px">{data['party_size']}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Table</td><td style="padding:6px">{table_label}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">High chairs</td><td style="padding:6px">{data.get('high_chairs_needed',0)}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Requests</td><td style="padding:6px">{data.get('special_requests','—')}</td></tr>
    <tr><td style="padding:6px;background:#f5f5f5;font-weight:600">Ref</td><td style="padding:6px">{ref}</td></tr>
  </table>
</div>"""
            send_email(admin_email, f"New Table Booking – {data['date']} {data['start_time']}", admin_html)

        return jsonify({"success": True, "booking_ref": ref, "table": table_label, "end_time": end_str})
    except Exception as e:
        conn.rollback()
        logging.exception("table_book failed")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close(); conn.close()


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





ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
# Set ADMIN_PASSWORD_HASH in .env with: werkzeug.security.generate_password_hash("<your_password>")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")



def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect("/admin-7xk92q-hidden-login")
        return f(*args, **kwargs)
    return decorated_function


@app.route("/admin-7xk92q-hidden-login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if (ADMIN_EMAIL and email == ADMIN_EMAIL.lower()
                and ADMIN_PASSWORD_HASH
                and check_password_hash(ADMIN_PASSWORD_HASH, password)):
            session.clear()
            session["is_admin"] = True
            return redirect("/admin-7xk92q-hidden")

        return "Invalid credentials", 403

    return """
    <form method="POST">
        <input name="email" placeholder="Email" required>
        <input name="password" type="password" placeholder="Password" required>
        <button type="submit">Login</button>
    </form>
    """

@app.route("/admin-7xk92q-hidden")
@admin_required
def admin_dashboard():
    return render_template("admin/dashboard.html")


@app.route("/hidden-email-sender", methods=["GET"])
@admin_required
def hidden_email_sender():
    return render_template("admin/hidden_email_sender.html")


@app.route("/hidden-email-sender/send", methods=["POST"])
@admin_required
def hidden_email_sender_send():
    subject = (request.form.get("subject") or "").strip()
    recipients_raw = request.form.get("recipients") or ""
    html_body = request.form.get("html_body") or ""
    plain_text = (request.form.get("plain_text") or "").strip()

    recipients = [r.strip() for r in recipients_raw.splitlines() if r.strip()]

    if not subject:
        return jsonify({"error": "Subject is required"}), 400
    if not recipients:
        return jsonify({"error": "At least one recipient is required"}), 400
    if not html_body.strip():
        return jsonify({"error": "HTML body is required"}), 400

    succeeded = []
    failed = []

    for email_addr in recipients:
        try:
            print(f"[SENDER] Sending email to: {email_addr}")
            payload = {
                "from": "Dinebloc <info@dinebloc.com>",
                "to": [email_addr],
                "subject": subject,
                "html": html_body,
            }
            if plain_text:
                payload["text"] = plain_text
            resend.Emails.send(payload)
            print(f"[SENDER] Success: {email_addr}")
            succeeded.append(email_addr)
        except Exception as e:
            print(f"[SENDER] Failed: {email_addr} → {e}")
            failed.append(email_addr)

    return jsonify({
        "success_count": len(succeeded),
        "failed_count": len(failed),
        "failed_emails": failed,
    })


@app.route("/feature_request", methods=["POST"])
@login_required
def submit_feature_request():
    data = request.get_json(silent=True) or request.form or {}
    feature_name = (data.get("feature_name") or "").strip()
    description = (data.get("description") or "").strip()
    page_context = (data.get("page_context") or "").strip()

    if not feature_name:
        return jsonify(success=False, error="Feature name is required"), 400

    client_id = session.get("client_id")
    client_email = session.get("email") or ""

    conn = get_db_connection()
    ensure_feature_requests_table(conn)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO feature_requests (client_id, client_email, feature_name, description, page_context)
        VALUES (%s, %s, %s, %s, %s)
    """, (client_id, client_email, feature_name, description or None, page_context or None))
    conn.commit()
    cursor.close()
    conn.close()

    html_body = build_email_shell(
        "New Feature Request",
        "A client just submitted a feature request from the dashboard.",
        f"""
        <table style="width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;">
          <tbody>
            <tr><td style="padding:10px 14px;font-size:13px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;width:1%;white-space:nowrap;">Feature</td>
                <td style="padding:10px 14px;font-size:15px;color:#0f172a;font-weight:600;">{escape(feature_name)}</td></tr>
            <tr style="background:#f8fafc;"><td style="padding:10px 14px;font-size:13px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;">Description</td>
                <td style="padding:10px 14px;font-size:15px;color:#0f172a;">{escape(description or '—')}</td></tr>
            <tr><td style="padding:10px 14px;font-size:13px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;">Submitted by</td>
                <td style="padding:10px 14px;font-size:15px;color:#0f172a;">{escape(client_email or '—')}</td></tr>
            <tr style="background:#f8fafc;"><td style="padding:10px 14px;font-size:13px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;">Page</td>
                <td style="padding:10px 14px;font-size:15px;color:#0f172a;">{escape(page_context or '—')}</td></tr>
          </tbody>
        </table>
        """,
        accent="#7c3aed"
    )
    send_email(
        to="info@dinebloc.com",
        subject=f"Feature Request: {feature_name}",
        html_body=html_body,
        sender=DEFAULT_INFO_EMAIL
    )
    return jsonify(success=True)


@app.route("/admin-api/feature_requests")
@admin_required
def get_feature_requests():
    conn = get_db_connection()
    ensure_feature_requests_table(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, client_email, feature_name, description, page_context, created_at
        FROM feature_requests
        ORDER BY created_at DESC
        LIMIT 200
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    for r in rows:
        if r.get("created_at"):
            try:
                r["created_at"] = r["created_at"].strftime("%d %b %Y %H:%M")
            except Exception:
                r["created_at"] = str(r["created_at"])
    return jsonify(rows)



@app.route("/admin-7xk92q-hidden-logout")
def admin_logout_v2():
    session.pop("is_admin", None)
    return redirect("/")



@app.route("/admin-api/analytics")
@admin_required
def get_admin_analytics():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # ── Clients ──────────────────────────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS total FROM clients")
        total_clients = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM clients WHERE is_active = 1")
        active_clients = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM clients WHERE is_active = 0")
        inactive_clients = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM clients
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        new_clients_7d = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM clients
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """)
        new_clients_30d = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM clients
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY day ORDER BY day
        """)
        signups_30d = cursor.fetchall()

        cursor.execute("""
            SELECT DATE(last_login) AS day, COUNT(*) AS cnt
            FROM clients
            WHERE last_login >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
            AND last_login IS NOT NULL
            GROUP BY day ORDER BY day
        """)
        logins_14d = cursor.fetchall()

        # ── Projects ──────────────────────────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM projects")
        total_projects = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM projects WHERE is_deployed = 1")
        deployed_projects = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT niche, COUNT(*) AS cnt FROM projects
            GROUP BY niche ORDER BY cnt DESC LIMIT 8
        """)
        projects_by_niche = cursor.fetchall()

        cursor.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM projects
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY day ORDER BY day
        """)
        projects_trend = cursor.fetchall()

        # ── Visits / Traffic ─────────────────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM project_visits")
        total_visits = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM project_visits
            WHERE DATE(visited_at) = CURDATE()
        """)
        visits_today = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM project_visits
            WHERE visited_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        visits_7d = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM project_visits
            WHERE visited_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """)
        visits_30d = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT DATE(visited_at) AS day, COUNT(*) AS cnt
            FROM project_visits
            WHERE visited_at >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
            GROUP BY day ORDER BY day
        """)
        visits_trend = cursor.fetchall()

        cursor.execute("""
            SELECT p.slug, p.project_name, COUNT(pv.id) AS cnt
            FROM project_visits pv
            JOIN projects p ON p.id = pv.project_id
            GROUP BY p.id ORDER BY cnt DESC LIMIT 10
        """)
        top_visited_projects = cursor.fetchall()

        cursor.execute("""
            SELECT HOUR(visited_at) AS hr, COUNT(*) AS cnt
            FROM project_visits
            WHERE visited_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY hr ORDER BY hr
        """)
        visits_by_hour = cursor.fetchall()

        cursor.execute("""
            SELECT ip_address, COUNT(*) AS cnt
            FROM project_visits
            GROUP BY ip_address ORDER BY cnt DESC LIMIT 10
        """)
        top_ips = cursor.fetchall()

        # ── Orders ────────────────────────────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM orders")
        total_orders = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM orders
            WHERE DATE(created_at) = CURDATE()
        """)
        orders_today = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM orders
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        orders_7d = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM orders WHERE status = 'completed'
        """)
        orders_completed = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) AS rev FROM orders
            WHERE status = 'completed'
              AND NOT (payment_method = 'instore' AND (payment_status IS NULL OR payment_status != 'paid'))
        """)
        total_revenue = float(cursor.fetchone()["rev"])

        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) AS rev FROM orders
            WHERE status = 'completed'
              AND NOT (payment_method = 'instore' AND (payment_status IS NULL OR payment_status != 'paid'))
              AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """)
        revenue_30d = float(cursor.fetchone()["rev"])

        cursor.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt, COALESCE(SUM(total),0) AS rev
            FROM orders
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
            GROUP BY day ORDER BY day
        """)
        orders_trend = cursor.fetchall()

        cursor.execute("""
            SELECT p.project_name, COUNT(o.id) AS cnt
            FROM orders o JOIN projects p ON p.id = o.project_id
            GROUP BY p.id ORDER BY cnt DESC LIMIT 8
        """)
        top_ordering_projects = cursor.fetchall()

        cursor.execute("""
            SELECT payment_method, COUNT(*) AS cnt
            FROM orders GROUP BY payment_method ORDER BY cnt DESC
        """)
        payment_methods = cursor.fetchall()

        cursor.execute("""
            SELECT status, COUNT(*) AS cnt
            FROM orders GROUP BY status ORDER BY cnt DESC
        """)
        order_statuses = cursor.fetchall()

        # ── Questions / Inquiries ─────────────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM questions")
        total_questions = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM catering_inquiries")
        total_catering = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM reservations")
        total_reservations = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM reservations WHERE status = 'pending'
        """)
        pending_reservations = cursor.fetchone()["cnt"]

        # ── Workers / Domains ─────────────────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM workers")
        total_workers = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM domains WHERE connected = 1")
        connected_domains = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM memberships WHERE is_active = 1")
        active_memberships = cursor.fetchone()["cnt"]

        # ── Dinebloc page visits ──────────────────────────────────────────────
        cursor.execute("""
            SELECT
                path,
                COUNT(*) AS total,
                COUNT(DISTINCT ip) AS unique_count,
                SUM(hit_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)) AS total_day,
                COUNT(DISTINCT CASE WHEN hit_at >= DATE_SUB(NOW(), INTERVAL 1 DAY) THEN ip END) AS unique_day,
                SUM(hit_at >= DATE_FORMAT(NOW(), '%Y-%m-01')) AS total_month,
                COUNT(DISTINCT CASE WHEN hit_at >= DATE_FORMAT(NOW(), '%Y-%m-01') THEN ip END) AS unique_month
            FROM site_page_hits
            GROUP BY path
            ORDER BY total DESC
        """)
        dinebloc_page_visits = cursor.fetchall()

        cursor.close()
        conn.close()

        def serialize_dates(rows, key="day"):
            for row in rows:
                if hasattr(row.get(key), "isoformat"):
                    row[key] = row[key].isoformat()

        serialize_dates(signups_30d)
        serialize_dates(logins_14d)
        serialize_dates(projects_trend)
        serialize_dates(visits_trend)
        for row in orders_trend:
            if hasattr(row.get("day"), "isoformat"):
                row["day"] = row["day"].isoformat()
            row["rev"] = float(row["rev"])

        return jsonify({
            "clients": {
                "total": total_clients,
                "active": active_clients,
                "inactive": inactive_clients,
                "new_7d": new_clients_7d,
                "new_30d": new_clients_30d,
                "signups_30d": signups_30d,
                "logins_14d": logins_14d,
            },
            "projects": {
                "total": total_projects,
                "deployed": deployed_projects,
                "not_deployed": total_projects - deployed_projects,
                "by_niche": projects_by_niche,
                "trend": projects_trend,
            },
            "visits": {
                "total": total_visits,
                "today": visits_today,
                "last_7d": visits_7d,
                "last_30d": visits_30d,
                "trend": visits_trend,
                "top_projects": top_visited_projects,
                "by_hour": visits_by_hour,
                "top_ips": top_ips,
            },
            "orders": {
                "total": total_orders,
                "today": orders_today,
                "last_7d": orders_7d,
                "completed": orders_completed,
                "total_revenue": total_revenue,
                "revenue_30d": revenue_30d,
                "trend": orders_trend,
                "top_projects": top_ordering_projects,
                "payment_methods": payment_methods,
                "statuses": order_statuses,
            },
            "engagement": {
                "questions": total_questions,
                "catering": total_catering,
                "reservations": total_reservations,
                "pending_reservations": pending_reservations,
                "workers": total_workers,
                "connected_domains": connected_domains,
                "active_memberships": active_memberships,
            },
            "dinebloc_pages": [
                {
                    "path": r["path"],
                    "total": int(r["total"] or 0),
                    "unique": int(r["unique_count"] or 0),
                    "total_day": int(r["total_day"] or 0),
                    "unique_day": int(r["unique_day"] or 0),
                    "total_month": int(r["total_month"] or 0),
                    "unique_month": int(r["unique_month"] or 0),
                }
                for r in dinebloc_page_visits
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Admin DB browser helpers ──────────────────────────────────

def _admin_valid_table(name: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    tables = {row[0] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return name in tables


def _admin_primary_key(table_name: str) -> str:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_KEY = 'PRI' LIMIT 1",
        (table_name,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else "id"


def _admin_valid_columns(table_name: str) -> set:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table_name,)
    )
    cols = {row[0] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return cols


def _admin_safe_cell(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        return f"[binary {len(value)}B]"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ── Admin DB browser routes ───────────────────────────────────

@app.route("/admin-api/tables")
@admin_required
def admin_list_tables():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SHOW TABLES")
        tables = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"tables": tables})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin-api/table/<table_name>/rows")
@admin_required
def admin_get_rows(table_name):
    try:
        if not _admin_valid_table(table_name):
            return jsonify({"error": "Invalid table"}), 400

        page  = max(1, int(request.args.get("page", 1)))
        limit = min(50, max(1, int(request.args.get("limit", 20))))
        offset = (page - 1) * limit

        conn = get_db_connection()

        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT * FROM `{table_name}` LIMIT %s OFFSET %s", (limit, offset))
        raw = cur.fetchall()
        cur.close()

        cur2 = conn.cursor()
        cur2.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        total = cur2.fetchone()[0]
        cur2.close()

        conn.close()

        rows = [{k: _admin_safe_cell(v) for k, v in row.items()} for row in raw]
        return jsonify({"rows": rows, "total": total, "page": page, "limit": limit})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin-api/table/<table_name>/row", methods=["POST"])
@admin_required
def admin_add_row(table_name):
    try:
        if not _admin_valid_table(table_name):
            return jsonify({"error": "Invalid table"}), 400

        pk      = _admin_primary_key(table_name)
        data    = request.get_json(silent=True) or {}
        allowed = _admin_valid_columns(table_name)
        cols    = [k for k in data if k != pk and k in allowed]

        conn = get_db_connection()
        cur  = conn.cursor()
        if cols:
            placeholders = ", ".join(["%s"] * len(cols))
            col_sql      = ", ".join(f"`{c}`" for c in cols)
            cur.execute(
                f"INSERT INTO `{table_name}` ({col_sql}) VALUES ({placeholders})",
                [data[c] for c in cols]
            )
        else:
            cur.execute(f"INSERT INTO `{table_name}` () VALUES ()")
        conn.commit()
        new_id = cur.lastrowid
        cur.close()
        conn.close()
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin-api/table/<table_name>/row/<int:row_id>", methods=["PATCH"])
@admin_required
def admin_update_row(table_name, row_id):
    try:
        if not _admin_valid_table(table_name):
            return jsonify({"error": "Invalid table"}), 400

        pk      = _admin_primary_key(table_name)
        data    = request.get_json(silent=True) or {}
        allowed = _admin_valid_columns(table_name)
        fields  = [(k, None if v == "" else v) for k, v in data.items() if k != pk and k in allowed]

        if not fields:
            return jsonify({"error": "No valid fields to update"}), 400

        set_clause = ", ".join(f"`{k}` = %s" for k, _ in fields)
        values     = [v for _, v in fields] + [row_id]

        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            f"UPDATE `{table_name}` SET {set_clause} WHERE `{pk}` = %s",
            values
        )
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        return jsonify({"success": True, "affected": affected})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin-api/table/<table_name>/row/<int:row_id>", methods=["DELETE"])
@admin_required
def admin_delete_row(table_name, row_id):
    try:
        if not _admin_valid_table(table_name):
            return jsonify({"error": "Invalid table"}), 400

        pk = _admin_primary_key(table_name)

        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(f"DELETE FROM `{table_name}` WHERE `{pk}` = %s", (row_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/admin-api/logs")
@admin_required
def get_logs():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT pv.ip_address, pv.path, pv.visited_at, p.project_name, p.slug
            FROM project_visits pv
            LEFT JOIN projects p ON p.id = pv.project_id
            ORDER BY pv.visited_at DESC LIMIT 100
        """)
        logs = cursor.fetchall()

        for row in logs:
            if hasattr(row.get("visited_at"), "isoformat"):
                row["visited_at"] = row["visited_at"].isoformat()

        cursor.close()
        conn.close()

        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




def _build_weekly_report_html(client_name, report, prev, top_items):
    name = escape((client_name or "").strip() or "there")
    orders = int(report["total_orders"])
    revenue = float(report["revenue"])
    avg_order = round(revenue / orders, 2) if orders else 0.0
    prev_orders = int(prev["total_orders"])
    prev_revenue = float(prev["revenue"])

    def pct_badge(current, previous):
        if previous == 0:
            return '<span style="color:#3dba7a;font-size:12px;font-weight:700;">New</span>'
        diff = current - previous
        pct = round(abs(diff) / previous * 100, 1)
        if diff >= 0:
            return f'<span style="color:#3dba7a;font-size:12px;font-weight:700;">&#9650; {pct}%</span>'
        return f'<span style="color:#e05555;font-size:12px;font-weight:700;">&#9660; {pct}%</span>'

    orders_badge = pct_badge(orders, prev_orders)
    revenue_badge = pct_badge(revenue, prev_revenue)

    top_items_html = ""
    if top_items:
        rows = ""
        for i, item in enumerate(top_items[:5]):
            item_name = escape(str(item.get("item_name", "Unknown")))
            qty = int(item.get("qty", 0))
            bar_width = min(100, int(qty / top_items[0]["qty"] * 100)) if top_items[0]["qty"] else 0
            rows += f"""
            <tr>
              <td style="padding:10px 14px;font-size:14px;color:#c8d0e0;">
                <span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#1e2540;
                  color:#8fa8ff;font-size:11px;font-weight:700;text-align:center;line-height:20px;margin-right:8px;">{i+1}</span>
                {item_name}
              </td>
              <td style="padding:10px 14px;font-size:13px;color:#8fa8ff;text-align:right;white-space:nowrap;">{qty} orders</td>
              <td style="padding:10px 14px;width:120px;">
                <div style="background:#1e2330;border-radius:4px;height:6px;">
                  <div style="background:linear-gradient(90deg,#4a7cdc,#8fa8ff);height:6px;border-radius:4px;width:{bar_width}%;"></div>
                </div>
              </td>
            </tr>"""
        top_items_html = f"""
        <div style="margin-top:28px;">
          <div style="font-size:11px;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;
            color:#4a5266;margin-bottom:12px;">Top Items This Week</div>
          <div style="border-radius:14px;overflow:hidden;border:1px solid #1e2330;">
            <table style="width:100%;border-collapse:collapse;">
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    content_html = f"""
    <p style="margin:0 0 24px;font-size:15px;line-height:1.75;color:#9aa4b8;">
      Hi {name}, here's how your restaurant performed over the last 7 days.
    </p>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px;">
      <div style="padding:20px;border-radius:14px;background:#0f1219;border:1px solid #1e2330;border-top:3px solid #4a7cdc;">
        <div style="font-size:11px;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;color:#4a5266;margin-bottom:10px;">Orders</div>
        <div style="font-size:32px;font-weight:800;color:#e0e6f0;line-height:1;">{orders}</div>
        <div style="margin-top:8px;">{orders_badge}</div>
        <div style="font-size:11px;color:#4a5266;margin-top:4px;">vs prev. 7 days</div>
      </div>
      <div style="padding:20px;border-radius:14px;background:#0f1219;border:1px solid #1e2330;border-top:3px solid #3dba7a;">
        <div style="font-size:11px;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;color:#4a5266;margin-bottom:10px;">Revenue</div>
        <div style="font-size:32px;font-weight:800;color:#e0e6f0;line-height:1;">${revenue:,.2f}</div>
        <div style="margin-top:8px;">{revenue_badge}</div>
        <div style="font-size:11px;color:#4a5266;margin-top:4px;">vs prev. 7 days</div>
      </div>
      <div style="padding:20px;border-radius:14px;background:#0f1219;border:1px solid #1e2330;border-top:3px solid #d4913a;">
        <div style="font-size:11px;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;color:#4a5266;margin-bottom:10px;">Avg Order</div>
        <div style="font-size:32px;font-weight:800;color:#e0e6f0;line-height:1;">${avg_order:,.2f}</div>
        <div style="margin-top:8px;font-size:12px;color:#4a5266;">per transaction</div>
      </div>
    </div>
    {top_items_html}
    <div style="margin-top:28px;padding:18px 22px;border-radius:14px;background:#0f1219;border:1px solid #1e2330;">
      <div style="font-size:11px;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;color:#4a5266;margin-bottom:14px;">
        Previous Week
      </div>
      <div style="display:flex;gap:28px;flex-wrap:wrap;">
        <div>
          <div style="font-size:20px;font-weight:700;color:#7a849a;">{prev_orders}</div>
          <div style="font-size:11px;color:#4a5266;margin-top:4px;">Orders</div>
        </div>
        <div>
          <div style="font-size:20px;font-weight:700;color:#7a849a;">${prev_revenue:,.2f}</div>
          <div style="font-size:11px;color:#4a5266;margin-top:4px;">Revenue</div>
        </div>
      </div>
    </div>
    <div style="margin-top:24px;text-align:center;">
      <a href="https://app.dinebloc.com/dashboard"
         style="display:inline-block;padding:13px 28px;border-radius:10px;
                background:linear-gradient(135deg,#4a7cdc,#1e2540);
                color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;
                letter-spacing:0.02em;">
        View Full Dashboard &rarr;
      </a>
    </div>
    """

    return build_email_shell(
        "Your Weekly Report",
        "Performance summary for the last 7 days",
        content_html,
        accent="#1e2540"
    )


def send_weekly_reports():
    conn = get_db_connection()

    end = datetime.utcnow()
    start = end - timedelta(days=7)
    prev_start = start - timedelta(days=7)

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, email, name FROM clients WHERE email IS NOT NULL AND email != ''")
    clients = cursor.fetchall()
    cursor.close()

    sent = 0
    failed = 0

    for client in clients:
        client_email = (client.get("email") or "").strip()
        if not client_email:
            continue
        try:
            rc = conn.cursor(dictionary=True)

            rc.execute("""
                SELECT COUNT(*) AS total_orders, COALESCE(SUM(o.total), 0) AS revenue
                FROM orders o
                JOIN projects p ON p.id = o.project_id
                WHERE p.client_id = %s AND o.created_at BETWEEN %s AND %s
            """, (client["id"], start, end))
 
            report = rc.fetchone()

            rc.execute("""
                SELECT COUNT(*) AS total_orders, COALESCE(SUM(o.total), 0) AS revenue
                FROM orders o
                JOIN projects p ON p.id = o.project_id
                WHERE p.client_id = %s AND o.created_at BETWEEN %s AND %s
            """, (client["id"], prev_start, start))
            prev = rc.fetchone() or {"total_orders": 0, "revenue": 0}
            rc.close()

            top_items = []
            try:
                rc.execute("""
                    SELECT
                        JSON_UNQUOTE(JSON_EXTRACT(item_json.value, '$.name')) AS item_name,
                        CAST(JSON_UNQUOTE(JSON_EXTRACT(item_json.value, '$.quantity')) AS UNSIGNED) AS qty
                    FROM orders o
                    JOIN projects p ON p.id = o.project_id
                    JOIN JSON_TABLE(o.items, '$[*]' COLUMNS (value JSON PATH '$')) AS item_json
                    WHERE p.client_id = %s AND o.created_at BETWEEN %s AND %s
                      AND JSON_EXTRACT(item_json.value, '$.name') IS NOT NULL
                """, (client["id"], start, end))
                raw_items = rc.fetchall()
                item_totals = {}
                for row in raw_items:
                    n = (row.get("item_name") or "").strip()
                    q = int(row.get("qty") or 0)
                    if n:
                        item_totals[n] = item_totals.get(n, 0) + q
                top_items = sorted(
                    [{"item_name": k, "qty": v} for k, v in item_totals.items()],
                    key=lambda x: x["qty"], reverse=True
                )
            except Exception:
                pass
            rc.close()

            html = _build_weekly_report_html(client.get("name"), report, prev, top_items)

            if not html:
                print(f"[WEEKLY REPORT] Skipped (no HTML): {client_email}")
                continue

            resend.Emails.send({
                "from": "Dinebloc <info@dinebloc.com>",
                "to": [client_email],
                "subject": "Your Weekly Dinebloc Report",
                "html": html,
            })

            print(f"[WEEKLY REPORT] Success: {client_email}")
            sent += 1

        except Exception as e:
            print(f"[WEEKLY REPORT] Failed: {client_email} → {e}")
            failed += 1

    conn.close()
    print(f"[WEEKLY REPORT] Done — sent: {sent}, failed: {failed}")



@app.route("/api/stripe/status/<int:project_id>")
@login_required
def stripe_status(project_id):
    conn = get_db_connection()
    ensure_stripe_project_columns(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT stripe_account_id, stripe_enabled FROM projects WHERE id = %s AND client_id = %s",
        (project_id, session["client_id"])
    )
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"error": "Project not found"}), 404

    if not project.get("stripe_account_id"):
        cursor.close()
        conn.close()
        return jsonify({
            "connected": False,
            "charges_enabled": False,
            "payouts_enabled": False,
            "details_submitted": False,
        })

    try:
        account = stripe.Account.retrieve(project["stripe_account_id"])
        charges_enabled = account.charges_enabled
        payouts_enabled = account.payouts_enabled
        details_submitted = account.details_submitted

        cursor.execute("""
            UPDATE projects
            SET stripe_enabled = %s,
                stripe_charges_enabled = %s,
                stripe_payouts_enabled = %s
            WHERE id = %s
        """, (
            1 if charges_enabled else 0,
            1 if charges_enabled else 0,
            1 if payouts_enabled else 0,
            project_id,
        ))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "connected": True,
            "charges_enabled": charges_enabled,
            "payouts_enabled": payouts_enabled,
            "details_submitted": details_submitted,
        })

    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


def get_base_url():
    """Return the public base URL (always HTTPS in production).
    Reads BASE_URL env var first, then trusts X-Forwarded-Proto from nginx."""
    env = os.getenv("BASE_URL", "").rstrip("/")
    if env:
        return env
    proto = request.headers.get("X-Forwarded-Proto", "https")
    return f"{proto}://{request.host}"


@app.route("/api/stripe/disconnect/<int:project_id>", methods=["POST"])
@login_required
def stripe_disconnect(project_id):
    """Clear the stored Stripe account so the project can start a fresh Connect flow.
    Useful when switching between test/live keys."""
    conn = get_db_connection()
    ensure_stripe_project_columns(conn)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM projects WHERE id = %s AND client_id = %s",
        (project_id, session["client_id"])
    )
    if not cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"error": "Project not found"}), 404
    cursor.execute(
        "UPDATE projects SET stripe_account_id = NULL, stripe_enabled = 0 WHERE id = %s",
        (project_id,)
    )
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"success": True})


@app.route("/api/stripe/create-account/<int:project_id>")
@login_required
def create_stripe_account(project_id):
    conn = get_db_connection()
    ensure_stripe_project_columns(conn)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, stripe_account_id FROM projects WHERE id = %s AND client_id = %s",
        (project_id, session["client_id"])
    )
    project = cursor.fetchone()

    if not project:
        cursor.close()
        conn.close()
        return jsonify({"error": "Project not found"}), 404

    if project.get("stripe_account_id"):
        cursor.close()
        conn.close()
        return jsonify({"account_id": project["stripe_account_id"]})

    try:
        account = stripe.Account.create(
            type="express",
            country="AU",
            capabilities={
                "card_payments": {"requested": True},
                "transfers":     {"requested": True},
            },
        )

        cursor.execute(
            "UPDATE projects SET stripe_account_id = %s WHERE id = %s",
            (account.id, project_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"account_id": account.id})

    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/stripe/onboard/<int:project_id>")
@login_required
def stripe_onboard(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT stripe_account_id FROM projects WHERE id = %s AND client_id = %s",
        (project_id, session["client_id"])
    )
    project = cursor.fetchone()
    cursor.close()
    conn.close()

    if not project or not project.get("stripe_account_id"):
        return jsonify({"error": "Stripe account not found"}), 400

    # Store context so the return route can verify the account
    session["stripe_onboard_project_id"]  = project_id
    session["stripe_onboard_account_id"]  = project["stripe_account_id"]

    try:
        base_url = get_base_url()
        account_link = stripe.AccountLink.create(
            account=project["stripe_account_id"],
            refresh_url=f"{base_url}/stripe/refresh",
            return_url=f"{base_url}/stripe/return",
            type="account_onboarding",
        )
        return redirect(account_link.url)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stripe/return")
def stripe_return():
    project_id = session.pop("stripe_onboard_project_id", None)
    account_id = session.pop("stripe_onboard_account_id", None)

    charges_enabled = False
    if account_id:
        try:
            acct = stripe.Account.retrieve(account_id)
            charges_enabled = bool(acct.charges_enabled)
        except Exception:
            charges_enabled = False

    if charges_enabled and project_id:
        conn = get_db_connection()
        ensure_stripe_project_columns(conn)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET stripe_enabled=1 WHERE id=%s",
            (project_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return render_template("stripe_return.html", charges_enabled=True)

    # Onboarding started but not yet complete — redirect back to dashboard
    return redirect(url_for("dashboard") + "?stripe=incomplete")


@app.route("/stripe/refresh")
def stripe_refresh():
    return redirect(url_for("dashboard"))


@app.route("/api/stripe/start-checkout", methods=["POST"])
def stripe_start_checkout():
    """Create a Stripe Checkout Session for the restaurant's Express Connect account.
    Stores a pending order in the DB, then returns the Stripe-hosted checkout URL.
    The order is confirmed in /payment-success after Stripe redirects back."""
    if not hasattr(g, "project") or not g.project:
        return jsonify({"error": "Project not found"}), 404

    project_id   = g.project["id"]
    project_name = g.project.get("project_name", "Restaurant")
    data         = request.get_json(silent=True) or {}

    conn = get_db_connection()
    ensure_order_columns(conn)
    ensure_location_id_column(conn, "orders")
    ensure_location_id_column(conn, "products")
    ensure_location_id_column(conn, "deals")
    location_id = resolve_active_location_id(project_id, data.get("location_id"))
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT stripe_account_id, stripe_enabled FROM projects WHERE id = %s",
        (project_id,)
    )
    project_row = cursor.fetchone()

    if not project_row or not project_row.get("stripe_enabled") or not project_row.get("stripe_account_id"):
        cursor.close()
        conn.close()
        return jsonify({"error": "Payments not enabled for this restaurant"}), 400

    # Create pending order so we have an order_number before redirecting
    try:
        order_payload = create_order_record(project_id, data, cursor, location_id=location_id)
    except ValueError as exc:
        cursor.close()
        conn.close()
        return jsonify({"error": str(exc)}), 400

    order_number = order_payload["order_number"]
    total        = order_payload["total"]
    account_id   = project_row["stripe_account_id"]

    base_url = get_base_url()
    try:
        cs = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency":     "aud",
                    "product_data": {"name": f"Order from {project_name}"},
                    "unit_amount":  int(round(total * 100)),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}&order_number={order_number}",
            cancel_url=f"{base_url}/checkout",
            payment_intent_data={
                "on_behalf_of":  account_id,
                "transfer_data": {"destination": account_id},
                "metadata":      {"project_id": str(project_id), "order_number": order_number},
            },
            metadata={"project_id": str(project_id), "order_number": order_number},
        )
    except Exception as exc:
        logging.error("[STRIPE] Checkout Session creation failed for order %s: %s", order_number, exc)
        cursor.close()
        conn.close()
        return jsonify({"error": str(exc)}), 500

    # Mark order as checkout_pending and store session ID temporarily
    cursor.execute(
        "UPDATE orders SET payment_status='checkout_pending', payment_intent_id=%s WHERE order_number=%s",
        (cs.id, order_number)
    )
    conn.commit()
    cursor.close()
    conn.close()

    logging.info("[STRIPE] Checkout Session %s created for order %s project %s", cs.id, order_number, project_id)
    return jsonify({"url": cs.url})


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)



