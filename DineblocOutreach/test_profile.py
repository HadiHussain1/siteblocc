from playwright.sync_api import sync_playwright
import time

print("Connecting to Dinebloc Outreach Chrome...")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")

    print("Connected successfully!")

    context = browser.contexts[0]

    print(f"Contexts found: {len(browser.contexts)}")
    print(f"Pages found: {len(context.pages)}")

    # Find an existing Google page if one exists.
    page = None

    for existing_page in context.pages:
        print("Existing page:", existing_page.url)

        if "google.com" in existing_page.url:
            page = existing_page
            break

    # If there isn't already a Google tab, create one.
    if page is None:
        print("No Google tab found.")
        print("Creating a new browser tab...")

        page = context.new_page()

        # Use the browser's normal address-bar navigation rather than
        # Playwright's page.goto(), which can be aborted when attached
        # to an existing Chrome session.
        page.evaluate("window.location.href = 'https://www.google.com'")

    print("Using page:", page.url)

    # Give Google time to render.
    time.sleep(5)

    print("Current URL:", page.url)
    print("TITLE:", page.title())

    print("Looking for Google search box...")

    search_box = None

    selectors = [
        'textarea[name="q"]',
        'input[name="q"]',
        'textarea[aria-label*="Search"]',
        'input[aria-label*="Search"]',
        'textarea[title*="Search"]',
        'input[title*="Search"]',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first

            if locator.is_visible(timeout=3000):
                search_box = locator
                print("Found search box:", selector)
                break

        except Exception:
            pass

    if search_box is None:
        print("Could not find the Google search box.")
        print("Current URL:", page.url)
        print("TITLE:", page.title())

        input("Press ENTER to close...")
        raise SystemExit

    print("Clicking search box...")

    search_box.click()

    time.sleep(1)

    print("Typing search...")

    search_box.fill("kebab sunshine")

    time.sleep(1)

    print("Search text entered.")

    print("Pressing ENTER...")

    search_box.press("Enter")

    time.sleep(6)

    print("Search submitted!")
    print("Final URL:", page.url)
    print("Final TITLE:", page.title())

    input("Press ENTER to close...")