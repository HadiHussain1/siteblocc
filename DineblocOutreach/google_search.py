from playwright.sync_api import sync_playwright

SEARCH = "Merrifield Kebab House"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="google_profile",
        channel="chrome",
        headless=False,
        viewport={"width": 1400, "height": 900},
    )

    page = context.pages[0] if context.pages else context.new_page()

    # Go to Google
    page.goto("https://www.google.com")

    # If a consent button appears, click it
    try:
        page.get_by_role("button", name="Accept all").click(timeout=3000)
    except:
        pass

    # Search
    page.locator("textarea[name='q']").fill(SEARCH)
    page.locator("textarea[name='q']").press("Enter")

    # Wait for results
    page.wait_for_load_state("networkidle")

    print("Search complete.")

    input("Press ENTER to close...")

    context.close()