from playwright.sync_api import sync_playwright
import csv
import os
import time
import re

SEARCH = "kebab Sunshine Melbourne"

print("=" * 70)
print("DINEBLOC OUTREACH - GOOGLE LEAD DISCOVERY")
print("=" * 70)

os.makedirs("output", exist_ok=True)

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized"]
    )

    context = browser.new_context(
        viewport=None
    )

    page = context.new_page()

    print("\nOpening Google...")

    page.goto(
        "https://www.google.com",
        wait_until="domcontentloaded",
        timeout=30000
    )

    time.sleep(3)

    print("Google opened.")
    print("\nSearching:", SEARCH)

    search_box = page.locator('textarea[name="q"]')

    if not search_box.is_visible(timeout=10000):
        search_box = page.locator('input[name="q"]')

    search_box.click()
    search_box.fill(SEARCH)
    search_box.press("Enter")

    print("Search submitted.")

    time.sleep(5)

    # ---------------------------------------------------------
    # CAPTCHA / verification
    # ---------------------------------------------------------

    print("\nIf Google shows a CAPTCHA, complete it manually.")
    print("Waiting for the Google results page...")

    input(
        "\nWhen the normal Google results are visible, "
        "press ENTER here to continue..."
    )

    # ---------------------------------------------------------
    # Extract Google search result blocks
    # ---------------------------------------------------------

    print("\nExtracting search results...")

    results = []

    # Google organic results
    blocks = page.locator("div.MjjYud")

    count = blocks.count()

    print(f"Found {count} potential result blocks.")

    for i in range(count):

        block = blocks.nth(i)

        try:
            text = block.inner_text(timeout=2000).strip()
        except:
            continue

        if not text:
            continue

        # Get links inside the result
        links = block.locator("a")

        href = None
        title = None

        for j in range(min(links.count(), 5)):

            try:
                link = links.nth(j)

                link_text = link.inner_text(timeout=1000).strip()
                link_href = link.get_attribute("href")

                if (
                    link_text
                    and link_href
                    and link_href.startswith("http")
                ):
                    title = link_text
                    href = link_href
                    break

            except:
                continue

        if not title:
            continue

        # Ignore Google navigation
        if "google.com" in href:
            continue

        # Avoid duplicate results
        if any(r["url"] == href for r in results):
            continue

        # Try to identify likely business names
        lines = [
            x.strip()
            for x in text.splitlines()
            if x.strip()
        ]

        business_name = lines[0] if lines else title

        # Keep useful information from the result
        results.append({
            "business_name": business_name,
            "title": title,
            "url": href,
            "raw_text": text
        })

    # ---------------------------------------------------------
    # Save results
    # ---------------------------------------------------------

    csv_path = "output/businesses.csv"

    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "business_name",
                "title",
                "url",
                "raw_text"
            ]
        )

        writer.writeheader()
        writer.writerows(results)

    # ---------------------------------------------------------
    # Display
    # ---------------------------------------------------------

    print("\n" + "=" * 70)
    print(f"FOUND {len(results)} RESULTS")
    print("=" * 70)

    for i, result in enumerate(results, 1):

        print(f"\n{i}. {result['business_name']}")
        print(f"   {result['url']}")

        # Show a short preview
        preview = re.sub(
            r"\s+",
            " ",
            result["raw_text"]
        )

        if len(preview) > 250:
            preview = preview[:250] + "..."

        print(f"   {preview}")

    print("\n" + "=" * 70)
    print(f"Saved to: {csv_path}")
    print("=" * 70)

    input("\nPress ENTER to close...")

    browser.close()