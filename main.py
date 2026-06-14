import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Page
from dataclasses import dataclass, asdict
import pandas as pd
import argparse
import platform
import time
import os


@dataclass
class Place:
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    email: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    store_shopping: str = "No"
    in_store_pickup: str = "No"
    store_delivery: str = "No"
    place_type: str = ""
    opens_at: str = ""
    open_status: str = ""
    introduction: str = ""
    website_status: str = ""
    website_error_reason: str = ""
    website_confidence: int = -1


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )


def _check_website(browser, url: str, domain_cache: dict):
    """
    Opens the URL in a fresh browser context and returns (status, reason).
    Conservative two-attempt website checker.
    Returns (website_status, website_error_reason, website_confidence).
    Prefers false negatives over false positives — a working site is never
    flagged as broken on a single failure.

    Statuses and confidence:
        Working          →  0%
        Protected Website→ 50%
        Timeout          → 85%
        Server Error     → 90%
        Parked Domain    → 95%
        Domain Not Found →100%
    """
    _PARKED_PHRASES = [
        "this domain is for sale", "buy this domain", "sedo",
        "parked domain", "domain parking", "godaddy parked",
        "this website is coming soon", "coming soon",
        "purchase this domain", "domain may be for sale",
        "domain for sale",
    ]
    _PROTECTED_PHRASES = [
        "checking your browser", "just a moment", "cloudflare",
        "bot protection", "verify you are human",
        "please complete the security check",
        "enable javascript and cookies",
        "you need to enable javascript",
    ]

    norm_url = url.strip()
    if not norm_url.startswith(("http://", "https://")):
        norm_url = "https://" + norm_url

    try:
        parsed = urlparse(norm_url)
        domain = re.sub(r"^www\.", "", parsed.netloc.lower())
    except Exception:
        domain = norm_url

    if domain in domain_cache:
        return domain_cache[domain]

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def _single_attempt():
        ctx = None
        try:
            ctx = browser.new_context(ignore_https_errors=True, user_agent=_UA)
            pg = ctx.new_page()
            try:
                response = pg.goto(norm_url, timeout=10000, wait_until="networkidle")
            except Exception as exc:
                err = str(exc).lower()
                if "name_not_resolved" in err or "err_name_not_resolved" in err:
                    return ("Domain Not Found", "The domain does not exist.", 100)
                if "timed_out" in err or "err_timed_out" in err or "timeout" in err:
                    return ("Timeout", "The website did not respond within 10 seconds.", 85)
                if "connection_refused" in err or "err_connection_refused" in err:
                    return ("Server Error", "The server refused the connection.", 90)
                if "ssl" in err or "cert" in err:
                    return ("Server Error", "SSL/certificate error.", 85)
                return ("Broken", "The website failed to load.", 75)

            if response is None:
                return ("Broken", "The website did not return a response.", 75)

            code = response.status

            if code in (500, 502, 503) or (code >= 500):
                return ("Server Error", f"The website server returned an error (HTTP {code}).", 90)

            if code == 403:
                return ("Protected Website", "The website requires human verification (access restricted).", 50)

            try:
                body = pg.content().lower()
            except Exception:
                body = ""

            for phrase in _PROTECTED_PHRASES:
                if phrase in body:
                    return ("Protected Website", "The website requires browser verification (bot protection active).", 50)

            for phrase in _PARKED_PHRASES:
                if phrase in body:
                    return ("Parked Domain", "The domain is parked or for sale.", 95)

            if code < 400:
                return ("Working", "", 0)

            return ("Broken", f"The website returned an error (HTTP {code}).", 75)

        except Exception:
            return ("Broken", "Could not connect to the website.", 70)
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass

    # ── Attempt 1 ──
    res1 = _single_attempt()

    # Domain Not Found is definitive — no retry needed
    if res1[0] == "Domain Not Found":
        domain_cache[domain] = res1
        return res1

    # Working or Protected — conservative; accept immediately
    if res1[0] in ("Working", "Protected Website"):
        domain_cache[domain] = res1
        return res1

    # Any other failure → wait 2s and retry once
    time.sleep(2)
    res2 = _single_attempt()

    # If second attempt is Working or Protected, trust it
    if res2[0] in ("Working", "Protected Website"):
        final = res2
    # Both agree
    elif res1[0] == res2[0]:
        final = res1
    else:
        # Pick the more severe of the two results
        _sev = {"Domain Not Found": 6, "Parked Domain": 5,
                "Server Error": 4, "Timeout": 3, "Broken": 2}
        final = res1 if _sev.get(res1[0], 1) >= _sev.get(res2[0], 1) else res2

    domain_cache[domain] = final
    return final


