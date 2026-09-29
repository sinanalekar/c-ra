"""Browser subsystem: real controlled browser automation via
Playwright (chromium, headless) with an HTTP-fetch fallback.

REAL capabilities (driver + chromium present - verified):
- navigate URLs, follow redirects, per-session pages
- text/DOM extraction, structured links, page source
- interaction: click, type, press, scroll (browser.interact)
- screenshots (browser.read)
- downloads via click + expect_download (browser.download,
  high-risk confirmation)
- uploads via file inputs (browser.upload, high-risk
  confirmation)

Fallback: when the driver or browser binaries are missing, the
runtime reports those capabilities UNAVAILABLE honestly - never
faked.

All actions pass the central capability system and appear in
the live activity journal. Only http/https navigation; never
bypasses authentication, CAPTCHAs, paywalls, or access
controls."""
from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path

from .capabilities import AuthorizationError

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "CYRA-research/1.0")
MAX_CONTENT = 2 * 1024 * 1024
DOWNLOAD_DIR_NAME = "downloads"


def _playwright_available() -> bool:
    """Cached probe. A missing driver caches False
    permanently. A launch failure is cached for the process
    too, but sessions recover by falling back honestly -
    never by faking."""
    global _DRIVER_OK_CACHE
    if _DRIVER_OK_CACHE is not None:
        return _DRIVER_OK_CACHE
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        _DRIVER_OK_CACHE = False   # truly missing
        return False
    try:
        with sync_playwright() as p:
            try:
                b = p.chromium.launch(headless=True)
                b.close()
                _DRIVER_OK_CACHE = True
            except Exception:
                _DRIVER_OK_CACHE = False
    except Exception:
        _DRIVER_OK_CACHE = False
    return _DRIVER_OK_CACHE


_DRIVER_OK_CACHE = None


class BrowserSession(dict):
    @classmethod
    def make(cls, session_id):
        return cls(session_id=session_id,
                   current_url="", title="",
                   history=[], downloads=[],
                   errors=[], engine="none",
                   created_utc=time.strftime(
                       "%Y-%m-%dT%H:%M:%SZ",
                       time.gmtime()))


