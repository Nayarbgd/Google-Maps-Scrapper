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
import requests as _requests
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


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
    Two-stage website checker.

    Stage 1 — HTTP (requests library, no browser):
        HEAD request first; fall back to GET if HEAD fails or returns 405/501.
        Timeout: 20 s. Follows redirects. Uses a real browser User-Agent.
        HTTP 200 / 301 / 302 / 307 / 308 / 403 / any 2xx-3xx → accessible, stop.
        HTTP 503                                               → ambiguous, go to Stage 2.
        DNS fail / connection refused / 5xx / timeout         → go to Stage 2.

    Stage 2 — Playwright (only when Stage 1 did not confirm accessible):
        Two independent attempts. Fresh browser context each time.
        Timeout: 20 s, wait_until="networkidle".
        If either attempt shows the site is accessible → return Working/Protected.

    Final classification — ONLY when BOTH stages fail:
        Both must agree on the failure type for a broken status to be assigned.
        Any ambiguity or mixed signals → return Working (conservative fallback).

    Returns (website_status, website_error_reason, website_confidence).

    Statuses:
        Working                  →  0 %
        Accessible but Protected →  0 %
        Domain Not Found         → 100 %
        Parked Domain            → 100 %
        Server Unreachable       →  95 %
        Server Error             →  90 %
    """
    _PARKED_PHRASES = [
        "this domain is for sale", "buy this domain", "sedo",
        "parked domain", "domain parking", "godaddy parked",
        "hugedomains.com", "dan.com/buy",
        "purchase this domain", "domain may be for sale",
        "domain for sale",
    ]
    _PROTECTED_PHRASES = [
        "checking your browser", "just a moment",
        "bot protection", "verify you are human",
        "please complete the security check",
        "enable javascript and cookies",
        "you need to enable javascript",
        "ddos protection by", "are you a robot",
        "please verify you are a human",
        "one more step", "ray id",
    ]
    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    _HTTP_HEADERS = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    # ── URL normalisation ──────────────────────────────────────────────────────
    norm_url = url.strip()
    if not norm_url.startswith(("http://", "https://")):
        norm_url = "https://" + norm_url

    try:
        parsed    = urlparse(norm_url)
        domain    = re.sub(r"^www\.", "", parsed.netloc.lower())
        suffix    = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
        https_url = "https://" + parsed.netloc + suffix
        http_url  = "http://"  + parsed.netloc + suffix
    except Exception:
        domain    = norm_url
        https_url = norm_url
        http_url  = norm_url.replace("https://", "http://", 1)

    if domain in domain_cache:
        return domain_cache[domain]

    # ── Stage 1: HTTP check (requests) ────────────────────────────────────────
    def _http_check(check_url):
        """
        Try HEAD first; fall back to GET.
        Returns dict: raw | code | detail
          raw values: working | protected | parked |
                      dns_fail | conn_refused | s1_503 | s1_server_error | timeout | error
        """
        kw = dict(headers=_HTTP_HEADERS, timeout=20, allow_redirects=True, verify=False)

        # HEAD attempt
        head_code = None
        try:
            rh = _requests.head(check_url, **kw)
            if rh.status_code not in (405, 501):
                head_code = rh.status_code
        except Exception:
            pass  # HEAD unsupported or network error — fall through to GET

        # HEAD gave a clear accessible answer → return immediately (no body needed)
        if head_code is not None:
            if head_code in (200, 301, 302, 307, 308) or (200 <= head_code < 400):
                return {"raw": "working", "code": head_code,
                        "detail": f"HTTP {head_code} (HEAD) — accessible"}
            if head_code == 403:
                return {"raw": "protected", "code": head_code,
                        "detail": "HTTP 403 (HEAD) — access restricted, accessible to humans"}

        # GET request (always run when HEAD was inconclusive or returned 4xx/5xx)
        try:
            rg   = _requests.get(check_url, **kw, stream=True)
            code = rg.status_code
            # Read up to 8 KB for phrase analysis; close stream immediately after
            raw_bytes = b""
            try:
                for chunk in rg.iter_content(chunk_size=8192):
                    raw_bytes += chunk
                    break
            except Exception:
                pass
            finally:
                rg.close()
            body = raw_bytes.decode("utf-8", errors="ignore").lower()

        except _requests.exceptions.ConnectionError as exc:
            err = str(exc).lower()
            if any(k in err for k in (
                "nodename", "name resolution", "getaddrinfo",
                "name or service not known", "nxdomain",
                "temporary failure in name resolution",
                "failed to resolve", "[errno 11001]", "[errno -2]",
                "[errno -3]", "[errno -5]",
            )):
                return {"raw": "dns_fail", "code": None,
                        "detail": "DNS resolution failed — domain does not exist"}
            return {"raw": "conn_refused", "code": None,
                    "detail": "Connection refused or network unreachable"}
        except _requests.exceptions.Timeout:
            return {"raw": "timeout", "code": None,
                    "detail": "HTTP request timed out after 20 seconds"}
        except Exception as exc:
            return {"raw": "error", "code": None,
                    "detail": f"HTTP request error: {str(exc)[:120]}"}

        # ── Classify GET response ──────────────────────────────────────────
        # Explicitly accessible — check body first for parked/protected signals
        if code in (200, 301, 302, 307, 308) or (200 <= code < 400):
            for phrase in _PARKED_PHRASES:
                if phrase in body:
                    return {"raw": "parked", "code": code,
                            "detail": "Domain is parked or for sale (detected in page content)"}
            for phrase in _PROTECTED_PHRASES:
                if phrase in body:
                    return {"raw": "protected", "code": code,
                            "detail": "Bot-protection or access-restriction page — accessible to humans"}
            return {"raw": "working", "code": code,
                    "detail": f"HTTP {code} — accessible"}

        if code == 403:
            return {"raw": "protected", "code": code,
                    "detail": "HTTP 403 — access restricted, accessible to humans"}

        # 503 — never immediately broken; might be Cloudflare / Wix / Squarespace
        if code == 503:
            for phrase in _PROTECTED_PHRASES:
                if phrase in body:
                    return {"raw": "protected", "code": code,
                            "detail": "HTTP 503 with bot-protection page — accessible to humans"}
            for phrase in _PARKED_PHRASES:
                if phrase in body:
                    return {"raw": "parked", "code": code,
                            "detail": "Domain is parked or for sale"}
            return {"raw": "s1_503", "code": code,
                    "detail": "HTTP 503 — possible CDN/protection page; needs Playwright confirmation"}

        # Other 5xx
        if code >= 500:
            return {"raw": "s1_server_error", "code": code,
                    "detail": f"HTTP {code} — server error"}

        # 404
        if code == 404:
            return {"raw": "s1_server_error", "code": code,
                    "detail": "HTTP 404 — resource not found"}

        # Other 4xx (not 403) — ambiguous, do not treat as broken
        return {"raw": "error", "code": code,
                "detail": f"HTTP {code} — ambiguous, not treated as broken"}

    # Run Stage 1 on https; if the error is a network-level failure also try http
    s1 = _http_check(https_url)
    if s1["raw"] in ("error", "timeout", "conn_refused") and https_url != http_url:
        s1_http = _http_check(http_url)
        if s1_http["raw"] in ("working", "protected", "parked"):
            s1 = s1_http  # http was reachable — use that result

    logging.info(
        f"WS-check S1 ({https_url}): raw={s1['raw']} "
        f"code={s1['code']} — {s1['detail']}"
    )

    # Stage 1 confirmed accessible → done
    if s1["raw"] == "working":
        result = ("Working", s1["detail"], 0)
        _log_debug(domain, [s1], "Working")
        domain_cache[domain] = result
        return result

    if s1["raw"] == "protected":
        result = ("Accessible but Protected", s1["detail"], 0)
        _log_debug(domain, [s1], "Accessible but Protected")
        domain_cache[domain] = result
        return result

    if s1["raw"] == "parked":
        result = ("Parked Domain", "The domain is parked or for sale.", 100)
        _log_debug(domain, [s1], "Parked Domain")
        domain_cache[domain] = result
        return result

    # ── Stage 2: Playwright (Stage 1 did not confirm accessible) ──────────────
    def _pw_attempt(attempt_url):
        """
        Single Playwright attempt with networkidle and 20 s timeout.
        Returns dict: raw | code | detail
          raw values: working | protected | parked | dns_fail | conn_refused |
                      p2_server_error | p2_503 | timeout | error
        """
        ctx = None
        try:
            ctx = browser.new_context(ignore_https_errors=True, user_agent=_UA)
            pg  = ctx.new_page()
            try:
                response = pg.goto(attempt_url, timeout=25000, wait_until="domcontentloaded")
            except Exception as exc:
                err = str(exc).lower()
                if any(k in err for k in ("name_not_resolved", "nxdomain", "dns_probe",
                                          "err_name_not_resolved")):
                    return {"raw": "dns_fail", "code": None,
                            "detail": "Playwright: DNS resolution failed"}
                if any(k in err for k in ("connection_refused", "err_connection_refused")):
                    return {"raw": "conn_refused", "code": None,
                            "detail": "Playwright: connection refused"}
                if any(k in err for k in ("timed_out", "err_timed_out", "timeout")):
                    return {"raw": "p2_timeout", "code": None,
                            "detail": "Playwright: page did not reach domcontentloaded within 25 s"}
                return {"raw": "error", "code": None,
                        "detail": f"Playwright error: {str(exc)[:120]}"}

            if response is None:
                return {"raw": "error", "code": None, "detail": "Playwright: no response object"}

            code = response.status

            # Redirects → working
            if code in (301, 302, 307, 308):
                return {"raw": "working", "code": code,
                        "detail": f"Playwright: redirect ({code}) — accessible"}

            # 403 → protected
            if code == 403:
                return {"raw": "protected", "code": code,
                        "detail": "Playwright: HTTP 403 — accessible to humans"}

            # Read rendered body
            try:
                body = pg.content().lower()
            except Exception:
                body = ""

            # Bot protection / captcha → protected
            for phrase in _PROTECTED_PHRASES:
                if phrase in body:
                    return {"raw": "protected", "code": code,
                            "detail": "Playwright: bot-protection or browser-check page — accessible to humans"}

            # Parked domain
            for phrase in _PARKED_PHRASES:
                if phrase in body:
                    return {"raw": "parked", "code": code,
                            "detail": "Playwright: domain is parked or for sale"}

            # 503 — keep separate from hard server errors
            if code == 503:
                return {"raw": "p2_503", "code": code,
                        "detail": "Playwright: HTTP 503"}

            # Hard server errors
            if code in (500, 502, 504) or code >= 500:
                return {"raw": "p2_server_error", "code": code,
                        "detail": f"Playwright: server error (HTTP {code})"}

            if code == 404:
                return {"raw": "p2_server_error", "code": code,
                        "detail": "Playwright: HTTP 404 not found"}

            # Successful load
            if code < 400:
                return {"raw": "working", "code": code,
                        "detail": f"Playwright: loaded (HTTP {code})"}

            # Other 4xx — ambiguous
            return {"raw": "error", "code": code,
                    "detail": f"Playwright: HTTP {code} — ambiguous"}

        except Exception as exc:
            return {"raw": "error", "code": None,
                    "detail": f"Playwright outer error: {str(exc)[:120]}"}
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass

    # Two Playwright attempts
    s2_results = []
    for pw_num in range(1, 3):
        s2 = _pw_attempt(https_url)
        s2_results.append(s2)
        logging.info(
            f"WS-check S2 attempt {pw_num}/2 ({https_url}): "
            f"raw={s2['raw']} code={s2['code']} — {s2['detail']}"
        )
        # Playwright found the site accessible → override Stage 1 failure
        if s2["raw"] in ("working", "protected"):
            status = "Working" if s2["raw"] == "working" else "Accessible but Protected"
            result = (status, f"Accessible via browser — {s2['detail']}", 0)
            _log_debug(domain, [s1] + s2_results, status)
            domain_cache[domain] = result
            return result

    # ── Both stages failed — final classification ──────────────────────────────
    all_results = [s1] + s2_results

    # Parked detected by Playwright
    if any(r["raw"] == "parked" for r in s2_results):
        result = ("Parked Domain", "The domain is parked or for sale.", 100)
        _log_debug(domain, all_results, "Parked Domain")
        domain_cache[domain] = result
        return result

    # DNS failure — definitive even from Stage 1 alone (DNS won't change between attempts)
    if s1["raw"] == "dns_fail" or any(r["raw"] == "dns_fail" for r in s2_results):
        result = ("Domain Not Found",
                  "The domain does not exist (DNS resolution failed).", 100)
        _log_debug(domain, all_results, "Domain Not Found")
        domain_cache[domain] = result
        return result

    # Connection refused — both stages must confirm
    s2_conn = any(r["raw"] == "conn_refused" for r in s2_results)
    if s1["raw"] == "conn_refused" and s2_conn:
        result = ("Server Unreachable",
                  "The server refused all connection attempts.", 95)
        _log_debug(domain, all_results, "Server Unreachable")
        domain_cache[domain] = result
        return result

    # Hard server error (non-503) — both stages must confirm
    s1_hard_err = s1["raw"] == "s1_server_error"
    s2_hard_err = any(r["raw"] == "p2_server_error" for r in s2_results)
    if s1_hard_err and s2_hard_err:
        codes  = [r["code"] for r in all_results if r.get("code")]
        code_s = str(codes[0]) if codes else "unknown"
        result = ("Server Error",
                  f"The server returned errors on all checks (HTTP {code_s}).", 90)
        _log_debug(domain, all_results, "Server Error")
        domain_cache[domain] = result
        return result

    # 503 path — only broken if BOTH stages return server-level failures
    # (503 + hard server error from Playwright counts; 503 + timeout does NOT)
    s1_503 = s1["raw"] == "s1_503"
    s2_503_hard = any(r["raw"] in ("p2_server_error", "p2_503") for r in s2_results)
    # Require BOTH Playwright attempts to agree on a server-level failure
    s2_both_503_hard = all(r["raw"] in ("p2_server_error", "p2_503", "conn_refused") for r in s2_results)
    if s1_503 and s2_both_503_hard and s2_503_hard:
        result = ("Server Error",
                  "The server is unavailable (HTTP 503 confirmed by both HTTP and browser checks).", 90)
        _log_debug(domain, all_results, "Server Error")
        domain_cache[domain] = result
        return result

    # Consistent timeout across both stages → Server Unreachable
    s1_timeout = s1["raw"] == "timeout"
    s2_all_timeout = all(r["raw"] in ("p2_timeout", "error") for r in s2_results)
    if s1_timeout and s2_all_timeout:
        result = ("Server Unreachable",
                  "The site did not respond on any attempt (consistent timeout on HTTP and browser checks).", 95)
        _log_debug(domain, all_results, "Server Unreachable")
        domain_cache[domain] = result
        return result

    # Mixed hard failures across both stages → Server Unreachable
    s1_failed = s1["raw"] in ("timeout", "conn_refused", "s1_server_error", "dns_fail")
    s2_all_failed = all(r["raw"] in ("p2_timeout", "p2_server_error", "dns_fail", "conn_refused", "error") for r in s2_results)
    s2_has_hard = any(r["raw"] in ("p2_server_error", "dns_fail", "conn_refused") for r in s2_results)
    if s1_failed and s2_all_failed and s2_has_hard:
        result = ("Server Unreachable",
                  f"The site failed all checks (HTTP: {s1['raw']}, browser: {s2_results[0]['raw']}).", 92)
        _log_debug(domain, all_results, "Server Unreachable")
        domain_cache[domain] = result
        return result

    # ── Conservative fallback — insufficient evidence → Working ───────────────
    reason = (
        f"Insufficient evidence of a broken site "
        f"(HTTP check: {s1['raw']}, "
        f"browser: {' / '.join(r['raw'] for r in s2_results)}). "
        "Classified as working to avoid false positives."
    )
    result = ("Working", reason, 0)
    _log_debug(domain, all_results, "Working (conservative fallback)")
    domain_cache[domain] = result
    return result


def _log_debug(domain: str, attempts: list, final: str) -> None:
    """Write a structured debug log line for every website check."""
    parts = [f"WS-RESULT domain={domain} final={final!r}"]
    for i, a in enumerate(attempts, start=1):
        parts.append(f"attempt_{i}=(raw={a['raw']} code={a['code']})")
    logging.info(" | ".join(parts))


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
                            _broken = {"Domain Not Found", "Server Unreachable", "Server Error", "Parked Domain"}
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
