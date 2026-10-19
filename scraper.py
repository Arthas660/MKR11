from playwright.sync_api import sync_playwright, TimeoutError
from urllib.parse import urljoin
from pathlib import Path
import csv
import re

BASE_URL = "https://ek.ua"
CATALOG_URL = BASE_URL + "/ua/list/298/"
FILENAME = "ek_laptops.csv"


def get_text(parent, selector):
    element = parent.locator(selector).first
    if element.count() == 0:
        return ""
    return " ".join((element.text_content() or "").split())


def open_page(page, url, selector):
    page.wait_for_timeout(1500)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.locator(selector).first.wait_for(state="attached", timeout=30000)


def parse_laptop(page, url):
    open_page(page, url, ".conf-prices-price-big")
    try:
        page.locator(".desc-short-prices .m-c-f2 .m-s-f3").first.wait_for(
            state="attached", timeout=10000
        )
    except TimeoutError:
        return None

    title = get_text(page, "h1")
    description = "; ".join(
        " ".join(
            (
                element.get_attribute("title")
                or element.text_content()
                or ""
            ).split()
        )
        for element in page.locator(".desc-short-prices .m-c-f2 .m-s-f3").all()
    )
    if not title or not description:
        return None

    for price_cell in page.locator(".conf-prices-price-big").all():
        row = price_cell.locator("xpath=ancestor::tr[1]")
        shop = get_text(row, ".it-shop")
        city_text = get_text(row, ".it-deliv")

        if not shop:
            continue

        city = None
        city_match = re.search(
            r"\b((?:з|із|зі)\s+.+)$", city_text, flags=re.I
        )

        if city_match:
            city = city_match.group(1).strip().rstrip(").")
        elif city_text and "достав" not in city_text.lower():
            city = city_text.strip("() ") or None

        raw_price = " ".join((price_cell.text_content() or "").split())

        price_match = re.search(
            r"(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:грн\.?|UAH|₴)",
            raw_price,
            flags=re.I,
        )

        value = price_match.group(1) if price_match else raw_price
        value = re.sub(r"\s+", "", value).replace(",", ".")

        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
            continue

        price = float(value)

        if price <= 0:
            continue

        return {
            "Назва": title,
            "Опис": description,
            "Ціна": price,
            "Місто": city,
            "Магазин": shop,
        }

    return None


def parse_ek_playwright(pages_to_scrape=5):
    products = []
    seen = set()
    skipped = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="uk-UA")

        catalog = context.new_page()
        details = context.new_page()

        try:
            for number in range(pages_to_scrape):
                url = (
                    CATALOG_URL
                    if number == 0
                    else f"{CATALOG_URL}{number}/"
                )

                print(f"\nСторінка {number + 1}: {url}")
                open_page(catalog, url, ".model-short-div")

                links = catalog.locator(
                    ".model-short-div .model-conf-title > a[href], "
                    ".model-short-div a.model-short-title, "
                    ".model-short-div .model-short-info a[id^='product_']"
                ).all()

                series_urls = []

                for link in links:
                    href = link.get_attribute("href")

                    if href:
                        series_url = urljoin(BASE_URL, href).split("#")[0]

                        if series_url not in series_urls:
                            series_urls.append(series_url)

                if not series_urls:
                    print("Посилань немає. Перевір сторінку в браузері.")
                    break

                for series_url in series_urls:
                    try:
                        open_page(
                            details,
                            series_url,
                            ".desc-short-prices .m-c-f2",
                        )

                        laptop_urls = []

                        for link in details.locator(
                            ".conf-table a.conf-name[href]"
                        ).all():
                            href = link.get_attribute("href")

                            if href:
                                laptop_url = urljoin(
                                    BASE_URL, href
                                ).split("#")[0]

                                if laptop_url not in laptop_urls:
                                    laptop_urls.append(laptop_url)

                        if not laptop_urls:
                            laptop_urls = [series_url]

                        for laptop_url in laptop_urls:
                            if laptop_url in seen:
                                continue

                            seen.add(laptop_url)

                            try:
                                product = parse_laptop(details, laptop_url)

                                if product:
                                    products.append(product)

                                    print(
                                        f"{product['Назва']} | "
                                        f"{product['Ціна']} грн | "
                                        f"{product['Місто']} | "
                                        f"{product['Магазин']}"
                                    )
                                else:
                                    skipped += 1
                                    print(
                                        "Немає назви, опису або "
                                        "пропозиції з магазином і ціною: "
                                        f"{laptop_url}"
                                    )

                            except TimeoutError:
                                skipped += 1
                                print(f"Не завантажилось: {laptop_url}")

                    except TimeoutError:
                        print(f"Не завантажилась серія: {series_url}")

        finally:
            # Збереження у CSV
            fieldnames = ["Назва", "Опис", "Ціна", "Місто", "Магазин"]
            with open(FILENAME, mode="w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(products)

            browser.close()
            print(f"\nЗбережено: {len(products)}")
            print(f"Пропущено ноутбуків: {skipped}")
            print(f"Файл: {Path(FILENAME).resolve()}")


if __name__ == "__main__":
    parse_ek_playwright(pages_to_scrape=1)