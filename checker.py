# checker.py
import logging
import tempfile
import shutil
import re
import requests
from bs4 import BeautifulSoup
from langdetect import detect_langs
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from urllib.parse import urlparse, urljoin
from collections import Counter
from typing import List, Tuple, Dict

logger = logging.getLogger("checker")
logger.setLevel(logging.INFO)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36"
}

class WebsiteChecker:
    def __init__(self, base_url: str, max_pages: int = 50):
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc.replace("www.", "").lower()
        self._profile_dir = tempfile.mkdtemp(prefix="chrome-profile-")
        self.max_pages = max_pages
        logger.info(f"Создан WebsiteChecker для URL: {self.base_url}")

    # --- Chrome driver ---
    def _get_driver(self):
        options = Options()
        # Надёжный headless
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--disable-default-apps")
        options.add_argument("--mute-audio")
        options.add_argument("--hide-scrollbars")
        options.add_argument(f"--user-data-dir={self._profile_dir}")
        options.add_argument("--window-size=1280,1024")
        options.add_argument("--lang=en-US")

        try:
            driver = webdriver.Chrome(service=Service(), options=options)
            driver.implicitly_wait(10)
            return driver
        except Exception as e:
            logger.error(f"Не удалось запустить Chrome: {e}")
            raise

    def close(self):
        try:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Ошибка при удалении временной директории: {e}")

    # --- Helpers ---
    def _same_site(self, href: str) -> bool:
        """Проверка, что ссылка принадлежит тому же сайту (вкл. поддомены)."""
        parsed = urlparse(href)
        netloc = parsed.netloc.replace("www.", "").lower()
        return netloc.endswith(self.base_domain)

    def _extract_internal_links(self, base: str, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"])
            if href.startswith("mailto:") or href.startswith("tel:"):
                continue
            if self._same_site(href):
                links.append(href)
        return list(dict.fromkeys(links))  # уникальность, сохранение порядка

    # --- Checks (sync) ---
    def check_language_consistency(self) -> Dict[str, object]:
        logger.info("Проверка: Language Consistency")
        driver = self._get_driver()
        try:
            driver.get(self.base_url)
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            texts = [t.strip() for t in soup.stripped_strings]
            visible_text = " ".join(texts[:2000])

            if len(visible_text) < 50:
                return {"language": "unknown", "probability": 0.0, "consistent": False}

            langs = detect_langs(visible_text)
            primary = langs[0]
            is_consistent = all(abs(primary.prob - l.prob) < 0.3 for l in langs)
            return {"language": primary.lang, "probability": round(primary.prob, 2), "consistent": is_consistent}
        except Exception as e:
            logger.error(f"Ошибка определения языка: {e}")
            return {"language": "error", "probability": 0.0, "consistent": False}
        finally:
            driver.quit()

    def check_cookie_consent(self) -> bool:
        logger.info("Проверка: Cookie Consent Banner")
        keywords = [
            "cookie", "cookies", "consent", "accept", "agree", "preferences",
            "куки", "cookie-файлы", "согласие", "принять", "настройки"
        ]
        driver = self._get_driver()
        try:
            driver.get(self.base_url)
            elements = driver.find_elements(By.CSS_SELECTOR, "button, a, div")
            for elem in elements:
                text = (elem.text or "").strip().lower()
                if not text:
                    continue
                if any(k in text for k in keywords):
                    logger.info(f"Найден элемент баннера: '{text}'")
                    return True
            return False
        except Exception as e:
            logger.warning(f"Ошибка при поиске cookie consent: {e}")
            return False
        finally:
            driver.quit()

    def check_terms_and_policies(self) -> Dict[str, bool]:
        logger.info("Проверка: Terms, Privacy Policy")
        driver = self._get_driver()
        try:
            driver.get(self.base_url)
            elements = driver.find_elements(By.CSS_SELECTOR, "a, button")
            textset = set((e.text or "").strip().lower() for e in elements if (e.text or "").strip())

            terms_keys = {"terms", "terms of service", "terms & conditions", "условия", "пользовательское соглашение"}
            policy_keys = {"privacy policy", "privacy", "политика конфиденциальности", "конфиденциальность"}

            found_terms = any(any(k in t for k in terms_keys) for t in textset)
            found_policy = any(any(k in t for k in policy_keys) for t in textset)

            return {"terms": found_terms, "privacy policy": found_policy}
        except Exception as e:
            logger.warning(f"Ошибка при поиске terms and policies: {e}")
            return {"terms": False, "privacy policy": False}
        finally:
            driver.quit()

    def check_contact_email(self) -> Dict[str, object]:
        logger.info("Проверка: Contact Email")
        email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        driver = self._get_driver()
        try:
            # 1) главная
            driver.get(self.base_url)
            page_source = driver.page_source
            found_main = sorted(set(re.findall(email_pattern, page_source)))
            if found_main:
                return {"found": True, "emails": found_main, "source": "main"}

            # 2) privacy policy
            links = driver.find_elements(By.TAG_NAME, "a")
            privacy_url = None
            for a in links:
                text = (a.text or "").strip().lower()
                href = a.get_attribute("href")
                if href and ("privacy" in text and "policy" in text):
                    privacy_url = href
                    break
            if not privacy_url:
                return {"found": False, "emails": [], "source": "none"}

            driver.get(privacy_url)
            found_privacy = sorted(set(re.findall(email_pattern, driver.page_source)))
            if found_privacy:
                return {"found": True, "emails": found_privacy, "source": "privacy_policy"}
            return {"found": False, "emails": [], "source": "none"}
        finally:
            driver.quit()

    @staticmethod
    def extract_phones_from_html(html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return WebsiteChecker.extract_phones_from_text(text)

    @staticmethod
    def extract_phones_from_text(text: str) -> List[str]:
        phone_pattern = r"""
            (?<!\d)
            (?:(?:\+|00)?\d{1,3}[\s\-\.]?)?
            (?:\(?\d{2,4}\)?[\s\-\.]?)?
            \d{2,4}[\s\-\.]?\d{2,4}(?:[\s\-\.]?\d{2,4})?
            (?!\d)
        """
        matches = re.findall(phone_pattern, text, flags=re.VERBOSE)
        results = []
        for m in matches:
            digits = re.sub(r"\D", "", m)
            if 7 <= len(digits) <= 15:
                results.append(m.strip())
        return list(sorted(set(results)))

    def check_contact_phone(self) -> Dict[str, object]:
        logger.info("Проверка: Contact Phone")
        driver = self._get_driver()
        try:
            driver.get(self.base_url)
            found_main = self.extract_phones_from_html(driver.page_source)
            if found_main:
                return {"found": True, "phones": found_main, "source": "main"}

            links = driver.find_elements(By.TAG_NAME, "a")
            privacy_url = None
            for a in links:
                text = (a.text or "").strip().lower()
                href = a.get_attribute("href")
                if href and ("privacy" in text and "policy" in text):
                    privacy_url = href
                    break
            if not privacy_url:
                return {"found": False, "phones": [], "source": "none"}

            driver.get(privacy_url)
            found_privacy = self.extract_phones_from_html(driver.page_source)
            if found_privacy:
                return {"found": True, "phones": found_privacy, "source": "privacy_policy"}
            return {"found": False, "phones": [], "source": "none"}
        finally:
            driver.quit()

    def check_currency(self) -> Dict[str, object]:
        logger.info("Проверка: Валюта на страницах")
        visited, queue = set(), [self.base_url]
        symbol_pattern = re.compile(r"[€$£¥₽₹₩₪₫฿₴₦]")
        code_pattern = re.compile(r"\b(?:USD|EUR|RUB|GBP|JPY|CNY|INR|KRW|ILS|VND|THB|UAH|NGN)\b", re.IGNORECASE)

        symbols, codes = [], []

        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        pages = 0
        while queue and pages < self.max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)
            pages += 1

            try:
                resp = session.get(current_url, timeout=10)
                html = resp.text
            except Exception as e:
                logger.warning(f"Ошибка загрузки {current_url}: {e}")
                continue

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ")

            symbols.extend(symbol_pattern.findall(text))
            codes.extend(c.upper() for c in code_pattern.findall(text))

            # новые ссылки
            for href in self._extract_internal_links(current_url, html):
                if href not in visited and href not in queue:
                    queue.append(href)

        symbols_counter = Counter(symbols)
        codes_counter = Counter(codes)
        most_common_symbol = symbols_counter.most_common(1)[0][0] if symbols_counter else None
        return {
            "found": bool(symbols_counter or codes_counter),
            "symbols": dict(symbols_counter),
            "codes": dict(codes_counter),
            "most_common_symbol": most_common_symbol
        }

    def check_404_errors(self) -> List[Tuple[str, int]]:
        logger.info("Проверка: 4xx/5xx ошибок")
        visited, queue = set(), [self.base_url]
        broken: List[Tuple[str, int]] = []

        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        pages = 0
        while queue and pages < self.max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)
            pages += 1

            status = None
            try:
                r = session.head(current_url, timeout=5, allow_redirects=True)
                status = r.status_code
                # некоторые сайты не любят HEAD
                if status in (405, 403) or status is None:
                    r = session.get(current_url, timeout=8, allow_redirects=True)
                    status = r.status_code
            except Exception as e:
                logger.warning(f"Request error {current_url}: {e}")
                broken.append((current_url, 0))
                # не расширяем ссылки если страница недоступна
                continue

            if status >= 400:
                broken.append((current_url, status))
                continue

            # собрать внутренние ссылки, если страница ок
            try:
                r = session.get(current_url, timeout=8, allow_redirects=True)
                html = r.text
                for href in self._extract_internal_links(current_url, html):
                    if href not in visited and href not in queue:
                        queue.append(href)
            except Exception as e:
                logger.warning(f"Ошибка парсинга ссылок на {current_url}: {e}")

        return broken
