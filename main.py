import time
import re
import logging
import base64
import os
import json
import requests
import random
from datetime import datetime
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException
)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('vfs_automation.log'),
        logging.StreamHandler()
    ]
)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']
MAX_RETRIES = 3000
CREDENTIALS_BASE_PATH = "credentials_"
TELEGRAM_BOT_TOKEN = "****************_**************" 
TELEGRAM_CHAT_ID = "*******************" 



def get_driver_options():
    """Configure Chrome options with enhanced anti-detection settings"""
    options = uc.ChromeOptions()
    
    # Basic options
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
   
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.images": 1,
    }
    options.add_experimental_option("prefs", prefs)
    
    return options

def randomize_browser_fingerprint(driver):
    """Randomize browser fingerprint to appear as different devices"""
    try:
        # Randomize viewport size
        width = random.randint(1400, 1920)
        height = random.randint(900, 1080)
        driver.set_window_size(width, height)
        
        # Randomize screen resolution in browser
        driver.execute_script(
            "Object.defineProperty(window, 'screen', {"
            "value: {"
            f"width: {width},"
            f"height: {height},"
            "availWidth: window.screen.availWidth,"
            "availHeight: window.screen.availHeight,"
            "colorDepth: window.screen.colorDepth,"
            "pixelDepth: window.screen.pixelDepth,"
            "}, configurable: false});"
        )
        
        # Randomize timezone
        timezones = ["Asia/Kolkata"]
        driver.execute_script(
            "Object.defineProperty(Intl, 'DateTimeFormat', {"
            "value: class extends Intl.DateTimeFormat {"
            "constructor(...args) {"
            f"super(...args, {{ timeZone: '{random.choice(timezones)}' }});"
            "}"
            "}, configurable: false});"
        )
        
        # Remove navigator.webdriver flag
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {"
            "get: () => undefined"
            "});"
        )
        
        # Randomize language
        languages = ["en-US", "en-GB"]
        driver.execute_script(
            "Object.defineProperty(navigator, 'language', {"
            f"value: '{random.choice(languages)}'"
            "});"
        )
        
    except Exception as e:
        logging.warning(f"Could not randomize fingerprint: {e}")

def clean_browser_data(driver):
    """Clean browser data between sessions"""
    try:
        driver.execute_cdp_cmd('Storage.clearDataForOrigin', {
            "origin": "*",
            "storageTypes": "all",
        })
        logging.info("Browser data cleaned between sessions")
    except Exception as e:
        logging.warning(f"Could not clean browser data: {e}")

