from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="dinebloc_profile",
        channel="chrome",
        headless=False,
    )

    page = context.new_page()
    page.goto("https://accounts.google.com")

    print("Log into your Google account.")
    input("Press ENTER after you're completely logged in...")

    context.close()