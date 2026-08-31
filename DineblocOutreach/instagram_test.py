from playwright.sync_api import sync_playwright
import time

# ============================================================
# TEST SETTINGS
# ============================================================

USERNAME = "instagram"

MESSAGE = "Hey! This is a test message from Dinebloc Outreach."


# ============================================================
# CONNECT
# ============================================================

print("Connecting to Dinebloc Instagram Chrome...")

with sync_playwright() as p:

    browser = p.chromium.connect_over_cdp(
        "http://127.0.0.1:9223"
    )

    print("Connected successfully!")

    context = browser.contexts[0]

    page = None

    for existing_page in context.pages:
        if "instagram.com" in existing_page.url.lower():
            page = existing_page
            break

    if page is None:
        page = context.new_page()

    # ========================================================
    # OPEN PROFILE
    # ========================================================

    profile_url = f"https://www.instagram.com/{USERNAME}/"

    print(f"Opening Instagram profile: @{USERNAME}")

    page.goto(
        profile_url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    time.sleep(5)

    print("Current URL:", page.url)

    # ========================================================
    # MESSAGE BUTTON
    # ========================================================

    print("Looking for Message button...")

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
        print("ERROR: Message button not found.")
        input("Press ENTER to finish...")
        raise SystemExit

    print("Message button found.")

    message_button.first.click()

    print("Message window opened.")

    time.sleep(4)

    # ========================================================
    # FIND MESSAGE COMPOSER
    # ========================================================

    print("Looking for message composer...")

    composer = page.locator(
        '[contenteditable="true"]'
    )

    try:
        composer.last.wait_for(
            state="visible",
            timeout=15000
        )
    except Exception:
        print("ERROR: Message composer not found.")
        input("Press ENTER to finish...")
        raise SystemExit

    print("Message composer found.")

    # ========================================================
    # TYPE MESSAGE
    # ========================================================

    composer.last.click()

    composer.last.fill(MESSAGE)

    print("Message typed.")

    time.sleep(2)

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    print("Looking for Send button...")

    send_button = page.get_by_role(
        "button",
        name="Send",
        exact=True
    )

    if send_button.count() > 0:

        print("Send button found.")
        send_button.last.click()

    else:

        print("Send button not found.")
        print("Using Enter to send...")

        composer.last.press("Enter")

    time.sleep(4)

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

    input("Press ENTER to finish...")