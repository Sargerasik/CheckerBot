import logging
import asyncio
import aiohttp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

import re
from typing import List, Tuple

logger = logging.getLogger("checker")
logger.setLevel(logging.INFO)


class WebsiteChecker:
    def __init__(self, base_url: str):
        self.base_url = base_url
        logger.info(f"Создан WebsiteChecker для URL: {self.base_url}")
        self.driver = self._get_driver()

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

    def check_terms_and_policies(self) -> dict:
        logger.info("Проверка: Terms, Privacy Policy, Cookie")
        self.driver.get(self.base_url)
        expected = {"terms": False, "privacy policy": False, "cookie": False}
        elements = self.driver.find_elements(By.TAG_NAME, "a") + self.driver.find_elements(By.TAG_NAME, "button")

        for elem in elements:
            text = elem.text.strip().lower()
            if not text:
                continue
            if "terms" in text:
                expected["terms"] = True
            if "privacy policy" in text:
                expected["privacy policy"] = True
            if "cookie" in text:
                expected["cookie"] = True

        logger.info(f"Результат Terms & Policies: {expected}")
        return expected

    def check_contact_email(self) -> dict:
        logger.info("Проверка: Contact Email")
        self.driver.get(self.base_url)
        page_source = self.driver.page_source
        email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        found = re.findall(email_pattern, page_source)
        unique_emails = list(set(found))
        logger.info(f"Найдено Email: {unique_emails}")
        return {"found": bool(unique_emails), "emails": unique_emails}

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
                        if href and self.base_url in href and href not in visited and href not in queue:
                            queue.append(href)
                except Exception as e:
                    logger.warning(f"Selenium ошибка: {e}")

        logger.info(f"Обнаружены битые ссылки: {broken}")
        return broken

    def close(self):
        self.driver.quit()
        logger.debug("Драйвер закрыт")
