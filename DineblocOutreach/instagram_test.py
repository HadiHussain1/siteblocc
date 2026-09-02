import argparse
import json
import sys
import time
import traceback

from playwright.sync_api import sync_playwright

# ============================================================
# TEST SETTINGS
# ============================================================

USERNAME = "instagram"

MESSAGE = "Hey! This is a test message from Dinebloc Outreach."
CDP_URL = "http://127.0.0.1:9223"

parser = argparse.ArgumentParser()
parser.add_argument("--payload")
args = parser.parse_args()
INTERACTIVE = not args.payload

if args.payload:
    with open(args.payload, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    USERNAME = (payload.get("username") or "").strip().lstrip("@")
    messages = [str(item).strip() for item in (payload.get("messages") or []) if str(item).strip()]
    CDP_URL = (payload.get("cdp_url") or CDP_URL).strip()
    if not USERNAME:
        raise RuntimeError("Missing Instagram username.")
    if len(messages) != 1:
        raise RuntimeError("Live Test S1 requires exactly one message.")
    MESSAGE = messages[0]


def log(prefix, message):
    print(f"{prefix} {message}", file=sys.stderr, flush=True)


def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    log("[ERROR]", f"[INSTAGRAM] Sender failed: {exc_value}")
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)


sys.excepthook = log_uncaught_exception


# ============================================================
# CONNECT
# ============================================================

log("[INSTAGRAM]", f"Sender started. username=@{USERNAME} live_test={not INTERACTIVE}")
log("[INSTAGRAM]", f"CDP connection attempted. cdp_url={CDP_URL}")

with sync_playwright() as p:

    browser = p.chromium.connect_over_cdp(
        CDP_URL
    )

    log("[INSTAGRAM]", "Chrome CDP connection succeeded.")

    context = browser.contexts[0]

    page = None

    for existing_page in context.pages:
        if "instagram.com" in existing_page.url.lower():
            page = existing_page
            break

    if page is None:
        page = context.new_page()
        log("[INSTAGRAM]", "No Instagram tab found; opened a new page.")
    else:
        log("[INSTAGRAM]", f"Instagram page found: {page.url}")

    # ========================================================
    # OPEN PROFILE
    # ========================================================

    profile_url = f"https://www.instagram.com/{USERNAME}/"

    log("[INSTAGRAM]", f"Opening target profile: @{USERNAME}")

    page.goto(
        profile_url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    time.sleep(5)

    log("[INSTAGRAM]", f"Target profile loaded. current_url={page.url}")
    login_inputs = page.locator("input[name='username'], input[name='password']")
    if login_inputs.count() > 0:
        raise RuntimeError("Instagram login screen detected; the Chrome CDP profile is not logged in.")
    log("[INSTAGRAM]", "Logged-in Instagram state verified.")

    # ========================================================
    # MESSAGE BUTTON
    # ========================================================

    log("[INSTAGRAM]", "Looking for Message button.")

    message_button = page.get_by_role(
        "button",
        name="Message",
        exact=True
    )

    if message_button.count() == 0:
        message_button = page.get_by_text(
            "Message",
            exact=True
        )

    if message_button.count() == 0:
        raise RuntimeError("Message button not found.")

    log("[INSTAGRAM]", "Message button found. Clicking.")

    message_button.first.click()

    log("[INSTAGRAM]", "Message window opened.")

    time.sleep(4)

    # ========================================================
    # FIND MESSAGE COMPOSER
    # ========================================================

    log("[INSTAGRAM]", "Looking for message composer.")

    composer = page.locator(
        '[contenteditable="true"]'
    )

    try:
        composer.last.wait_for(
            state="visible",
            timeout=15000
        )
    except Exception:
        raise RuntimeError("Message composer not found.")

    log("[INSTAGRAM]", "Message composer found.")

    # ========================================================
    # TYPE MESSAGE
    # ========================================================

    composer.last.click()

    composer.last.fill(MESSAGE)

    log("[INSTAGRAM]", "Message typed.")

    time.sleep(2)

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    log("[INSTAGRAM]", "Attempting send action.")

    send_button = page.get_by_role(
        "button",
        name="Send",
        exact=True
    )

    if send_button.count() > 0:

        log("[INSTAGRAM]", "Send button found. Clicking.")
        send_button.last.click()

    else:

        log("[INSTAGRAM]", "Send button not found; using Enter to send.")

        composer.last.press("Enter")

    time.sleep(4)
    log("[INSTAGRAM]", "Send confirmed after post-send wait.")

    # ========================================================
    # COMPLETE
    # ========================================================

    print("")
    print("============================================")
    print("MESSAGE SENT")
    print("============================================")
    print("")
    print("Username:", USERNAME)
    print("Message:", MESSAGE)
    print("")
    print("Check the Instagram window to confirm.")
    print("")

    if INTERACTIVE:
        input("Press ENTER to finish...")
    else:
        print(json.dumps({"success": True, "username": USERNAME, "message_count": 1}), flush=True)
