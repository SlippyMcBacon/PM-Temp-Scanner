from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from concurrent.futures import ThreadPoolExecutor
import time
import re
import calendar
import random
import os
import requests
from datetime import datetime

# do for every place/airport ticker pair in a list
# go to wunderground + get high for the airport
# https://www.wunderground.com/hourly/{airport ticker}/date/{year}-{month}-{day}
# go to robinhood website and get the cheapest contract that is < 3 degrees of high
# https://robinhood.com/us/en/prediction-markets/climate/events/{place}-daily-temperature-high-{full month name}-{day}-{year}-{month abreviated name}-{day}-{year}/
# print temperature of cheapest contract found and what place it is in

locations = [
    ("washington-dc", "KDCA"),
    ("los-angeles", "KLAX"),
    ("chicago", "KMDW"),
    ("new-york-city", "KLGA"),
    ("san-francisco", "KSFO"),
    ("miami", "KMIA"),
    ("oklahoma-city", "KOKC"),
    ("seattle", "KSEA"),
    ("austin", "KAUS"),
    ("philadelphia", "KPHL"),
    ("atlanta", "KATL"),
    ("dallas", "KDFW"),
    ("houston", "KHOU"),
    ("nashville", "KBNA"),
    ("minneapolis-saint-paul", "KMSP"),
    ("phoenix", "KPHX"),
    ("las-vegas", "KLAS"),
    ("boston", "KBOS"),
    ("jacksonville", "KJAX"),
    ("denver", "KBKF"),
    ("detroit", "KDTW"),
    ("charlotte", "KCLT"),
    ("san-antonio", "KSAT")
]

def format_date_parts(year, month, day):
    m_full = calendar.month_name[month].lower()   # april
    m_abbr = calendar.month_abbr[month].lower()   # apr
    d_str = f"{year}-{month:02d}-{day:02d}"       # 2026-04-21
    return m_full, m_abbr, d_str

def get_driver():
    options = webdriver.ChromeOptions()
    options.binary_location = "/usr/bin/google-chrome"
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.page_load_strategy = 'eager'
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    #use system installed chrome driver
    service = Service()
    return webdriver.Chrome(service=service, options=options)

def get_max_temp(driver, airport, date_str):
    url = f"https://www.wunderground.com/hourly/{airport}/date/{date_str}"
    driver.get(url)

    # Wait until temperature cells are loaded
    cells = WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "td.mat-column-temperature")
        )
    )

    wait = WebDriverWait(driver, 20)

    # Wait for actual numbers, not just table cells
    max = 0
    count = 0

    for cell in cells:
        try:
            # Find the span inside each cell
            span = cell.find_element(By.CSS_SELECTOR, "span.wu-value")
            text = span.text.strip()

            if text.isdigit():
                value = int(text)

                if value > max:
                    max = value
                    count = 1
                elif value == max:
                    count += 1
        except:
            continue

    if max == 0:
        raise Exception("No temperatures found")

    return max, count

def safe_get_max_temp(driver, airport, date_str, retries=3):
    for attempt in range(retries):
        try:
            return get_max_temp(driver, airport, date_str)
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2)  # brief backoff

def expand_all_contracts(driver, wait):
    while True:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button.css-10yetpw")
        if not buttons:
            break

        for button in buttons:
            try:
                driver.execute_script("arguments[0].click();", button)
            except:
                continue
    #while True:
        #try:
            # Wait briefly for the button to be clickable
            #button = WebDriverWait(driver, 3).until(
            #    EC.element_to_be_clickable(
            #        (By.CSS_SELECTOR, "button.css-10yetpw")
            #    )
            #)

            # Scroll into view (important for click reliability)
            #driver.execute_script("arguments[0].scrollIntoView(true);", button)
            #time.sleep(0.5)

            #driver.execute_script("arguments[0].click();", button)
            #time.sleep(1.5)  # allow new contracts to load

        #except TimeoutException:
            # No more button → all contracts loaded
        #    break
        #except StaleElementReferenceException:
            # DOM refreshed → retry loop
        #    continue

