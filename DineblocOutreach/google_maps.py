from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="google_maps_profile",
        channel="chrome",
        headless=False,
    )

    page = context.pages[0] if context.pages else context.new_page()

    page.goto("https://www.google.com/maps")

    input("Wait until Maps loads, then press ENTER...")

    print(page.content())

    input("Press ENTER to close...")