def extract_text(page: Page, xpath: str) -> str:
    try:
        if page.locator(xpath).count() > 0:
            return page.locator(xpath).inner_text()
    except Exception as e:
        logging.warning(f"Failed to extract text for xpath {xpath}: {e}")
    return ""


def extract_place(page: Page) -> Place:
    name_xpath            = '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]'
    address_xpath         = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
    website_xpath         = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
    phone_number_xpath    = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
    reviews_count_xpath   = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span//span//span[@aria-label]'
    reviews_average_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span[@aria-hidden]'
    info1                 = '//div[@class="LTs0Rc"][1]'
    info2                 = '//div[@class="LTs0Rc"][2]'
    info3                 = '//div[@class="LTs0Rc"][3]'
    opens_at_xpath        = '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]'
    opens_at_xpath2       = '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[2]'
    place_type_xpath      = '//div[@class="LBgpqf"]//button[@class="DkEaL "]'
    intro_xpath           = '//div[@class="WeS02d fontBodyMedium"]//div[@class="PYvSYb "]'

    place = Place()
    place.name         = extract_text(page, name_xpath)
    place.address      = extract_text(page, address_xpath)
    place.website      = extract_text(page, website_xpath)
    place.phone_number = extract_text(page, phone_number_xpath)
    place.place_type   = extract_text(page, place_type_xpath)
    place.introduction = extract_text(page, intro_xpath) or "None Found"

    # Email (appears as a mailto: link on some listings)
    try:
        email_el = page.locator('//a[contains(@href,"mailto:")]')
        if email_el.count() > 0:
            href = email_el.first.get_attribute("href") or ""
            place.email = href.replace("mailto:", "").strip()
    except Exception as e:
        logging.warning(f"Failed to extract email: {e}")

    # Open / Closed status
    open_xpaths = [
        '//div[contains(@class,"o0Svhf")]//span',
        '//span[@class="ZDu9vd"]',
        '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[1]',
    ]
    for ox in open_xpaths:
        raw = extract_text(page, ox)
        if raw:
            low = raw.lower()
            if "open" in low:
                place.open_status = "Open"
            elif "close" in low or "cerr" in low:
                place.open_status = "Closed"
            else:
                place.open_status = raw.strip()[:30]
            break

    # Reviews Count
    reviews_count_raw = extract_text(page, reviews_count_xpath)
    if reviews_count_raw:
        try:
            temp = reviews_count_raw.replace('\xa0', '').replace('(', '').replace(')', '').replace(',', '')
            place.reviews_count = int(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews count: {e}")

    # Reviews Average
    reviews_avg_raw = extract_text(page, reviews_average_xpath)
    if reviews_avg_raw:
        try:
            temp = reviews_avg_raw.replace(' ', '').replace(',', '.')
            place.reviews_average = float(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews average: {e}")

    # Store Info
    for info_xpath in [info1, info2, info3]:
        info_raw = extract_text(page, info_xpath)
        if info_raw:
            temp = info_raw.split('·')
            if len(temp) > 1:
                check = temp[1].replace("\n", "").lower()
                if 'shop' in check:
                    place.store_shopping = "Yes"
                if 'pickup' in check:
                    place.in_store_pickup = "Yes"
                if 'delivery' in check:
                    place.store_delivery = "Yes"

    # Opens At
    opens_at_raw = extract_text(page, opens_at_xpath)
    if opens_at_raw:
        opens = opens_at_raw.split('⋅')
        place.opens_at = (opens[1] if len(opens) > 1 else opens_at_raw).replace("\u202f", "")
    else:
        opens_at2_raw = extract_text(page, opens_at_xpath2)
        if opens_at2_raw:
            opens = opens_at2_raw.split('⋅')
            place.opens_at = (opens[1] if len(opens) > 1 else opens_at2_raw).replace("\u202f", "")

    return place


def scrape_places(
    search_for: str,
    total: int,
    progress_callback=None,
    stop_event=None,
    pause_event=None,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Place]:
    """
    Scrape Google Maps for businesses matching `search_for`.

    Args:
        search_for:         Search query.
        total:              Maximum number of listings to attempt.
        progress_callback:  Called as callback(valid_count, total_listings, place, extras_dict).
        stop_event:         threading.Event — when set, halts the scrape.
        pause_event:        threading.Event — when set, pauses inside the loop.
        filters:            Dict with optional keys:
                              min_rating, min_reviews,
                              require_web, require_phone, require_email.
    Returns:
        List of Place objects that passed deduplication and filters.
    """
    setup_logging()
    places: List[Place] = []
    seen_keys: set = set()
    domain_cache: dict = {}
    dup_count = 0
    filter_count = 0
    valid_count = 0

    with sync_playwright() as p:
        if platform.system() == "Windows":
            browser_path = r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            browser = p.chromium.launch(executable_path=browser_path, headless=True)
        else:
            import shutil
            import glob as _glob
            chromium_exec = shutil.which("chromium") or shutil.which("chromium-browser")
            if not chromium_exec:
                nix_candidates = _glob.glob("/nix/store/*-chromium-*/bin/chromium")
                chromium_exec = nix_candidates[0] if nix_candidates else None
            if chromium_exec:
                browser = p.chromium.launch(
                    executable_path=chromium_exec,
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
            else:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )

        page = browser.new_page()
        try:
            page.goto("https://www.google.com/maps/@32.9817464,70.1930781,3.67z?", timeout=60000)
            page.wait_for_timeout(1000)
            page.locator("//form[contains(@jsaction,'searchboxFormSubmit')]//input[@name='q']").fill(search_for)
            page.keyboard.press("Enter")
            page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]')
            page.hover('//a[contains(@href, "https://www.google.com/maps/place")]')

            # ── Automatic pagination: scroll until we have enough listings ──
            previously_counted = 0
            while True:
                if stop_event and stop_event.is_set():
                    break
                page.mouse.wheel(0, 10000)
                page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]')
                found = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').count()
                logging.info(f"Currently Found: {found}")
                if found >= total:
                    break
                if found == previously_counted:
                    logging.info("Arrived at all available results")
                    break
                previously_counted = found

            listings = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').all()[:total]
            listings = [listing.locator("xpath=..") for listing in listings]
            logging.info(f"Total listings to process: {len(listings)}")

            for idx, listing in enumerate(listings):
                # ── Stop check ──
                if stop_event and stop_event.is_set():
                    logging.info("Stop requested — halting scrape.")
                    break

                # ── Pause support ──
                if pause_event and pause_event.is_set():
                    logging.info("Scrape paused...")
                    while pause_event.is_set():
                        if stop_event and stop_event.is_set():
                            break
                        time.sleep(0.3)
                    if not (stop_event and stop_event.is_set()):
                        logging.info("Scrape resumed.")

                try:
                    listing.click()
                    page.wait_for_selector(
                        '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]',
                        timeout=10000,
                    )
                    time.sleep(1.5)
                    place = extract_place(page)

                    if not place.name:
                        logging.warning(f"No name found for listing {idx + 1}, skipping.")
                        continue

                    # ── Deduplication ──
                    dedup_key = (place.name.lower().strip(), place.address.lower().strip())
                    if dedup_key in seen_keys:
                        logging.info(f"Duplicate skipped: {place.name}")
                        dup_count += 1
                        continue
                    seen_keys.add(dedup_key)

                    # ── Website status check ──
                    ws_raw = (place.website or "").strip()
                    ws_has_url = bool(ws_raw and ws_raw != "-" and ("." in ws_raw or "http" in ws_raw.lower()))
                    if ws_has_url:
                        try:
                            ws_status, ws_reason, ws_conf = _check_website(browser, ws_raw, domain_cache)
                            place.website_status = ws_status
                            place.website_error_reason = ws_reason
                            place.website_confidence = ws_conf
                            logging.info(f"Website check [{ws_status} {ws_conf}%]: {ws_raw}")
                        except Exception as exc:
                            logging.warning(f"Website check failed for {ws_raw}: {exc}")

                    # ── Filters ──
                    if filters:
                        skip = False
                        min_rating = filters.get("min_rating")
                        if min_rating is not None:
                            if place.reviews_average is None or place.reviews_average < min_rating:
                                filter_count += 1
                                skip = True

                        if not skip:
                            min_reviews = filters.get("min_reviews")
                            if min_reviews is not None:
                                if place.reviews_count is None or place.reviews_count < min_reviews:
                                    filter_count += 1
                                    skip = True

                        if not skip and filters.get("require_web") and not place.website:
                            filter_count += 1
                            skip = True

                        if not skip and filters.get("no_website"):
                            ws = (place.website or "").strip()
                            has_web = bool(ws and ws != "-" and ("." in ws or "http" in ws.lower()))
                            if has_web:
                                filter_count += 1
                                skip = True

                        if not skip and filters.get("only_broken_websites"):
                            _broken = {"Timeout", "Domain Not Found", "Parked Domain", "Server Error"}
                            if place.website_status not in _broken:
                                filter_count += 1
                                skip = True

                        if not skip and filters.get("require_phone") and not place.phone_number:
                            filter_count += 1
                            skip = True

                        if not skip and filters.get("require_email") and not place.email:
                            filter_count += 1
                            skip = True

                        if skip:
                            continue

                    valid_count += 1
                    places.append(place)

                    if progress_callback:
                        progress_callback(
                            valid_count,
                            len(listings),
                            place,
                            {
                                "scraped_idx": idx + 1,
                                "dup_skipped": dup_count,
                                "filtered": filter_count,
                            },
                        )

                except Exception as e:
                    logging.warning(f"Failed to extract listing {idx + 1}: {e}")

        finally:
            browser.close()

    return places