def get_best_contract(driver, place, year, month, day, max_temp, count):
    month_full, month_abbr, _ = format_date_parts(year, month, day)
    day2 = f"{day:02d}"
    url = f"https://robinhood.com/us/en/prediction-markets/climate/events/" \
          f"{place}-daily-temperature-high-{month_full}-{day}-{year}-" \
          f"{month_abbr}-{day2}-{year}/"

    driver.get(url)

    wait = WebDriverWait(driver, 15)

    # Wait for the Contracts container
    container = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//div[@role='tablist' and @aria-label='Contracts']")
        )
    )

    #expand contracts
    expand_all_contracts(driver, wait)

    # Re-find container after DOM updates
    container = driver.find_element(
        By.XPATH, "//div[@role='tablist' and @aria-label='Contracts']"
    )

    # Get each contract (each tab)
    contracts_elements = container.find_elements(By.XPATH, ".//div[@role='tab']")

    contracts = []

    for contract in contracts_elements:
        try:
            # Each contract has two inner divs:
            # [0] = label, [1] = price
            inner_divs = contract.find_elements(By.XPATH, "./div")

            if len(inner_divs) < 2:
                continue

            label_text = inner_divs[0].text.strip()
            price_text = inner_divs[1].text.strip()

            # Extract temperature (e.g. "Greater than 60")
            temp_match = re.search(r"(\d+)", label_text)
            if not temp_match:
                continue

            temp_val = int(temp_match.group(1))

            # Extract price (e.g. "63¢")
            price_match = re.search(r"(\d+)", price_text)
            if not price_match:
                continue

            price = int(price_match.group(1))

            # Filter < 3°F
            if temp_val <= max_temp - temp_range and price > 0:
                contracts.append((temp_val, price))
            elif temp_val <= max_temp - (temp_range - 1) and price > 0 and count > 2 and use_count:
                contracts.append((temp_val, price))

        except:
            continue

    if not contracts:
        return None

    # Return temperature of cheapest contract
    best = min(contracts, key=lambda x: x[1])
    return best

def process_location(place, airport, year, month, day):
    time.sleep(random.uniform(.5, 2))
    driver = get_driver()
    try:
        _, _, date_str = format_date_parts(year, month, day)
        temp, count = safe_get_max_temp(driver, airport, date_str)
        best = get_best_contract(driver, place, year, month, day, temp, count)

        return place, best, count

    except Exception as e:
        print(f"FAILED: {place} ({airport}) → {e}")
        return place, None, 0

    finally:
        driver.quit()

def send_pushover(message: str, title: str = "Stock Tracker"):
    user_key = os.getenv("PUSHOVER_USER_KEY")
    api_token = os.getenv("PUSHOVER_API_TOKEN")

    if not user_key or not api_token:
        print("[Warn] Pushover credentials not set.")
        return

    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": api_token,
                "user": user_key,
                "title": title,
                "message": message,
            },
            timeout=10,
        )
        print("[Info] Pushover notification sent.")
    except Exception as e:
        print(f"[Warn] Failed to send notification: {e}")
if __name__ == "__main__":
    start_time = time.perf_counter()

    temp_range = 3
    price_range = 79
    use_count = False

    today = datetime.now()
    year = today.year
    month = today.month
    day = today.day
    #good days: 2

    contracts = []
    #print("|||||||||||||||||||||||")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(process_location, place, airport, year, month, day)
            for place, airport in locations
        ]

        for f in futures:
            place, best, count = f.result()
            #print("|", end="")
            if best is not None and best[1] < price_range:
                contracts.append(best + (place,) + (count,))
                #print(f"{place}: {best[0]} at {best[1]}c")
                #if(best[1] < best_contract[1][1]):
                #    best_contract = (place, best)
            #else:
                #print(f"{place}: N/A")
    #print(f"Best = {best_contract[0]} at {best_contract[1][0]} for {best_contract[1][1]}c")
    contracts = sorted(contracts, key=lambda x: x[1])
    #print("")
    if len(contracts) > 0:
        message = []
        for i in contracts[:3]:
            message.append(f"{i[2]}: {i[0]} at {i[1]}c {i[3]}")
        send_pushover("\n".join(message[:3]), "Temp Scanner")

    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time / 60: .0f}:{elapsed_time % 60:.0f}")