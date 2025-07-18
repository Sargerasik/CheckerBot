import logging
import asyncio
import aiohttp
from langdetect import detect_langs
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from urllib.parse import urlparse
import re
from typing import List, Tuple

logger = logging.getLogger("checker")
logger.setLevel(logging.INFO)


class WebsiteChecker:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc.replace("www.", "")
        self.driver = self._get_driver()
        logger.info(f"Создан WebsiteChecker для URL: {self.base_url}")

    def _get_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")
        driver = webdriver.Chrome(service=Service(), options=options)
        driver.implicitly_wait(10)
        logger.debug("Chrome-драйвер запущен (headless)")
        return driver

    def check_language_consistency(self) -> dict:
        logger.info("Проверка: Language Consistency")

        driver = self._get_driver()
        driver.get(self.base_url)
        try:
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")

            texts = [t.strip() for t in soup.stripped_strings]
            visible_text = " ".join(texts[:1000])  # Ограничим объём

            if not visible_text:
                logger.warning("Нет текста для анализа")
                return {"language": "unknown", "consistent": False}

            langs = detect_langs(visible_text)
            logger.info(f"Detected langs: {langs}")

            primary = langs[0]
            is_consistent = all(abs(primary.prob - l.prob) < 0.3 for l in langs)

            return {
                "language": primary.lang,
                "probability": round(primary.prob, 2),
                "consistent": is_consistent
            }
        except Exception as e:
            logger.error(f"Ошибка определения языка: {e}")
            return {"language": "error", "consistent": False}
        finally:
            driver.quit()

    def check_cookie_consent(self) -> bool:
        logger.info("Проверка: Cookie Consent Banner")
        self.driver.get(self.base_url)

        # Пробуем найти кнопки или блоки, похожие на баннер
        keywords = ["cookie", "consent", "accept", "agree", "preferences"]

        found = False
        try:
            # Ищем кнопки и ссылки
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            links = self.driver.find_elements(By.TAG_NAME, "a")
            divs = self.driver.find_elements(By.TAG_NAME, "div")

            all_elements = buttons + links + divs

            for elem in all_elements:
                text = elem.text.strip().lower()
                if any(k in text for k in keywords):
                    found = True
                    logger.info(f"Найден элемент: '{text}'")
                    break

        except Exception as e:
            logger.warning(f"Ошибка при поиске cookie consent: {e}")

        logger.info(f"Результат Cookie Consent: {found}")
        return found

    def check_terms_and_policies(self) -> dict:
        logger.info("Проверка: Terms, Privacy Policy")
        self.driver.get(self.base_url)
        expected = {"terms": False, "privacy policy": False}
        elements = self.driver.find_elements(By.TAG_NAME, "a") + self.driver.find_elements(By.TAG_NAME, "button")

        for elem in elements:
            text = elem.text.strip().lower()
            if not text:
                continue
            if "terms" in text:
                expected["terms"] = True
            if "privacy policy" in text:
                expected["privacy policy"] = True

        logger.info(f"Результат Terms & Policies: {expected}")
        return expected

    def check_contact_email(self) -> dict:
        logger.info("Проверка: Contact Email (включая Privacy Policy)")
        driver = self._get_driver()
        driver.get(self.base_url)
        logger.debug(f"Открыт сайт: {self.base_url}")

        try:
            # --- 1. Ищем email на главной странице ---
            page_source = driver.page_source
            email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
            found_main = re.findall(email_pattern, page_source)
            found_main = list(set(found_main))  # уникальные

            if found_main:
                logger.info(f"Email найден на главной: {found_main}")
                return {
                    "found": True,
                    "emails": found_main,
                    "source": "main"
                }

            # --- 2. Ищем ссылку на Privacy Policy ---
            logger.info("Email не найден на главной. Пытаемся перейти в Privacy Policy...")
            elements = driver.find_elements(By.TAG_NAME, "a")
            privacy_url = None
            for a in elements:
                text = a.text.strip().lower()
                href = a.get_attribute("href")
                if href and "privacy" in text and "policy" in text:
                    privacy_url = href
                    break

            if not privacy_url:
                logger.warning("Ссылка на Privacy Policy не найдена.")
                return {
                    "found": False,
                    "emails": [],
                    "source": "none"
                }

            # --- 3. Переход в Privacy Policy ---
            logger.info(f"Переход по ссылке: {privacy_url}")
            driver.get(privacy_url)
            page_source = driver.page_source
            found_privacy = re.findall(email_pattern, page_source)
            found_privacy = list(set(found_privacy))

            if found_privacy:
                logger.info(f"Email найден в Privacy Policy: {found_privacy}")
                return {
                    "found": True,
                    "emails": found_privacy,
                    "source": "privacy_policy"
                }

            logger.info("Email не найден ни на главной, ни в Privacy Policy.")
            return {
                "found": False,
                "emails": [],
                "source": "none"
            }

        finally:
            driver.quit()
            logger.debug("Драйвер закрыт после проверки Email")

    def check_currency(self) -> bool:
        logger.info("Проверка: Валюта")
        self.driver.get(self.base_url)
        page_source = self.driver.page_source
        result = "€" in page_source or "£" in page_source
        logger.info(f"Валюта найдена: {result}")
        return result

    async def check_404_errors(self) -> List[Tuple[str, int]]:
        logger.info("Проверка: 404 и 500 Errors (async)")
        visited = set()
        broken = []
        queue = [self.base_url]

        async with aiohttp.ClientSession() as session:
            while queue:
                current_url = queue.pop(0)
                if current_url in visited:
                    continue

                visited.add(current_url)
                logger.info(f"HEAD+GET для: {current_url}")

                try:
                    async with session.head(current_url, timeout=5, allow_redirects=True) as resp:
                        if resp.status in (404, 500):
                            broken.append((current_url, resp.status))
                            continue
                        if resp.status == 200:
                            async with session.get(current_url, timeout=5) as resp2:
                                if resp2.status in (404, 500):
                                    broken.append((current_url, resp2.status))
                                    continue
                except Exception as e:
                    logger.warning(f"RequestException: {e}")
                    broken.append((current_url, 0))
                    continue

                try:
                    self.driver.get(current_url)
                    anchors = self.driver.find_elements(By.TAG_NAME, "a")
                    logger.debug(f"Найдено ссылок: {len(anchors)} на {current_url}")

                    for a in anchors:
                        href = a.get_attribute("href")
                        if not href:
                            continue
                        parsed = urlparse(href)
                        netloc = parsed.netloc.replace("www.", "")
                        if netloc == self.base_domain and href not in visited and href not in queue:
                            queue.append(href)
                            logger.info(f"Добавлена в очередь внутренняя ссылка: {href}")
                except Exception as e:
                    logger.warning(f"Selenium ошибка: {e}")

        logger.info(f"Обнаружены битые ссылки: {broken}")
        return broken

    def close(self):
        self.driver.quit()
        logger.debug("Драйвер закрыт")