def save_places_to_csv(places: List[Place], output_path: str = "result.csv", append: bool = False):
    df = pd.DataFrame([asdict(place) for place in places])
    if not df.empty:
        for column in df.columns:
            if df[column].nunique() == 1:
                df.drop(column, axis=1, inplace=True)
        file_exists = os.path.isfile(output_path)
        mode = "a" if append else "w"
        header = not (append and file_exists)
        df.to_csv(output_path, index=False, mode=mode, header=header)
        logging.info(f"Saved {len(df)} places to {output_path} (append={append})")
    else:
        logging.warning("No data to save. DataFrame is empty.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--search",  type=str, help="Search query for Google Maps")
    parser.add_argument("-t", "--total",   type=int, help="Total number of results to scrape")
    parser.add_argument("-o", "--output",  type=str, default="result.csv", help="Output CSV file path")
    parser.add_argument("--append",        action="store_true", help="Append to existing file")
    parser.add_argument("--min-rating",    type=float, help="Minimum rating filter")
    parser.add_argument("--min-reviews",   type=int,   help="Minimum reviews filter")
    parser.add_argument("--require-web",   action="store_true", help="Only include results with a website")
    parser.add_argument("--require-phone", action="store_true", help="Only include results with a phone")
    parser.add_argument("--require-email", action="store_true", help="Only include results with an email")
    args = parser.parse_args()

    filters = {}
    if args.min_rating:   filters["min_rating"]    = args.min_rating
    if args.min_reviews:  filters["min_reviews"]   = args.min_reviews
    if args.require_web:  filters["require_web"]   = True
    if args.require_phone:filters["require_phone"] = True
    if args.require_email:filters["require_email"] = True

    search_for  = args.search or "turkish stores in toronto Canada"
    total       = args.total or 1
    output_path = args.output
    append      = args.append

    places = scrape_places(search_for, total, filters=filters or None)
    save_places_to_csv(places, output_path, append=append)


if __name__ == "__main__":
    main()
