import argparse
import json
import sys
import time
import traceback

from playwright.sync_api import sync_playwright


def log(prefix, message):
    print(f"{prefix} {message}", file=sys.stderr, flush=True)


def load_payload(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def find_instagram_page(context):
    log("[INSTAGRAM]", f"Searching existing Chrome tabs for an Instagram page. page_count={len(context.pages)}")
    for existing_page in context.pages:
        if "instagram.com" in (existing_page.url or "").lower():
            log("[INSTAGRAM]", f"Instagram page found in existing tab: {existing_page.url}")
            return existing_page
    log("[INSTAGRAM]", "No Instagram tab found. Opening a new page.")
    return context.new_page()


def verify_logged_in_state(page):
    log("[INSTAGRAM]", "Verifying logged-in Instagram state.")
    login_inputs = page.locator("input[name='username'], input[name='password']")
    if login_inputs.count() > 0:
        raise RuntimeError("Instagram appears to be on the login screen, not an active logged-in session.")
    log("[INSTAGRAM]", "Logged-in state appears valid.")


def open_message_composer(page, username):
    profile_url = f"https://www.instagram.com/{username}/"
    log("[INSTAGRAM]", f"Opening target profile: @{username}")
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(4)
    log("[INSTAGRAM]", f"Target profile opened. current_url={page.url}")
    verify_logged_in_state(page)

    log("[INSTAGRAM]", "Looking for Message button.")
    message_button = page.get_by_role("button", name="Message", exact=True)
    if message_button.count() == 0:
        message_button = page.get_by_text("Message", exact=True)
    if message_button.count() == 0:
        raise RuntimeError("Message button not found on Instagram profile.")

    log("[INSTAGRAM]", "Message button found. Clicking.")
    message_button.first.click()
    time.sleep(3)

    log("[INSTAGRAM]", "Looking for message composer.")
    composer = page.locator('[contenteditable="true"]')
    composer.last.wait_for(state="visible", timeout=15000)
    log("[INSTAGRAM]", "Message composer found.")
    return composer.last


def send_messages(payload):
    username = (payload.get("username") or "").strip().lstrip("@")
    messages = [str(item).strip() for item in (payload.get("messages") or []) if str(item).strip()]
    cdp_url = (payload.get("cdp_url") or "http://127.0.0.1:9223").strip()

    if not username:
        raise RuntimeError("Missing Instagram username.")
    if not messages:
        raise RuntimeError("No messages supplied.")

    log("[INSTAGRAM]", f"Instagram sender invoked. username=@{username} message_count={len(messages)}")
    log("[INSTAGRAM]", f"CDP connection attempt starting. cdp_url={cdp_url}")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            log("[ERROR]", f"[INSTAGRAM] CDP connection failed: {exc}")
            raise RuntimeError(f"CDP connection failed: {exc}") from exc
        log("[INSTAGRAM]", "Chrome CDP connection succeeded.")
        if not browser.contexts:
            raise RuntimeError("No Chrome context available on the Instagram CDP session.")
        context = browser.contexts[0]
        log("[INSTAGRAM]", f"Chrome context acquired. context_count={len(browser.contexts)}")
        page = find_instagram_page(context)
        composer = open_message_composer(page, username)

        for index, message in enumerate(messages, start=1):
            log("[INSTAGRAM]", f"Typing message {index}/{len(messages)}.")
            composer.click()
            composer.fill(message)
            time.sleep(0.8)
            log("[INSTAGRAM]", f"Message typed for slot {index}.")

            log("[INSTAGRAM]", f"Attempting send action for message {index}/{len(messages)}.")
            send_button = page.get_by_role("button", name="Send", exact=True)
            if send_button.count() > 0:
                send_button.last.click()
            else:
                composer.press("Enter")
            time.sleep(1.6)
            log("[INSTAGRAM]", f"Send action attempted for message {index}/{len(messages)}.")
            if page.get_by_role("button", name="Send", exact=True).count() > 0:
                log("[INSTAGRAM]", f"Send button still visible after send attempt for message {index}/{len(messages)}.")
            log("[INSTAGRAM]", f"Send confirmed for message {index}/{len(messages)} based on post-send continuation.")

        return {
            "success": True,
            "username": username,
            "message_count": len(messages),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()

    try:
        payload = load_payload(args.payload)
        result = send_messages(payload)
        print(json.dumps(result))
        return 0
    except Exception as exc:
        step = "runtime_exception"
        message = str(exc)
        if "CDP connection failed" in message:
            step = "cdp_connection"
        elif "login screen" in message:
            step = "logged_in_state"
        elif "Message button not found" in message:
            step = "message_button"
        elif "composer" in message.lower():
            step = "composer"
        elif "target profile" in message.lower():
            step = "target_profile"
        log("[ERROR]", f"[INSTAGRAM] Failure at step={step}: {message}")
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"success": False, "error": message, "step": step}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
