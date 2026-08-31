from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="instagram_profile",
        headless=False,
        channel="chrome",
        viewport={"width": 1400, "height": 900},
    )

    page = context.pages[0] if context.pages else context.new_page()

    page.goto("https://www.instagram.com", wait_until="networkidle")

    print("Instagram opened.")

    input("Press ENTER to close...")

    context.close()