def send_telegram_message(message):
    """Send a message to a Telegram chat using the bot API."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logging.error(f"Failed to send Telegram message: {response.text}")
        else:
            logging.info("Telegram message sent successfully.")
    except Exception as e:
        logging.error(f"Error sending Telegram message: {e}")

def send_email(service, sender_email, recipient_email, subject, body):
    """Send an email using the Gmail API."""
    try:
        message = {
            'raw': base64.urlsafe_b64encode(
                f"From: {sender_email}\n"
                f"To: {recipient_email}\n"
                f"Cc: cli**********@gmail.com\n"
                f"Subject: {subject}\n\n"
                f"{body}".encode('utf-8')
            ).decode('utf-8')
        }
        service.users().messages().send(userId='me', body=message).execute()
        logging.info(f"Email sent to {recipient_email}.")
    except HttpError as e:
        logging.error(f"Gmail API error while sending email: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while sending email: {e}")

def get_account_folders():
    """Get list of credential folders (e.g., credentials_1, credentials_2)."""
    folders = [f for f in os.listdir() if os.path.isdir(f) and f.startswith(CREDENTIALS_BASE_PATH)]
    folders.sort()
    return folders

def get_last_account_index():
    """Read the last used account index from last_account.txt."""
    try:
        with open('last_account.txt', 'r') as f:
            index = int(f.read().strip())
        return index
    except (FileNotFoundError, ValueError):
        return 0

def save_last_account_index(index, total_accounts):
    """Save the next account index, looping back to 0 if at the end."""
    next_index = (index + 1) % total_accounts
    with open('last_account.txt', 'w') as f:
        f.write(str(next_index))

def load_account_details(folder):
    """Load email and password from account.json in the specified folder."""
    try:
        with open(os.path.join(folder, 'account.json'), 'r') as f:
            data = json.load(f)
        return data.get('email'), data.get('password')
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Failed to load account details from {folder}/account.json: {e}")
        return None, None

def get_gmail_service(folder):
    """Authenticate and return Gmail API service for the specified account folder."""
    try:
        creds = None
        token_path = os.path.join(folder, 'token.json')
        credentials_path = os.path.join(folder, 'credentials.json')
        
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
        except FileNotFoundError:
            logging.info(f"Token file not found in {folder}, initiating OAuth flow...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            except FileNotFoundError as e:
                logging.error(f"Credentials file not found in {folder}: {e}")
                raise
            except Exception as e:
                logging.error(f"OAuth flow failed for {folder}: {e}")
                raise
        return build('gmail', 'v1', credentials=creds)
    except HttpError as e:
        logging.error(f"Gmail API error during authentication for {folder}: {e}")
        raise
    except Exception as e:
        logging.error(f"Failed to initialize Gmail service for {folder}: {e}")
        raise

def fetch_otp_from_email(service, sender="donotreply@vfshelpline.com", max_wait=240, time_window=90):
    """Fetch OTP from the latest email from the specified sender within the given time window."""
    try:
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                results = service.users().messages().list(userId='me', q=f'from:{sender}').execute()
                messages = results.get('messages', [])
                if not messages:
                    logging.info("No emails found. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue

                message = service.users().messages().get(userId='me', id=messages[0]['id']).execute()
                internal_date = int(message.get('internalDate', 0)) / 1000
                current_time = time.time()

                if current_time - internal_date <= time_window:
                    payload = message.get('payload', {})
                    body = ''
                    if 'parts' in payload:
                        for part in payload['parts']:
                            if part['mimeType'] == 'text/plain':
                                body = part['body']['data']
                                break
                    else:
                        body = payload['body']['data']
                    
                    try:
                        body = base64.urlsafe_b64decode(body).decode('utf-8')
                    except base64.binascii.Error as e:
                        logging.error(f"Base64 decoding error: {e}")
                        time.sleep(10)
                        continue
                    
                    otp_match = re.search(r'\b\d{6}\b', body)
                    if otp_match:
                        otp = otp_match.group(0)
                        logging.info(f"OTP found: {otp} (Email received at {time.ctime(internal_date)})")
                        return otp
                    else:
                        logging.info("No OTP found in the latest email. Retrying in 10 seconds...")
                else:
                    logging.info(f"Latest email is too old (received at {time.ctime(internal_date)}). Retrying in 10 seconds...")
                
                time.sleep(10)
            except HttpError as e:
                if e.resp.status == 429:
                    logging.warning("Gmail API rate limit exceeded. Waiting 30 seconds before retrying...")
                    time.sleep(30)
                else:
                    logging.error(f"Gmail API error: {e}")
                    return None
        
        logging.warning(f"No OTP found within {max_wait} seconds.")
        return None
    except Exception as e:
        logging.error(f"Unexpected error fetching OTP: {e}")
        return None

def human_typing(element, text, delay=0.2):
    """Simulate human-like typing into an element."""
    try:
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(delay*0.5, delay*1.5)) 
    except StaleElementReferenceException as e:
        logging.error(f"Stale element during typing: {e}")
        raise
    except Exception as e:
        logging.error(f"Error during typing: {e}")
        raise

def click_with_retry(driver, by, value, retries=3, delay=6, element_description="element"):
    """Click an element with retries, handling overlays and other issues."""
    for attempt in range(retries):
        try:
            time.sleep(8)
            element = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((by, value)))
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            
            # Add human-like mouse movement simulation
            action = webdriver.ActionChains(driver)
            action.move_to_element(element).pause(random.uniform(0.1, 0.5)).click().perform()
            
            logging.info(f"Successfully clicked {element_description}")
            return True
        except (TimeoutException, ElementClickInterceptedException, StaleElementReferenceException) as e:
            logging.warning(f"Retry {attempt+1}/{retries} failed for {element_description}: {type(e)._name_} - {str(e)}")
            time.sleep(delay)
        except Exception as e:
            logging.error(f"Unexpected error during click on {element_description}: {type(e)._name_} - {str(e)}")
            raise
    logging.error(f"Failed to click {element_description} after {retries} retries.")
    return False

def check_and_select_captcha(driver, wait):
    """Check if CAPTCHA checkbox is present and select it if found."""
    try:
        captcha_label = driver.find_element(By.CSS_SELECTOR, "label.cb-lb")
        logging.info("CAPTCHA checkbox found, selecting...")
        checkbox = captcha_label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        
        # Human-like interaction with CAPTCHA
        action = webdriver.ActionChains(driver)
        action.move_to_element(checkbox).pause(random.uniform(0.2, 0.8)).click().perform()
        
        time.sleep(random.uniform(3, 7)) 
        logging.info("CAPTCHA checkbox selected.")
    except NoSuchElementException:
        logging.info("No CAPTCHA checkbox found, assuming auto-selected or not required.")
    except Exception as e:
        logging.error(f"Failed to select CAPTCHA: {e}")
        logging.info("Manual CAPTCHA input required.")
        input("Please complete CAPTCHA manually, then press Enter to continue...")

def login(driver, wait, service, email, password):
    """Perform login process with OTP automation and CAPTCHA handling."""
    try:
        driver.get("https://visa.vfsglobal.com/ind/en/deu/login")
        logging.info("Navigating to login page...")
        WebDriverWait(driver, 30).until(EC.url_contains("/login"))
        logging.info("Login page loaded.")
        time.sleep(random.uniform(10, 12))

        try:
            cookie_button = wait.until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
            time.sleep(random.uniform(10, 12))
            cookie_button.click()
            logging.info("Accepted cookies.")
        except (NoSuchElementException, TimeoutException):
            logging.info("No cookie consent button found or already accepted.")

        email_input = wait.until(EC.element_to_be_clickable((By.ID, "email")))
        email_input.click()
        human_typing(email_input, email, delay=0.2)

        password_input = wait.until(EC.element_to_be_clickable((By.ID, "password")))
        password_input.click()
        human_typing(password_input, password, delay=0.2)

        check_and_select_captcha(driver, wait)
        
        # Random delay before submission
        time.sleep(random.uniform(0.5, 2.0))
        password_input.send_keys(Keys.ENTER)
        logging.info("Submitted credentials.")
        time.sleep(random.uniform(10, 12))

        logging.info("Fetching OTP from email...")
        otp = fetch_otp_from_email(service)
        if otp:
            logging.info(f"OTP found: {otp}")
            try:
                otp_input = wait.until(EC.element_to_be_clickable((By.ID, "mat-input-5")))
            except (TimeoutException, NoSuchElementException):
                logging.warning("OTP input ID 'mat-input-5' not found, trying fallback selector...")
                otp_input = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@formcontrolname='otp']")))
            otp_input.click()
            human_typing(otp_input, otp, delay=0.4)
            logging.info("Submitted OTP.")

            check_and_select_captcha(driver, wait)
            time.sleep(random.uniform(1, 3))
            logging.info("Submitting OTP with Enter...")
            otp_input.send_keys(Keys.ENTER)
        else:
            logging.warning("No OTP found. Manual OTP and CAPTCHA input required.")
            return False

        try:
            WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
            logging.info("Login successful — dashboard loaded!")
            return True
        except TimeoutException:
            try:
                error_message = driver.find_element(By.CSS_SELECTOR, ".error-message, .alert-danger").text
                logging.error(f"Login failed with error: {error_message}")
            except NoSuchElementException:
                logging.error("Login failed, no error message found on page.")
            return False

    except (TimeoutException, NoSuchElementException, ElementClickInterceptedException) as e:
        logging.error(f"Login failed due to Selenium error: {e}")
        return False
    except WebDriverException as e:
        logging.error(f"Browser error during login: {e}")
        raise
    except Exception as e:
        logging.error(f"Unexpected error during login: {e}")
        raise


def try_booking(driver, wait, service, email, max_attempts=2):
    """Attempt to book an appointment with retries."""
    for attempt in range(1, max_attempts + 1):
        try:
            logging.info(f"Attempting booking (Attempt {attempt}/{max_attempts}) for {email}...")
            
            # Ensure dashboard is loaded
            for _ in range(3):
                try:
                    WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, "//button[.//span[contains(text(), 'Start New Booking')]]"))
                    )
                    logging.info("Dashboard fully loaded.")
                    break
                except (TimeoutException, WebDriverException) as e:
                    logging.warning(f"Retry dashboard load: {type(e)._name_} - {str(e)}")
                    driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                    time.sleep(random.uniform(4, 6))
            else:
                logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to load dashboard")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to load dashboard")
                if attempt < max_attempts:
                    logging.info(f"Waiting 160-170 seconds before next attempt for {email}...")
                    send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting 160-170 seconds before next attempt for {email}...")
                    time.sleep(random.uniform(160, 170))
                    continue
                return False

            # Click "Start New Booking"
            logging.info("Clicking 'Start New Booking'...")
            selectors = [
                (By.XPATH, "//button[contains(@class, 'd-lg-inline-block') and .//span[contains(text(), 'Start New Booking')]]"),
                (By.XPATH, "//button[.//span[contains(text(), 'Start New Booking')]]"),
                (By.CSS_SELECTOR, "button.d-lg-inline-block span"),
            ]
            
            booking_started = False
            for by, value in selectors:
                try:
                    if click_with_retry(driver, by, value, retries=3, delay=6, element_description="Start New Booking button"):
                        booking_started = True
                        break
                except Exception as e:
                    logging.warning(f"Failed with selector {by}: {value} - {type(e)._name_} - {str(e)}")
                    continue
            
            if not booking_started:
                logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to click 'Start New Booking'")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to click 'Start New Booking'")
                if attempt < max_attempts:
                    logging.info(f"Waiting 160-170 seconds before next attempt for {email}...")
                    send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting 160-170 seconds before next attempt for {email}...")
                    time.sleep(random.uniform(160, 170))
                    continue
                return False

            wait.until(EC.url_contains("application-detail"))
            logging.info("Navigated to booking page.")
            time.sleep(random.uniform(8, 12))

            # Select Application Centre
            logging.info("Selecting Application Centre...")
            for _ in range(3):
                try:
                    wait.until(EC.element_to_be_clickable((By.ID, "mat-select-0"))).click()
                    time.sleep(4)
                    del_option_xpath = "//mat-option[@id='DEL']//span[contains(text(), 'New Delhi')]"
                    wait.until(EC.visibility_of_element_located((By.XPATH, del_option_xpath))).click()
                    break
                except (TimeoutException, StaleElementReferenceException) as e:
                    logging.warning(f"Retry failed for Application Centre selection: {type(e)._name_} - {str(e)}")
                    time.sleep(random.uniform(8, 10))
            else:
                logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to select Application Centre")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to select Application Centre")
                if attempt < max_attempts:
                    logging.info(f"Navigating back to dashboard and waiting 160-170 seconds...")
                    try:
                        driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                        WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                    except Exception as nav_error:
                        logging.warning(f"Failed to navigate to dashboard for retry: {nav_error}")
                    time.sleep(random.uniform(160, 170))
                    continue
                return False

            time.sleep(random.uniform(6, 8))

            # Select Appointment Category
            logging.info("Selecting Appointment Category...")
            for _ in range(3):
                try:
                    wait.until(EC.element_to_be_clickable((By.ID, "mat-select-4"))).click()
                    time.sleep(4)
                    del_option_xpath = "//mat-option[@id='NVEMP']//span[contains(normalize-space(), 'National Visa (stay of more than 90 days): Employment')]"
                    wait.until(EC.visibility_of_element_located((By.XPATH, del_option_xpath))).click()
                    break
                except (TimeoutException, StaleElementReferenceException) as e:
                    logging.warning(f"Retry failed for Appointment Category selection: {type(e)._name_} - {str(e)}")
                    time.sleep(random.uniform(8, 10))
            else:
                logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to select Appointment Category")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to select Appointment Category")
                if attempt < max_attempts:
                    logging.info(f"Navigating back to dashboard and waiting 160-170 seconds...")
                    try:
                        driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                        WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                    except Exception as nav_error:
                        logging.warning(f"Failed to navigate to dashboard for retry: {nav_error}")
                    time.sleep(random.uniform(160, 170))
                    continue
                return False

            time.sleep(random.uniform(6, 8))

            # Select Sub-Category
            logging.info("Selecting Sub-Category...")
            for _ in range(3):
                try:
                    wait.until(EC.element_to_be_clickable((By.ID, "mat-select-2"))).click()
                    time.sleep(4)
                    del_option_xpath = "//mat-option[@id='NVBA']//span[starts-with(normalize-space(), 'Basic or advanced in-company or school-based vocational training')]"
                    wait.until(EC.visibility_of_element_located((By.XPATH, del_option_xpath))).click()
                    break
                except (TimeoutException, StaleElementReferenceException) as e:
                    logging.warning(f"Retry failed for Sub-Category selection: {type(e)._name_} - {str(e)}")
                    time.sleep(random.uniform(8, 10))
            else:
                logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to select Sub-Category")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to select Sub-Category")
                if attempt < max_attempts:
                    logging.info(f"Navigating back to dashboard and waiting 160-170 seconds...")
                    try:
                        driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                        WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                    except Exception as nav_error:
                        logging.warning(f"Failed to navigate to dashboard for retry: {nav_error}")
                    time.sleep(random.uniform(160, 170))
                    continue
                return False

            time.sleep(random.uniform(2, 4))

            # Check Continue button availability
            logging.info("Checking Step 4: Continue button availability...")
            try:
                continue_button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[.//span[normalize-space()='Continue']]")))
                is_disabled = continue_button.get_attribute("disabled")
            except Exception as e:
                logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to locate Continue button - {str(e)}")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: Failed to locate Continue button")
                if attempt < max_attempts:
                    logging.info(f"Navigating back to dashboard and waiting 160-170 seconds...")
                    try:
                        driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                        WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                    except Exception as nav_error:
                        logging.warning(f"Failed to navigate to dashboard for retry: {nav_error}")
                    time.sleep(random.uniform(160, 170))
                    continue
                return False

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if is_disabled is not None:
                logging.warning(f"[{timestamp}] Attempt {attempt}/{max_attempts} - Slot NOT available for {email}. Continue button is disabled.")
                send_telegram_message(f"[{timestamp}] Attempt {attempt}/{max_attempts} - Slot NOT available for {email}. Continue button is disabled.")
                
                if attempt < max_attempts:
                    logging.info(f"Navigating back to dashboard for retry...")
                    try:
                        driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                        WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                        logging.info("Successfully navigated back to dashboard for retry.")
                    except Exception as nav_error:
                        logging.warning(f"Failed to navigate to dashboard for retry: {nav_error}")
                        send_telegram_message(f"[{timestamp}] Failed to navigate to dashboard for retry: {nav_error}")
                    
                    # Wait AFTER navigating back to dashboard
                    logging.info(f"Waiting 160-170 seconds before next attempt for {email}...")
                    send_telegram_message(f"[{timestamp}] Waiting 160-170 seconds before next attempt for {email}...")
                    time.sleep(random.uniform(160, 170))
                    continue
                
                return False
            else:
                # Continue button is enabled - slots available!
                logging.info(f"[{timestamp}] SUCCESS! Slots available for {email}. Continue button is enabled.")
                send_telegram_message(f"[{timestamp}] SUCCESS! Slots available for {email}. Continue button is enabled.")
                send_email(
                    service=service,
                    sender_email=email,
                    recipient_email="s*************@gmail.com",
                    subject="VFS Slot Available",
                    body=f"Slot available for {email} at {timestamp}. Please proceed manually on the VFS website."
                )
                return True
                
        except WebDriverException as e:
            logging.error(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Browser error during attempt {attempt}/{max_attempts} for {email}: {type(e)._name_} - {str(e)}")
            send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Browser error during attempt {attempt}/{max_attempts} for {email}: {str(e)}")
            # For browser errors, we should close browser and move to next account
            raise
            
        except Exception as e:
            logging.warning(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: {type(e)._name_} - {str(e)}")
            send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Attempt {attempt}/{max_attempts} failed for {email}: {str(e)}")
            
            if attempt < max_attempts:
                logging.info(f"Navigating back to dashboard and waiting 160-170 seconds...")
                try:
                    driver.get("https://visa.vfsglobal.com/ind/en/deu/dashboard")
                    WebDriverWait(driver, 30).until(EC.url_contains("/dashboard"))
                except Exception as nav_error:
                    logging.warning(f"Failed to navigate to dashboard for retry: {nav_error}")
                time.sleep(random.uniform(160, 170))
                continue
            
            return False
    
    return False


def main():
    """Main loop to run the automation with multiple accounts."""
    account_folders = get_account_folders()
    if not account_folders:
        logging.error("No credential folders found. Please create folders like credentials_1, credentials_2, etc.")
        print("No credential folders found. Please create folders like credentials_1, credentials_2, etc.")
        send_telegram_message("Script terminated: No credential folders found.")
        return

    retry_count = 0
    consecutive_failed_login_count = 0 

    while retry_count < MAX_RETRIES:
        account_index = get_last_account_index()
        folder = account_folders[account_index]
        logging.info(f"Using account from folder: {folder}")

        email, password = load_account_details(folder)
        if not email or not password:
            logging.error(f"Invalid account details in {folder}. Skipping to next account.")
            send_telegram_message(f"Invalid account details in {folder}. Skipping to next account.")
            save_last_account_index(account_index, len(account_folders))
            retry_count += 1
            # Always long wait for invalid credential skip
            wait_time = random.randint(3600, 4200)
            logging.info(f"Waiting {wait_time} seconds before next account (invalid credentials)...")
            send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting {wait_time} seconds before next account (invalid credentials)...")
            time.sleep(wait_time)
            continue

        login_successful = False
        booking_completed = False

        options = get_driver_options()
        driver = None
        service = None

        try:
            logging.info(f"Starting new session with account: {email}")
            send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting browser session for {email}")
            time.sleep(random.uniform(2, 5))

            # Initialize browser
            try:
                driver = uc.Chrome(options=options)
                logging.info("Browser initialized successfully.")
                time.sleep(15)
                driver.execute_script("return true;")
            except Exception as e:
                logging.error(f"Failed to initialize browser: {type(e).__name__} - {str(e)}")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Browser initialization failed for {email}")
                raise Exception("Browser initialization failed")

            wait = WebDriverWait(driver, 60)

            try:
                randomize_browser_fingerprint(driver)
            except Exception as e:
                logging.error(f"Failed to randomize browser fingerprint: {e}")

            service = get_gmail_service(folder)

            # Attempt login
            try:
                if login(driver, wait, service, email, password):
                    login_successful = True
                    logging.info(f"Login successful for {email}")
                    send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Login successful for {email}")
                else:
                    logging.error(f"Login failed for {email}")
                    send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Login failed for {email}")
                    raise Exception("Login failed")
            except Exception as login_error:
                logging.error(f"Login error for {email}: {login_error}")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Login error for {email}")
                raise Exception("Login failed")

            # If login successful, attempt booking
            if login_successful:
                time.sleep(random.uniform(10, 15))
                try:
                    success = try_booking(driver, wait, service, email)
                    if success:
                        logging.info("Booking successful! Slots are available.")
                        print("Booking successful! Slots are available. Please proceed manually.")
                        send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🎉 BOOKING SUCCESSFUL for {email}! Slots are available. Please proceed manually.")
                        input("Press Enter to close browser...")
                        booking_completed = True
                        return
                    else:
                        logging.info(f"All booking attempts failed for {email}. No slots available after 2 attempts.")
                        send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] All booking attempts failed for {email}. No slots available.")
                except Exception as booking_error:
                    logging.error(f"Booking error for {email}: {booking_error}")
                    send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Booking error for {email}: {str(booking_error)}")
                    raise

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error occurred for {email} (Attempt {retry_count}/{MAX_RETRIES}): {error_msg}")
            send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error for {email}: {error_msg}")

            # Save debug information
            if driver:
                try:
                    clean_browser_data(driver)
                    logging.info(f"Current URL: {driver.current_url}")
                    with open(f'error_page_source_{folder}.html', 'w', encoding='utf-8') as f:
                        f.write(driver.page_source)
                    logging.info(f"Saved page source to error_page_source_{folder}.html for debugging.")
                except Exception as save_error:
                    logging.error(f"Failed to save page source: {save_error}")

        finally:
            # Always close browser
            if driver:
                try:
                    driver.quit()
                    logging.info("Browser closed successfully.")
                    send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Browser closed for {email}")
                except Exception as quit_error:
                    logging.error(f"Error closing browser: {quit_error}")

            # If booking was successful, exit
            if booking_completed:
                return

            # Move to next account
            save_last_account_index(account_index, len(account_folders))
            retry_count += 1

            # Update consecutive_failed_login_count logic
            if login_successful:
                consecutive_failed_login_count = 0  # reset count after success
                wait_time = random.randint(3600, 4200)
                logging.info("Login successful, waiting before trying next account...")
            else:
                consecutive_failed_login_count += 1
                if consecutive_failed_login_count <= 2:
                    wait_time = random.randint(10, 15)
                    logging.info(f"Login failed (attempt {consecutive_failed_login_count}/2), waiting short time before next account...")
                else:
                    wait_time = random.randint(3600, 4200)
                    logging.info(f"Login failed (attempt {consecutive_failed_login_count}), waiting long time before next account...")

            # Wait accordingly or stop script
            if retry_count < MAX_RETRIES:
                logging.info(f"Waiting {wait_time} seconds before next account...")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting {wait_time} seconds before next account...")
                time.sleep(wait_time)
            else:
                logging.error("Maximum retries reached. Stopping script.")
                print("Maximum retries reached. Please check logs and configuration.")
                send_telegram_message(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Script terminated: Maximum retries reached.")
                return


if __name__ == "__main__":
    main()