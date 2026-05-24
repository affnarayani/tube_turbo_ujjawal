import os
import json
import time
import base64
import random
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from playwright.sync_api import sync_playwright

from playwright_stealth import Stealth   # ✅ REQUIRED


# =========================
# CONFIG
# =========================
HEADLESS = True

FACEBOOK_COOKIES_FILE = "fb_cookies.json.encrypted"  
FACEBOOK_BASE_URL = "https://www.facebook.com"  
FACEBOOK_REELS_URL = "https://www.facebook.com/profile.php?id=61573728815021&sk=reels_tab"  
REELS_JSON_FILE = "reels.json"  
PBKDF2_ITERATIONS = 200_000


# =========================
# ENV
# =========================
load_dotenv()
DECRYPT_KEY = os.getenv("DECRYPT_KEY")

if not DECRYPT_KEY:
    raise RuntimeError("DECRYPT_KEY missing")


# =========================
# CRYPTO
# =========================
def _derive_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password)


def _decrypt_payload(payload: Dict[str, Any], password: str) -> bytes:
    salt = base64.b64decode(payload["s"])
    nonce = base64.b64decode(payload["n"])
    ciphertext = base64.b64decode(payload["ct"])

    key = _derive_key(password.encode("utf-8"), salt)
    aesgcm = AESGCM(key)

    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag:
        raise RuntimeError("❌ Decryption failed (InvalidTag)")


def load_cookies(file_path: Path) -> List[Dict[str, Any]]:
    print("[STEP] Loading cookies...", flush=True)

    with file_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    plaintext = _decrypt_payload(payload, DECRYPT_KEY)
    cookies = json.loads(plaintext.decode("utf-8"))

    print("[OK] Cookies loaded", flush=True)
    return cookies


# =========================
# FACEBOOK BOT (STEALTH)
# =========================
def run():
    print("[START] Bot started", flush=True)

    # Clear or initialize the JSON file with an empty list at the start
    with open(REELS_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)
    print(f"[INFO] Initialized/Cleared {REELS_JSON_FILE}", flush=True)

    cookies = load_cookies(Path(FACEBOOK_COOKIES_FILE))

    # =========================
    # STEALTH SETUP
    # =========================
    stealth = Stealth()
    pw_cm = stealth.use_sync(sync_playwright())
    pw = pw_cm.__enter__()

    try:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        context.add_cookies(cookies)
        page = context.new_page()

        # Step 1: Go to Facebook Homepage first
        print("[STEP] Opening Facebook Homepage...", flush=True)
        page.goto(FACEBOOK_BASE_URL)  
        page.wait_for_timeout(random.randint(4000, 6000))

        # Step 2: Navigate to Reels URL
        print("[STEP] Navigating to Facebook Reels...", flush=True)
        page.goto(FACEBOOK_REELS_URL)  
        
        print("[STEP] Waiting for Reels grid to render...", flush=True)
        page.wait_for_timeout(6000) 

        # =========================
        # SCRAPING & SCROLLING LOGIC
        # =========================
        scraped_reels = set()
        no_change_count = 0
        last_height = page.evaluate("document.documentElement.scrollHeight")
        
        print("[STEP] Starting scrolling and scraping...", flush=True)

        while True:
            # ✅ ARIA-BASED FIX: Target elements based on your layout insights
            reel_elements = page.get_by_role("link", name="Reel tile preview").all()
            
            for element in reel_elements:
                try:
                    href = element.get_attribute("href")
                    text = element.inner_text() or ""
                    
                    if href:
                        # Clean profile parameters out of the reel link
                        clean_url = href.split("?")[0]
                        
                        # Full safety fallback if Facebook formats URL with /reel/ instead of /reels/
                        if clean_url not in scraped_reels:
                            scraped_reels.add(clean_url)
                            
                            # Real-time sequential dataset append from bottom
                            with open(REELS_JSON_FILE, "r+", encoding="utf-8") as f:
                                data = json.load(f)
                                data.append(clean_url)
                                f.seek(0)
                                json.dump(data, f, indent=2)
                                f.truncate()
                                
                            print(f"[FOUND] {clean_url} | Views: {text.strip()}", flush=True)
                except Exception:
                    continue

            # Smooth viewport scrolling injection
            page.evaluate("window.scrollBy(0, window.innerHeight * 1.2);")
            page.wait_for_timeout(random.randint(2500, 4000))

            # Infinite scroll validation offset checks
            new_height = page.evaluate("document.documentElement.scrollHeight")
            current_scroll = page.evaluate("window.scrollY + window.innerHeight")

            if current_scroll >= new_height or new_height == last_height:
                no_change_count += 1
                if no_change_count >= 5: # Confirmed bottom execution threshold
                    print("[INFO] Reached the end of the Reels tab.", flush=True)
                    break
            else:
                last_height = new_height
                no_change_count = 0

        print(f"\n[SUCCESS] Total unique reels scraped and saved: {len(scraped_reels)}", flush=True)

        # Final random wait before closing
        random_wait = random.randint(30, 60)
        print(f"[INFO] Waiting for {random_wait} seconds before closing the browser...", flush=True)
        time.sleep(random_wait)

    except Exception as e:
        print("[ERROR]", e, flush=True)

    finally:
        try:
            browser.close()
        except:
            pass

        try:
            pw_cm.__exit__(None, None, None)
        except:
            pass

        print("[DONE] Bot finished", flush=True)


if __name__ == "__main__":
    run()