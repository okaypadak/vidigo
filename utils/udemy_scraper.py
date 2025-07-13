import json
import time
import os
import uuid
from collections import defaultdict
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

COOKIES_PATH = "/home/oki/udemy_cookie.json"

def parse_duration(duration_str):
    try:
        if "saat" in duration_str:
            parts = duration_str.replace("dak", "").replace("saat", "").split()
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            return str(hours * 60 + minutes)
        elif "dak" in duration_str:
            return str(int(duration_str.replace("dak", "").strip()))
        else:
            return "?"
    except:
        return "?"

def expand_all_sections(browser):
    print("📂 Tüm bölümler açılıyor...")

    WebDriverWait(browser, 15).until(
        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'section--section')]"))
    )

    toggle_buttons = browser.find_elements(By.XPATH, "//div[contains(@class, 'section--section')]//button[contains(@class, 'panel-toggler')]")
    print(f"🔎 {len(toggle_buttons)} gerçek bölüm bulundu.")

    for i, btn in enumerate(toggle_buttons):
        try:
            expanded = btn.get_attribute("aria-expanded")
            if expanded == "false":
                browser.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                btn.click()
                print(f"✅ Bölüm {i+1} açıldı.")
                time.sleep(0.7)
            else:
                print(f"➡️ Bölüm {i+1} zaten açık.")
        except Exception as e:
            print(f"⚠️ Bölüm {i+1} açılamadı: {e}")

def start_uc_browser(url, profile_dir):
    options = uc.ChromeOptions()
    options.binary_location = "/usr/bin/google-chrome"
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={profile_dir}")

    browser = uc.Chrome(options=options)
    browser.get("https://www.udemy.com/")
    time.sleep(3)

    if os.path.exists(COOKIES_PATH):
        with open(COOKIES_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        for cookie in cookies:
            cookie.pop('sameSite', None)
            cookie.pop('same_site', None)
            cookie.pop('hostOnly', None)
            if 'expiry' in cookie and isinstance(cookie['expiry'], float):
                cookie['expiry'] = int(cookie['expiry'])
            try:
                browser.add_cookie(cookie)
            except Exception as e:
                print(f"⚠️ Cookie eklenemedi: {cookie.get('name')} → {e}")

    browser.get(url)
    time.sleep(5)
    print("✅ Sayfa yüklendi:", url)
    return browser

def scroll_to_bottom(browser):
    SCROLL_PAUSE = 1
    last_height = browser.execute_script("return document.body.scrollHeight")
    while True:
        browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE)
        new_height = browser.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    print("✅ Sayfa sonuna kadar scroll edildi.")

def scrape_udemy_course(course_url):
    session_id = str(uuid.uuid4())[:8]
    profile_dir = f"/tmp/chrome-profile-{session_id}"
    browser = start_uc_browser(course_url, profile_dir)
    expand_all_sections(browser)

    time.sleep(3)
    section_blocks = browser.find_elements(By.XPATH, "//div[contains(@class, 'section--section')]")
    section_map = defaultdict(list)

    for section_index, section in enumerate(section_blocks):
        try:
            header_elem = section.find_element(By.XPATH, ".//h3")
            section_title = header_elem.text.strip()
            if not section_title:
                raise ValueError("Boş başlık")
        except:
            section_title = f"Bölüm {section_index + 1}"

        print(f"\n📂 {section_title}")
        lectures = section.find_elements(By.XPATH, ".//li[contains(@class, 'curriculum-item-link')]")

        for i in range(len(lectures)):
            try:
                lectures = section.find_elements(By.XPATH, ".//li[contains(@class, 'curriculum-item-link')]")
                lec = lectures[i]

                browser.execute_script("arguments[0].scrollIntoView(true);", lec)
                time.sleep(0.5)
                lec.click()
                time.sleep(2)

                try:
                    current_title_elem = browser.find_element(By.XPATH, "//li[contains(@class, 'is-current')]//span//span//span")
                    lecture_title = current_title_elem.text.strip()
                except:
                    lecture_title = f"Ders {i+1}"

                try:
                    duration_elem = lec.find_element(By.XPATH, ".//div[contains(@class, 'curriculum-item-link--metadata')]//span")
                    raw_duration = duration_elem.text.strip()
                    duration = parse_duration(raw_duration)
                except:
                    duration = "?"

                lecture_url = browser.current_url

                print(f"  🎬 {lecture_title} - {duration} - {lecture_url}")

                section_map[section_title].append({
                    "lecture": lecture_title,
                    "duration": duration,
                    "url": lecture_url
                })

                browser.back()
                time.sleep(2)

            except Exception as e:
                print(f"⚠️ Lecture işlemi hatası: {e}")
                continue

    structured = []
    for section_title, lectures in section_map.items():
        structured.append({
            "section": section_title,
            "lectures": lectures
        })

    output_path = os.path.expanduser("~/udemy_course_list.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)

    print(f"\n✅ JSON dosyası oluşturuldu: {output_path}")
