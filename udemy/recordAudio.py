import re
import subprocess
import os
import time
from pathlib import Path
import json
import uuid
import shutil
import undetected_chromedriver as uc
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from concurrent.futures import ProcessPoolExecutor

JSON_FILE = "~/udemy_course_list.json"
COOKIES_PATH = "/home/oki/www.udemy.com_13-07-2025.json"
OUTDIR = os.path.expanduser("/home/oki/test/udemy-kayitlar")
os.makedirs(OUTDIR, exist_ok=True)

def temizle_null_sinks():
    result = subprocess.run(
        "pactl list short modules | grep module-null-sink | awk '{print $1}'",
        shell=True, capture_output=True, text=True)
    ids = result.stdout.strip().split("\n")
    for module_id in ids:
        if module_id.strip():
            subprocess.call(["pactl", "unload-module", module_id.strip()])
    print("🚟️ Eski sanal kanallar temizlendi.")

def sanitize_filename(name):
    name = re.sub(r'[^\w\-_\. ]', '_', name)
    name = name.replace(' ', '_')
    name = re.sub(r'_+', '_', name)
    return name

def reset_video_position(browser):
    try:
        WebDriverWait(browser, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-purpose="video-progress-bar"]'))
        )
        slider = browser.find_element(By.CSS_SELECTOR, '[data-purpose="video-progress-bar"]')
        actions = ActionChains(browser)
        actions.move_to_element_with_offset(slider, 5, 5).click().perform()
        print("⏮️ Video başa alındı (data-purpose selector ile).")
    except Exception as e:
        print(f"⚠️ Video ilerleme çubuğu tıklaması başarısız: {e}")


def get_pstree_pids(root_pid):
    try:
        cmd = ["pstree", "-p", str(root_pid)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout

        import re
        pids = re.findall(r"\((\d+)\)", output)
        return list(set(pids))
    except Exception as e:
        print(f"⚠️ pstree PID listesi alınamadı: {e}")
        return []

def find_sink_input_id_by_pid(pids):
    result = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True)
    lines = result.stdout.splitlines()
    current_id = None

    for line in lines:
        line = line.strip()
        if line.startswith("Sink Input") or line.startswith("Alıcı Girişi"):
            current_id = line.split("#")[-1].strip()

        if "application.process.id" in line:
            proc_id = line.split('"')[1]
            if proc_id in pids:
                print(f"✅ Eşleşme bulundu! Sink Input: {current_id} ← PID: {proc_id}")
                return current_id
    return None

def click_video_play_button(browser):
    try:
        time.sleep(5)
        video = browser.find_element(By.TAG_NAME, "video")
        actions = ActionChains(browser)
        actions.move_to_element(video).pause(1).click().perform()
        print("🖱️ Mouse ile video üzerine gidildi ve tıklandı.")
    except Exception as e:
        print(f"⚠️ Video play tıklaması başarısız: {e}")

def get_uc_binary_copy(session_id):
    uc_path = os.path.expanduser("~/.local/share/undetected_chromedriver/undetected_chromedriver")
    custom_path = f"/tmp/undetected_chromedriver_{session_id}"
    shutil.copy2(uc_path, custom_path)
    os.chmod(custom_path, 0o755)
    return custom_path

def start_uc_browser(url, profile_dir, session_id):
    options = uc.ChromeOptions()
    options.binary_location = "/usr/bin/google-chrome"
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={profile_dir}")

    binary_path = get_uc_binary_copy(session_id)
    browser = uc.Chrome(options=options, driver_executable_path=binary_path)

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
    print("✅ Sayfa yüklendi:", url)

    return browser

def kayit_tek_satir(lecture_info):
    if lecture_info["duration"] == "?":
        print(f"⏭️ Quiz ya da süre bilinmiyor, atlanıyor: {lecture_info['lecture']}")
        return

    url = lecture_info["url"]
    duration = int(lecture_info["duration"]) * 60
    lecture_title = lecture_info["lecture"]
    safe_title = sanitize_filename(lecture_title)

    session_id = str(uuid.uuid4())[:8]
    sink_name = f"sink_{session_id}"
    monitor_name = f"{sink_name}.monitor"
    outfile = f"{OUTDIR}/{safe_title}.wav"
    profile_dir = f"/tmp/chrome-profile-{session_id}"
    os.makedirs(profile_dir, exist_ok=True)

    print(f"🔊 Sanal çıkış oluşturuluyor: {sink_name}")
    pactl_cmd = ["pactl", "load-module", "module-null-sink",
                 f"sink_name={sink_name}",
                 f"sink_properties=device.description=Sink{session_id}"]
    module_id = subprocess.check_output(pactl_cmd).decode().strip()

    print(f"🌐 UC Browser başlatılıyor... ({session_id})")
    browser = start_uc_browser(url, profile_dir, session_id)

    #reset_video_position(browser)
    click_video_play_button(browser)

    browser_pid = browser.browser_pid
    pid_list = get_pstree_pids(browser_pid)
    sink_input_id = find_sink_input_id_by_pid(pid_list)

    if sink_input_id:
        subprocess.call(["pactl", "move-sink-input", sink_input_id, sink_name])
        print(f"🔗 Sink-input bulundu ve atandı: {sink_input_id}")
    else:
        print(f"❌ Sink-input bulunamadı")

    print(f"🎤 Kayıt başlıyor ({duration} sn)...")

    subprocess.call([
        "ffmpeg", "-f", "pulse", "-i", monitor_name, "-t", str(duration),
        outfile, "-loglevel", "error"
    ])

    subprocess.call(["pactl", "unload-module", module_id])
    print(f"✅ Kayıt tamamlandı: {outfile}")

    if browser.service.process and browser.service.process.poll() is None:
        try:
            browser.quit()
        except Exception as e:
            print(f"⚠️ Tarayıcı zaten kapanmış olabilir: {e}")

    print(f"🛑 Tarayıcı kapatıldı: {session_id}")

def filtrele_kayitlar(entries):
    """Daha önce kaydedilmiş veya süresi olmayan dersleri filtrele"""
    filtered = []
    for entry in entries:
        if entry["duration"] == "?":
            print(f"⏭️ Süre yok, atlanıyor: {entry['lecture']}")
            continue

        title = sanitize_filename(entry["lecture"])
        outfile = Path(OUTDIR) / f"{title}.wav"
        if outfile.exists():
            print(f"⏭️ Daha önce kaydedilmiş, atlanıyor: {title}")
            continue

        filtered.append(entry)

    return filtered

def chunkify(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def load_json_entries():
    if not Path(JSON_FILE).exists():
        print(f"❌ JSON dosyası bulunamadı: {JSON_FILE}")
        return []
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def asenkron(batch_size=3):
    temizle_null_sinks()
    entries = filtrele_kayitlar(load_json_entries())

    for group in chunkify(entries, batch_size):
        with ProcessPoolExecutor(max_workers=batch_size) as executor:
            futures = [executor.submit(kayit_tek_satir, entry) for entry in group]
            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    print(f"❌ Hata oluştu: {e}")
        print(f"✅ Grup tamamlandı: {len(group)} kayıt işlendi.")

def senkron():
    temizle_null_sinks()
    entries = load_json_entries()

    for info in entries:
        kayit_tek_satir(info)

    print("🎉 Tüm kayıtlar tamamlandı.")

if __name__ == "__main__":
    asenkron()
