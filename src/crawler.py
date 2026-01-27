"""
Web crawler for the Macedonian Parliament website.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import requests
from bs4 import BeautifulSoup

from .config import BotConfig
from .utils import get_logger, parse_pdf_link_text, generate_fallback_filename

logger = get_logger()


class SobranieCrawler:
    """
    Crawls the Macedonian Parliament website using Selenium.

    Features:
    - Accepts both "Завршена" and "Затворена" statuses
    - Collects ALL stenograph documents from a session (1-to-many)
    - Properly handles PDF files disguised as DOC files
    """

    def __init__(self, config: Optional[BotConfig] = None):
        """
        Initialize the crawler.

        Args:
            config: Bot configuration (uses default if not provided)
        """
        self.config = config or BotConfig()

        # Chrome Options
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--ignore-certificate-errors")
        self.chrome_options.add_argument("--disable-web-security")
        self.chrome_options.add_argument("--allow-running-insecure-content")
        self.chrome_options.add_argument(f"user-agent={self.config.USER_AGENT}")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option("useAutomationExtension", False)

        # Session for direct downloads
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.config.USER_AGENT})

    def _create_driver(self) -> webdriver.Chrome:
        """Create a new Chrome WebDriver instance."""
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=self.chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver

    def _handle_cookie_consent(self, driver: webdriver.Chrome) -> bool:
        """Attempt to dismiss any cookie/GDPR consent banners."""
        cookie_selectors = [
            "button.btn-accept",
            "button.accept-cookies",
            ".cookie-consent button.btn-primary",
            ".modal-footer button.btn-primary",
            "//button[contains(text(), 'Прифати')]",
            "//button[contains(text(), 'Accept')]",
            "//button[contains(text(), 'OK')]",
            ".modal .close",
            "[data-dismiss='modal']",
        ]

        for selector in cookie_selectors:
            try:
                by = By.XPATH if selector.startswith("//") else By.CSS_SELECTOR
                button = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((by, selector))
                )
                try:
                    button.click()
                    logger.debug(f"✓ Clicked cookie consent: {selector}")
                    time.sleep(1)
                    return True
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", button)
                    time.sleep(1)
                    return True
            except (TimeoutException, NoSuchElementException):
                continue
            except Exception:
                continue

        # Try to remove modals via JavaScript
        try:
            driver.execute_script("""
                document.querySelectorAll('.modal, .cookie-consent, .gdpr-modal').forEach(el => el.remove());
                document.querySelectorAll('.modal-backdrop, .overlay').forEach(el => el.remove());
                document.body.style.overflow = 'auto';
                document.body.classList.remove('modal-open');
            """)
        except Exception:
            pass
        return False

    def _wait_for_angular(self, driver: webdriver.Chrome, timeout: int = 15) -> bool:
        """Wait for AngularJS to finish loading."""
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("""
                    if (typeof angular === 'undefined') return false;
                    try {
                        var injector = angular.element(document.body).injector();
                        if (!injector) return false;
                        var $http = injector.get('$http');
                        return $http.pendingRequests.length === 0;
                    } catch(e) { return true; }
                """)
            )
            logger.debug("✓ Angular is ready")
            return True
        except TimeoutException:
            logger.debug("Angular wait timed out, continuing...")
            return False
        except Exception as e:
            logger.debug(f"Angular wait error: {e}")
            return False

    def _scroll_page(self, driver: webdriver.Chrome) -> None:
        """Scroll the page to trigger lazy loading."""
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
        except Exception:
            pass

    def _extract_sitting_id(self, details_url: str) -> Optional[str]:
        """Extract sittingId from URL."""
        try:
            parsed = urlparse(details_url)
            params = parse_qs(parsed.query)
            return params.get("sittingId", [None])[0]
        except:
            return None

    def _is_valid_status(self, status: str) -> bool:
        """Check if status indicates a finished/closed session."""
        if not status:
            return False
        status_lower = status.lower().strip()
        return "завршена" in status_lower or "затворена" in status_lower

    def get_finished_sessions(self) -> list[dict]:
        """
        Get finished/closed sessions from Page 1 only (Maintenance Mode).

        Returns:
            List of session dictionaries
        """
        driver = None
        sessions = []
        seen_sitting_ids = set()

        try:
            logger.info(f"Opening sessions list: {self.config.SESSIONS_URL}")
            driver = self._create_driver()
            driver.get(self.config.SESSIONS_URL)
            time.sleep(3)

            self._handle_cookie_consent(driver)
            self._wait_for_angular(driver)
            self._scroll_page(driver)
            time.sleep(2)

            logger.info("Scraping Page 1 (Maintenance Mode)...")

            # METHOD 1: Extract sessions from Angular scope
            try:
                sessions_data = driver.execute_script("""
                    try {
                        var result = [];
                        var controllers = document.querySelectorAll('[ng-controller]');

                        for (var i = 0; i < controllers.length; i++) {
                            var scope = angular.element(controllers[i]).scope();
                            var items = scope.sittings || scope.items || scope.model || [];

                            if (items && items.length > 0) {
                                for (var j = 0; j < items.length; j++) {
                                    var item = items[j];
                                    var statusTitle = item.StatusTitle || '';
                                    var isFinished = item.StatusId == 60 || item.Status == 60;
                                    var statusLower = statusTitle.toLowerCase();
                                    var isValidStatus = statusLower.indexOf('завршена') >= 0 || 
                                                       statusLower.indexOf('затворена') >= 0;

                                    if (isFinished || isValidStatus) {
                                        result.push({
                                            id: item.Id,
                                            number: item.Number,
                                            status: statusTitle || 'Завршена',
                                            date: item.SittingDate
                                        });
                                    }
                                }
                            }
                        }
                        return result;
                    } catch(e) {
                        console.error('Session extraction error:', e);
                        return null;
                    }
                """)

                if sessions_data and len(sessions_data) > 0:
                    logger.info(f"✓ Found {len(sessions_data)} finished/closed sessions via Angular")
                    for item in sessions_data:
                        sitting_id = str(item.get('id', ''))
                        if sitting_id and sitting_id not in seen_sitting_ids:
                            seen_sitting_ids.add(sitting_id)
                            details_url = f"{self.config.BASE_URL}/detali-na-sednica.nspx?sittingId={sitting_id}"
                            sessions.append({
                                "sitting_id": sitting_id,
                                "details_url": details_url,
                                "status": item.get('status', 'Завршена'),
                                "number": item.get('number')
                            })

            except Exception as e:
                logger.warning(f"Angular session extraction failed: {e}")

            # METHOD 2: Fallback - Parse HTML
            if not sessions:
                logger.debug("Trying HTML parsing fallback...")
                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')

                for row in soup.find_all(['div', 'tr'], class_=re.compile(r'row|ng-scope')):
                    row_text = row.get_text()

                    if not ('Завршена' in row_text or 'Затворена' in row_text):
                        continue

                    link = row.find('a', href=re.compile(r'detali-na-sednica'))
                    if not link:
                        parent = row.find_parent(['div', 'tr'])
                        if parent:
                            link = parent.find('a', href=re.compile(r'detali-na-sednica'))

                    if link:
                        href = link.get('href', '')
                        if not href.startswith('http'):
                            href = urljoin(self.config.BASE_URL, href)

                        sitting_id = self._extract_sitting_id(href)
                        if sitting_id and sitting_id not in seen_sitting_ids:
                            seen_sitting_ids.add(sitting_id)
                            status = "Затворена" if "Затворена" in row_text else "Завршена"
                            sessions.append({
                                "sitting_id": sitting_id,
                                "details_url": href,
                                "status": status
                            })

            logger.info(f"✓ Total sessions found on Page 1: {len(sessions)}")

        except Exception as e:
            logger.error(f"Error getting sessions: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

        return sessions

    def get_stenograph_pdf_urls(self, details_url: str) -> list[tuple[str, dict]]:
        """
        Get ALL stenograph PDF/DOC URLs from a session details page.

        Args:
            details_url: URL of the session details page

        Returns:
            List of tuples: (download_url, parsed_info_dict)
        """
        driver = None
        found_files = []
        seen_urls = set()

        try:
            logger.info(f"Opening details page: {details_url}")
            driver = self._create_driver()
            driver.get(details_url)
            time.sleep(3)

            self._handle_cookie_consent(driver)
            self._wait_for_angular(driver)
            self._scroll_page(driver)
            time.sleep(2)

            # Check if session is finished/closed
            session_status = driver.execute_script("""
                try {
                    var controllers = document.querySelectorAll('[ng-controller]');
                    for (var i = 0; i < controllers.length; i++) {
                        var scope = angular.element(controllers[i]).scope();
                        if (scope && scope.item) {
                            return {
                                statusId: scope.item.StatusId,
                                statusTitle: scope.item.StatusTitle || ''
                            };
                        }
                    }
                    return null;
                } catch(e) { return null; }
            """)

            if session_status:
                status_id = session_status.get('statusId')
                status_title = session_status.get('statusTitle', '').lower()
                is_valid = (status_id == 60 or
                            'завршена' in status_title or
                            'затворена' in status_title)

                if not is_valid:
                    logger.info(
                        f"Session status '{session_status.get('statusTitle')}' is not finished/closed, skipping")
                    return found_files

            # METHOD 1: Extract ALL documents from Angular scope
            try:
                all_steno_docs = driver.execute_script("""
                    try {
                        var allDocs = [];
                        var controllers = document.querySelectorAll('[ng-controller]');

                        for (var i = 0; i < controllers.length; i++) {
                            var scope = angular.element(controllers[i]).scope();

                            if (scope && scope.item && scope.item.Documents && scope.item.Documents.length > 0) {
                                for (var j = 0; j < scope.item.Documents.length; j++) {
                                    var doc = scope.item.Documents[j];
                                    if (doc.DocumentTypeId == '57' || doc.DocumentTypeId == 57) {
                                        allDocs.push({
                                            id: doc.Id,
                                            title: doc.Title || doc.DocumentTitle || '',
                                            url: doc.Url || doc.DocumentUrl || '',
                                            typeId: doc.DocumentTypeId,
                                            typeName: doc.DocumentTypeName || '',
                                            isExported: doc.IsExported
                                        });
                                    }
                                }
                            }

                            if (scope && scope.Document && scope.Document.length > 0) {
                                for (var k = 0; k < scope.Document.length; k++) {
                                    var doc = scope.Document[k];
                                    if (doc.DocumentTypeId == '57' || doc.DocumentTypeId == 57) {
                                        var exists = allDocs.some(function(d) { return d.id == doc.Id; });
                                        if (!exists) {
                                            allDocs.push({
                                                id: doc.Id,
                                                title: doc.Title || '',
                                                url: doc.Url || '',
                                                typeId: doc.DocumentTypeId,
                                                isExported: doc.IsExported
                                            });
                                        }
                                    }
                                }
                            }
                        }
                        return allDocs;
                    } catch(e) {
                        console.error('Angular document extraction error:', e);
                        return [];
                    }
                """)

                if all_steno_docs and len(all_steno_docs) > 0:
                    logger.info(f"✓ Found {len(all_steno_docs)} stenograph documents via Angular scope")

                    for doc in all_steno_docs:
                        title = doc.get('title', '')
                        url = doc.get('url', '')
                        doc_id = doc.get('id', '')

                        if not url:
                            logger.debug(f"Skipping document with no URL: {title}")
                            continue

                        preview_url = f"{self.config.BASE_URL}/preview?id={doc_id}&url={url}&method=GetDocumentContent"

                        if preview_url in seen_urls:
                            continue
                        seen_urls.add(preview_url)

                        parsed_info = parse_pdf_link_text(title)

                        if not parsed_info:
                            parsed_info = generate_fallback_filename(title, doc_id, url)
                        else:
                            if '.doc' in url.lower() and '.docx' not in url.lower():
                                parsed_info['filename'] = parsed_info['filename'].replace('.pdf', '.doc')
                            elif '.docx' in url.lower():
                                parsed_info['filename'] = parsed_info['filename'].replace('.pdf', '.docx')

                        found_files.append((preview_url, parsed_info))
                        logger.info(f"  ✓ [{len(found_files)}] {parsed_info['filename']}")

            except Exception as e:
                logger.warning(f"Angular scope extraction failed: {e}")
                import traceback
                logger.debug(traceback.format_exc())

            # METHOD 2: Look for ALL "Стенографски" links in rendered HTML
            try:
                logger.debug("Scanning HTML for additional stenograph links...")
                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')

                steno_rows = soup.find_all('tr', attrs={'ng-if': re.compile(r"DocumentTypeId\s*==\s*['\"]?57")})

                if steno_rows:
                    logger.debug(f"Found {len(steno_rows)} stenograph table rows in HTML")

                    for row in steno_rows:
                        link = row.find('a', href=True)
                        if link:
                            link_text = link.get_text(strip=True)
                            href = link.get('href', '')

                            if not href.startswith('http'):
                                href = urljoin(self.config.BASE_URL, href)

                            if href in seen_urls:
                                continue
                            seen_urls.add(href)

                            parsed_info = parse_pdf_link_text(link_text)

                            if parsed_info:
                                if 'url=' in href:
                                    url_match = re.search(r'url=([^&]+)', href)
                                    if url_match:
                                        actual_url = url_match.group(1)
                                        if '.doc' in actual_url.lower() and '.docx' not in actual_url.lower():
                                            parsed_info['filename'] = parsed_info['filename'].replace('.pdf', '.doc')
                                        elif '.docx' in actual_url.lower():
                                            parsed_info['filename'] = parsed_info['filename'].replace('.pdf', '.docx')

                                found_files.append((href, parsed_info))
                                logger.info(f"  ✓ [{len(found_files)}] Found via HTML row: {parsed_info['filename']}")

                for link in soup.find_all('a', href=True):
                    link_text = link.get_text(strip=True)
                    href = link.get('href', '')

                    if not re.search(r'[Сс]тенографски|[Сс]тенограм', link_text):
                        continue

                    if not href.startswith('http'):
                        href = urljoin(self.config.BASE_URL, href)

                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    parsed_info = parse_pdf_link_text(link_text)

                    if parsed_info:
                        if 'url=' in href:
                            url_match = re.search(r'url=([^&]+)', href)
                            if url_match:
                                actual_url = url_match.group(1)
                                if '.doc' in actual_url.lower() and '.docx' not in actual_url.lower():
                                    parsed_info['filename'] = parsed_info['filename'].replace('.pdf', '.doc')
                                elif '.docx' in actual_url.lower():
                                    parsed_info['filename'] = parsed_info['filename'].replace('.pdf', '.docx')

                        found_files.append((href, parsed_info))
                        logger.info(f"  ✓ [{len(found_files)}] Found via keyword: {parsed_info['filename']}")

            except Exception as e:
                logger.warning(f"HTML keyword search failed: {e}")

            # METHOD 3: Use Selenium to find ALL links directly
            if len(found_files) == 0:
                try:
                    logger.debug("Trying Selenium element search for all document links...")

                    selectors = [
                        "tr[ng-if*='57'] a[href]",
                        "tr.ng-scope a[href*='preview']",
                        "table.table a[href*='preview']",
                        "a[href*='GetDocumentContent']"
                    ]

                    for selector in selectors:
                        try:
                            links = driver.find_elements(By.CSS_SELECTOR, selector)

                            for link in links:
                                try:
                                    link_text = link.text.strip()
                                    href = link.get_attribute('href')

                                    if not href or href in seen_urls:
                                        continue

                                    if re.search(r'[Сс]тенографски|[Сс]тенограм', link_text):
                                        seen_urls.add(href)
                                        parsed_info = parse_pdf_link_text(link_text)

                                        if parsed_info:
                                            found_files.append((href, parsed_info))
                                            logger.info(
                                                f"  ✓ [{len(found_files)}] Found via Selenium: {parsed_info['filename']}")
                                except StaleElementReferenceException:
                                    continue
                                except Exception:
                                    continue
                        except Exception:
                            continue

                except Exception as e:
                    logger.warning(f"Selenium element search failed: {e}")

            if found_files:
                logger.info(f"✓ Total stenograph documents found: {len(found_files)}")
            else:
                debug_filename = f"debug_details_{int(time.time())}.html"
                try:
                    with open(debug_filename, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.warning(f"⚠️ NO STENOGRAPH DOCUMENTS FOUND!")
                    logger.warning(f"Debug HTML saved to: {debug_filename}")
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error getting stenograph PDFs: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

        return found_files

    def download_pdf(self, pdf_url: str, output_path: Path) -> tuple[bool, Optional[Path]]:
        """
        Download file and correct extension based on content.

        Args:
            pdf_url: URL to download from
            output_path: Initial output path

        Returns:
            tuple: (success: bool, actual_path: Path or None)
        """
        try:
            logger.info(f"Downloading: {pdf_url}")

            response = self.session.get(
                pdf_url, stream=True, timeout=120, verify=False, allow_redirects=True
            )
            response.raise_for_status()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(".tmp")

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = temp_path.stat().st_size
            if file_size < 1000:
                logger.warning(f"Downloaded file too small: {file_size} bytes")
                temp_path.unlink()
                return False, None

            is_pdf = False
            is_docx = False

            with open(temp_path, "rb") as f:
                header = f.read(8)

                if header.startswith(b'%PDF'):
                    is_pdf = True
                elif header.startswith(b'PK\x03\x04'):
                    is_docx = True

            original_suffix = output_path.suffix.lower()

            if is_pdf:
                correct_suffix = '.pdf'
            elif is_docx:
                correct_suffix = '.docx'
            else:
                correct_suffix = original_suffix if original_suffix else '.doc'

            if correct_suffix != original_suffix:
                logger.info(
                    f"Detected {correct_suffix.upper()[1:]} content. Correcting extension from {original_suffix} to {correct_suffix}")
                final_path = output_path.with_suffix(correct_suffix)
            else:
                final_path = output_path

            if final_path.exists():
                final_path.unlink()

            temp_path.rename(final_path)

            logger.info(f"✓ Downloaded: {final_path.name} ({file_size / 1024:.1f} KB)")
            return True, final_path

        except Exception as e:
            logger.error(f"Download failed: {e}")
            temp_path = output_path.with_suffix(".tmp")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
            return False, None