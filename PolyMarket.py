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

#https://forecasttrader.interactivebrokers.com/eventtrader/#/market-details?id=851808912%7C20260426%7C66%7CApril%2025,%202026&detail=contract_details

locations = [
    ("nyc", "KLGA"),
    ("denver", "KBKF"),
    ("miami", "KMIA"),
    ("dallas", "KDAL"),
    ("atlanta", "KATL"),
    ("houston", "KHOU"),
    ("austin", "KAUS"),
    ("san-francisco", "KSFO"),
    ("seattle", "KSEA"),
    ("chicago", "KORD"),
    ("los-angeles", "KLAX"),
]

def format_date_parts(year, month, day):
    m_full = calendar.month_name[month].lower()   # april
    m_abbr = calendar.month_abbr[month].lower()   # apr
    d_str = f"{year}-{month:02d}-{day:02d}"       # 2026-04-21
    return m_full, m_abbr, d_str

def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
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
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

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
    temps = []

    for cell in cells:
        try:
            # Find the span inside each cell
            span = cell.find_element(By.CSS_SELECTOR, "span.wu-value")
            text = span.text.strip()

            if text.isdigit():
                temps.append(int(text))
        except:
            continue

    if not temps:
        raise Exception("No temperatures found")

    return max(temps)

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

def get_best_contract(driver, place, year, month, day, max_temp):
    month_full, month_abbr, _ = format_date_parts(year, month, day)
    url = f"https://polymarket.com/event/highest-temperature-in-{place}-on-{month_full}-{day}-{year}"

    driver.get(url)

    wait = WebDriverWait(driver, 15)

    # Wait for the Contracts container
    contract_blocks = wait.until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "div.group.flex.flex-col")
        )
    )

    contracts = []

    for block in contract_blocks:
        try:
            # 1. Get temperature text
            temp_el = block.find_element(By.TAG_NAME, "p")
            temp_text = temp_el.text.strip()

            flag = 0

            text_lower = temp_text.lower()

            if "or below" in text_lower:
                flag = 1
            elif "or higher" in text_lower:
                flag = 2

            # Example: "49°F or below"
            numbers = re.findall(r"(\d+)", temp_text)
            if not numbers:
                continue

            temps = list(map(int, numbers))

            if len(temps) == 1:
                temp_val = temps[0]
            else:
                temp_val = temps[1]

            # 2. Get price button (Buy Yes)
            buttons = block.find_elements(By.TAG_NAME, "button")

            price = None
            for btn in buttons:
                text = btn.text.strip()

                if "Buy Yes" in text:
                    # Example: "Buy Yes 1.34¢"
                    price_match = re.search(r"(\d+(\.\d+)?)", text)
                    if price_match:
                        price = float(price_match.group(1))
                        break

            if price is None:
                continue

            if flag == 1 and price > 0 and temp_val > max_temp:
                contracts.append((temp_val, price))
            elif flag == 2 and price > 0 and temp_val < max_temp:
                contracts.append((temp_val, price))
            elif temp_val == max_temp and price > 0:
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

        temp = safe_get_max_temp(driver, airport, date_str)
        best = get_best_contract(driver, place, year, month, day, temp)

        return (place, best)

    except Exception as e:
        print(f"FAILED: {place} ({airport}) → {e}")
        return place, None

    finally:
        driver.quit()

if __name__ == "__main__":
    start_time = time.perf_counter()

    temp_range = 3

    year = 2026
    month = 4
    day = 27
    #dad started 4/24/26
    #off days: 1

    contracts = []
    print("|||||||||||")
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(process_location, place, airport, year, month, day)
            for place, airport in locations
        ]

        for f in futures:
            place, best = f.result()
            print("|", end="")
            if best is not None:
                contracts.append(best + (place,))
                #print(f"{place}: {best[0]} at {best[1]}c")
                #if(best[1] < best_contract[1][1]):
                #    best_contract = (place, best)
            #else:
                #print(f"{place}: N/A")
    #print(f"Best = {best_contract[0]} at {best_contract[1][0]} for {best_contract[1][1]}c")
    contracts = sorted(contracts, key=lambda x: x[1], reverse=True)
    print("")
    for i in contracts:
        print(f"{i[2]}: {i[0]} at {i[1]}c")
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time / 60: .0f}:{elapsed_time % 60:.0f}")