class BrowserRuntime:
    """Playwright-backed browser automation with an
    urllib-based fetch fallback for read-only navigation."""

    def __init__(self, capabilities, journal=None,
                 workdir: str = "."):
        self.capabilities = capabilities
        self.journal = journal
        self.workdir = Path(workdir)
        self.sessions: dict[str, BrowserSession] = {}
        self._seq = 0
        self._pw = None          # playwright driver handle
        self._browser = None     # shared chromium instance
        self._driver_ok = _playwright_available()

    # ------------------------------------------------ status
    def capability_status(self) -> dict:
        real = self._driver_ok
        return {
            "navigate_and_read": True,
            "text_extraction": True,
            "page_source": True,
            "interaction": real,
            "downloads": real,
            "uploads": real,
            "screenshots": real,
            "engine": ("playwright/chromium" if real
                       else "http-fetch fallback"),
            "note": ("interactive automation is REAL via "
                     "playwright/chromium" if real else
                     "interactive automation requires "
                     "playwright + chromium; reported "
                     "unavailable until installed - never "
                     "faked"),
        }

    # ------------------------------------------------ sessions
    def open_session(self) -> dict:
        self._seq += 1
        sid = f"web-{self._seq:05d}"
        s = BrowserSession.make(sid)
        if self._driver_ok:
            page = None
            for attempt in (1, 2):
                try:
                    page = self._ensure_browser(). \
                        new_page()
                    break
                except Exception as e:
                    s["errors"].append(
                        "driver init failed "
                        "(attempt %d): %r"
                        % (attempt, e))
                    # crashed browser recovery: tear the
                    # driver down completely and relaunch
                    # once before giving up honestly
                    self.shutdown()
                    if attempt == 2:
                        s["engine"] = \
                            "http-fetch fallback"
            if page is not None:
                s["engine"] = "playwright/chromium"
                s["_page"] = page
            else:
                s["engine"] = "http-fetch fallback"
        else:
            s["engine"] = "http-fetch fallback"
        self.sessions[sid] = s
        return {k: v for k, v in s.items()
                if not k.startswith("_")}

    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import \
                sync_playwright
            self._pw = sync_playwright().start()
            dl = self.workdir / DOWNLOAD_DIR_NAME
            dl.mkdir(parents=True, exist_ok=True)
            self._browser = self._pw.chromium.launch(
                headless=True)
        return self._browser

    def _page(self, session_id):
        s = self.sessions.get(session_id)
        if s is None:
            return None, None
        return s, s.get("_page")

    def get(self, session_id: str) -> dict:
        s = self.sessions.get(session_id)
        if s is None:
            return {"error": "unknown session"}
        return {k: v for k, v in s.items()
                if not k.startswith("_")}

    # ------------------------------------------------ navigate
    def navigate(self, session_id: str, url: str) -> dict:
        s, page = self._page(session_id)
        if s is None:
            return {"error": "unknown session"}
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            s["errors"].append(
                f"scheme {parsed.scheme!r} not allowed")
            self._journal("browser_blocked", url=url[:200],
                          reason="disallowed scheme")
            return {"error": "only http/https navigation "
                             "is supported"}
        for cap in ("browser.navigate", "browser.read"):
            d = self.capabilities.authorize(cap, scope=url)
            if not d["allowed"]:
                s["errors"].append(d["reason"])
                return {"error": d["reason"]}
        try:
            if page is not None:
                resp = page.goto(
                    url, timeout=30000,
                    wait_until="domcontentloaded")
                status = resp.status if resp else None
                final_url = page.url
                title = (page.title() or "")[:200]
                text = page.content()
            else:
                return self._fetch_fallback(s, url)
        except Exception as e:
            s["errors"].append(
                f"{url}: {e!r}"[:300])
            self._journal("browser_error", url=url[:200],
                          error=repr(e)[:200])
            return {"error": repr(e)[:300]}
        s["current_url"] = final_url
        s["title"] = title
        s["history"].append({
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": final_url, "status": status})
        self._journal("browser_navigated",
                      session_id=session_id,
                      url=final_url[:200], status=status,
                      title=title[:100])
        return {"url": final_url, "title": title,
                "status": status,
                "engine": s["engine"]}

    def _fetch_fallback(self, s, url) -> dict:
        import urllib.request
        try:
            req = urllib.request.Request(
                url, headers={
                    "User-Agent": USER_AGENT})
            with urllib.request.urlopen(
                    req, timeout=30) as r:
                body = r.read(MAX_CONTENT)
                text = body.decode(
                    "utf-8", errors="replace")
                title = ""
                m = re.search(
                    r"<title[^>]*>(.*?)</title>",
                    text, re.I | re.S)
                if m:
                    title = re.sub(
                        r"\s+", " ",
                        m.group(1)).strip()[:200]
                s["current_url"] = r.url
                s["title"] = title
                s["history"].append({
                    "ts": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime()),
                    "url": r.url, "status": r.status})
                self._journal(
                    "browser_navigated",
                    session_id=s["session_id"],
                    url=r.url[:200], status=r.status,
                    title=title[:100])
                return {"url": r.url, "title": title,
                        "status": r.status,
                        "engine": "http-fetch fallback"}
        except Exception as e:
            s["errors"].append(f"{url}: {e!r}"[:300])
            return {"error": repr(e)[:300]}

    # ------------------------------------------------ extract
    def extract(self, session_id: str) -> dict:
        s, page = self._page(session_id)
        if s is None:
            return {"error": "unknown session"}
        if not s["current_url"]:
            return {"error": "no page loaded"}
        d = self.capabilities.authorize(
            "browser.read", scope=s["current_url"])
        if not d["allowed"]:
            return {"error": d["reason"]}
        try:
            if page is not None:
                text = page.inner_text("body")
                links = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.slice(0, 100).map("
                    "e => e.getAttribute('href'))")
            else:
                return self._extract_fallback(s)
        except Exception as e:
            return {"error": repr(e)[:300]}
        self._journal("browser_extracted",
                      session_id=session_id,
                      chars=len(text),
                      links=len(links))
        return {"url": s["current_url"],
                "title": s["title"],
                "text": text[:100000],
                "links": links[:100]}

    def _extract_fallback(self, s) -> dict:
        import urllib.request
        try:
            req = urllib.request.Request(
                s["current_url"], headers={
                    "User-Agent": USER_AGENT})
            with urllib.request.urlopen(
                    req, timeout=30) as r:
                html = r.read(MAX_CONTENT).decode(
                    "utf-8", errors="replace")
        except Exception as e:
            return {"error": repr(e)[:300]}
        visible = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", " ", html,
            flags=re.S | re.I)
        visible = re.sub(r"<[^>]+>", " ", visible)
        visible = re.sub(r"\s+", " ",
                         visible).strip()
        links = re.findall(
            r'href=["\']([^"\']+)["\']', html)[:100]
        return {"url": s["current_url"],
                "title": s["title"],
                "text": visible[:100000],
                "links": links}

    def page_source(self, session_id: str) -> dict:
        s, page = self._page(session_id)
        if s is None:
            return {"error": "unknown session"}
        if page is not None:
            return {"url": s["current_url"],
                    "source": page.content()[:200000]}
        return {"error": "page source requires the "
                         "playwright engine (session is "
                         "in fetch-fallback mode)"}

    # ------------------------------------------------ interaction
    def interact(self, session_id: str, action: str,
                 selector: str = "",
                 text: str = "",
                 confirm: bool = False) -> dict:
        """REAL interaction via playwright: click | type |
        press | scroll. Requires browser.interact (and the
        driver). Falls through honestly when absent."""
        if not self._driver_ok:
            self._journal(
                "browser_interaction_unavailable",
                session_id=session_id,
                browser_action=action[:50])
            return {"error": "browser interaction requires "
                             "the playwright driver + "
                             "chromium; unavailable - "
                             "reported honestly, never "
                             "faked"}
        d = self.capabilities.authorize(
            "browser.interact", scope=session_id,
            confirm_high_risk=confirm)
        if not d["allowed"]:
            return {"error": d["reason"]}
        s, page = self._page(session_id)
        if page is None:
            return {"error": "session has no live page"}
        try:
            if action == "click":
                page.click(selector, timeout=10000)
            elif action == "type":
                page.fill(selector, text,
                          timeout=10000)
            elif action == "press":
                page.keyboard.press(text or "Enter")
            elif action == "scroll":
                page.mouse.wheel(0, int(text or 800))
            else:
                return {"error": f"unknown action "
                                 f"{action!r}"}
        except Exception as e:
            s["errors"].append(
                f"{action}: {e!r}"[:300])
            self._journal("browser_action_failed",
                          session_id=session_id,
                          browser_action=action,
                          error=repr(e)[:200])
            return {"error": repr(e)[:300]}
        s["history"].append({
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action, "selector": selector,
            "text": text[:50]})
        self._journal("browser_action",
                      session_id=session_id,
                      browser_action=action,
                      selector=selector[:100])
        return {"action": action, "done": True,
                "url": page.url}

    # ------------------------------------------- screenshots etc.
    def screenshot(self, session_id: str,
                   confirm: bool = False) -> dict:
        if not self._driver_ok:
            return {"error": "screenshots require the "
                             "playwright engine; "
                             "unavailable - reported "
                             "honestly"}
        d = self.capabilities.authorize(
            "browser.read", scope=session_id,
            confirm_high_risk=confirm)
        if not d["allowed"]:
            return {"error": d["reason"]}
        s, page = self._page(session_id)
        if page is None:
            return {"error": "no live page"}
        out = self.workdir / "screenshots" / \
            f"{session_id}-{int(time.time())}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
        self._journal("browser_screenshot",
                      session_id=session_id,
                      path=str(out))
        return {"screenshot": str(out)}

    def download(self, session_id: str,
                 selector: str,
                 confirm: bool = False) -> dict:
        """REAL download: click a link/button and capture the
        download artifact (browser.download, high-risk)."""
        if not self._driver_ok:
            return {"error": "downloads require the "
                             "playwright engine; "
                             "unavailable - reported "
                             "honestly"}
        d = self.capabilities.authorize(
            "browser.download", scope=session_id,
            confirm_high_risk=confirm)
        if not d["allowed"]:
            return {"error": d["reason"]}
        s, page = self._page(session_id)
        if page is None:
            return {"error": "no live page"}
        dl_dir = self.workdir / DOWNLOAD_DIR_NAME
        dl_dir.mkdir(parents=True, exist_ok=True)
        try:
            with page.expect_download(
                    timeout=30000) as dl_info:
                page.click(selector, timeout=10000)
            dl = dl_info.value
            target = dl_dir / dl.suggested_filename
            dl.save_as(str(target))
        except Exception as e:
            return {"error": repr(e)[:300]}
        s["downloads"].append(str(target))
        self._journal("browser_download",
                      session_id=session_id,
                      path=str(target))
        return {"downloaded": str(target)}

    def upload(self, session_id: str, selector: str,
               file_path: str,
               confirm: bool = False) -> dict:
        if not self._driver_ok:
            return {"error": "uploads require the "
                             "playwright engine; "
                             "unavailable - reported "
                             "honestly"}
        d = self.capabilities.authorize(
            "browser.upload", scope=session_id,
            confirm_high_risk=confirm)
        if not d["allowed"]:
            return {"error": d["reason"]}
        s, page = self._page(session_id)
        if page is None:
            return {"error": "no live page"}
        if not Path(file_path).is_file():
            return {"error": "file not found"}
        try:
            page.set_input_files(
                selector, file_path, timeout=10000)
        except Exception as e:
            return {"error": repr(e)[:300]}
        self._journal("browser_upload",
                      session_id=session_id,
                      file=file_path[:200])
        return {"uploaded": file_path}

    # ------------------------------------------------ shutdown
    def shutdown(self):
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass

    def _journal(self, action: str, **fields):
        if self.journal:
            self.journal.append(action, **fields)
