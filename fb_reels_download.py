import os
import json
import time
import base64
import random
import shutil
import glob
import sys
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth   # ✅ REQUIRED

import yt_dlp
import ffmpeg  # REQUIRED: pip install ffmpeg-python


# ==============================================================================
# GLOBAL CONFIGURATIONS (Merged from both scripts)
# ==============================================================================
HEADLESS = True

FACEBOOK_COOKIES_FILE = "fb_cookies.json.encrypted"  
FACEBOOK_BASE_URL = "https://www.facebook.com"  
FACEBOOK_REELS_URL = "https://www.facebook.com/profile.php?id=100091254387822&sk=reels_tab"  
REELS_JSON_FILE = "reels.json"  
PBKDF2_ITERATIONS = 200_000

MAX_REELS_LIMIT = 1500

OUTPUT_FOLDER = "videos"
TARGET_RATIO = 9 / 16  # 0.5625
MARGIN = 0.02          # 2% error tolerance margin


# ==============================================================================
# ENVIRONMENT VALIDATION
# ==============================================================================
load_dotenv()
DECRYPT_KEY = os.getenv("DECRYPT_KEY")

if not DECRYPT_KEY:
    raise RuntimeError("DECRYPT_KEY missing")

# ==============================================================================
# DUPLICATE URL CHECK (PAGES.TXT)
# ==============================================================================
PAGES_FILE = "pages.txt"

if os.path.exists(PAGES_FILE):
    print(f"[CHECK] Checking if URL exists in '{PAGES_FILE}'...", flush=True)
    with open(PAGES_FILE, "r", encoding="utf-8") as f:
        # Saare URLs ko read karke ek set mein store kar rahe hain (whitespaces aur newlines hata kar)
        existing_urls = {line.strip() for line in f if line.strip()}
    
    if FACEBOOK_REELS_URL in existing_urls:
        print(f"[EXIT] URL '{FACEBOOK_REELS_URL}' already exists in {PAGES_FILE}. Exiting...", flush=True)
        sys.exit(1)
    else:
        print("[OK] URL is new. Proceeding...", flush=True)
else:
    print(f"[INFO] '{PAGES_FILE}' not found. Assuming first run and proceeding...", flush=True)


# ==============================================================================
# CRYPTO FUNCTIONS
# ==============================================================================
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


# ==============================================================================
# DOWNLOADER & FILTERING UTILITIES
# ==============================================================================
def clear_and_create_folder(folder_path):
    """Deletes existing files and safely recreates the directory."""
    path = Path(folder_path)
    if path.exists():
        print(f"[CLEANUP] Clearing old content from '{folder_path}'...", flush=True)
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    print(f"[OK] Directory ready: '{folder_path}'", flush=True)


def get_video_aspect_ratio(video_path):
    """Uses ffprobe to calculate exact dynamic video aspect ratio and dimensions."""
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if not video_stream:
            return None, None, None
        
        width = int(video_stream['width'])
        height = int(video_stream['height'])
        
        if height == 0:
            return None, None, None
            
        return width / height, width, height
    except Exception as e:
        print(f"[ERROR] Failed probing metadata for {video_path}: {e}", flush=True)
        return None, None, None


# ==============================================================================
# PIPELINE PHASE 1: SCRAPING ENGINE
# ==============================================================================
def run():
    print("[START] Bot started (Phase 1: Scraping)", flush=True)

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
            # Check if limit reached at loop start
            if len(scraped_reels) >= MAX_REELS_LIMIT:
                print(f"[INFO] Reached the maximum limit of {MAX_REELS_LIMIT} reels. Stopping...", flush=True)
                break

            # ARIA-BASED TARGETING: Extract elements based on layout role
            reel_elements = page.get_by_role("link", name="Reel tile preview").all()
            
            for element in reel_elements:
                try:
                    # Instant stop check during item iteration
                    if len(scraped_reels) >= MAX_REELS_LIMIT:
                        break

                    href = element.get_attribute("href")
                    text = element.inner_text() or ""
                    
                    if href:
                        # Clean profile parameters out of the reel link
                        clean_url = href.split("?")[0]
                        
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

            # Break out of outer loop if inside loop triggered the limit
            if len(scraped_reels) >= MAX_REELS_LIMIT:
                print(f"[INFO] Reached the maximum limit of {MAX_REELS_LIMIT} reels. Stopping...", flush=True)
                break

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

        print("[DONE] Scraping phase completed.", flush=True)


# ==============================================================================
# PIPELINE PHASE 2: DOWNLOAD & FILTER ENGINE
# ==============================================================================
def download_reels_pipeline():
    print("\n[START] Starting Phase 2: Download & Filtering Pipeline", flush=True)
    
    # Step 1: Initialize environment directories safely
    clear_and_create_folder(OUTPUT_FOLDER)

    # Step 2: Read dataset JSON mapping array
    if not os.path.exists(REELS_JSON_FILE):
        print(f"[ERROR] Source registry file '{REELS_JSON_FILE}' does not exist!", flush=True)
        return

    with open(REELS_JSON_FILE, "r", encoding="utf-8") as f:
        relative_urls = json.load(f)

    if not relative_urls:
        print("[INFO] No urls found in JSON mapping file to process.", flush=True)
        return

    print(f"[INFO] Found {len(relative_urls)} target entries inside JSON file.", flush=True)

    # yt-dlp technical operational parameters
    ydl_opts = {
        # 'bestvideo+bestaudio/best' forces download at maximum available ecosystem resolution
        'format': 'bestvideo+bestaudio/best',
        # Temporary unique names using IDs to avoid collision issues before cleanup processes
        'outtmpl': os.path.join(OUTPUT_FOLDER, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True
    }

    # Step 3: Run standard downloads array sequences
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for index, partial_url in enumerate(relative_urls, start=1):
            # Normalizing formatting structures like "/reel/834562509294094/"
            clean_partial = partial_url.strip("/")
            full_url = f"{FACEBOOK_BASE_URL}/{clean_partial}"
            
            print(f"\n[DOWNLOAD {index}/{len(relative_urls)}] Fetching: {full_url}", flush=True)
            try:
                ydl.download([full_url])
                print("[OK] Download finished", flush=True)
            except Exception as e:
                print(f"[WARN] Skipping stream target due to processing error: {e}", flush=True)

    print("\n--- Starting Post-Download Filtering Pipeline ---", flush=True)

    # Step 4: Analyze dimensions and clear unaligned ratios
    downloaded_files = glob.glob(os.path.join(OUTPUT_FOLDER, "*.mp4"))
    valid_videos = []

    MAX_FILE_SIZE_BYTES = 99 * 1024 * 1024

    for video_file in downloaded_files:
        try:
            # 1. Check File Size First (Fast check before probing video)
            file_size = os.path.getsize(video_file)
            if file_size > MAX_FILE_SIZE_BYTES:
                size_in_mb = file_size / (1024 * 1024)
                print(f"[REMOVE] Deleting heavy file (>99MB) -> {os.path.basename(video_file)} ({size_in_mb:.2f} MB)", flush=True)
                os.remove(video_file)
                continue

            # 2. Check Aspect Ratio
            ratio, width, height = get_video_aspect_ratio(video_file)
            if ratio is None:
                print(f"[REMOVE] Deleting corrupted file structure: {video_file}", flush=True)
                os.remove(video_file)
                continue

            # 3. Check Width and Height (Low Resolution Filter)
            if width < 720 or height < 1280:
                print(f"[REMOVE] Deleting low-res content -> {os.path.basename(video_file)} ({width}x{height})", flush=True)
                os.remove(video_file)
                continue

            # Check aspect ratio with a 2% tolerance margin
            lower_bound = TARGET_RATIO * (1 - MARGIN)
            upper_bound = TARGET_RATIO * (1 + MARGIN)

            if lower_bound <= ratio <= upper_bound:
                valid_videos.append(video_file)
                print(f"[KEEP] Valid 9:16 Video -> {os.path.basename(video_file)} (Ratio: {ratio:.4f})", flush=True)
            else:
                print(f"[REMOVE] Deleting non-9:16 content -> {os.path.basename(video_file)} (Ratio: {ratio:.4f})", flush=True)
                os.remove(video_file)

        except Exception as e:
            print(f"[ERROR] Error processing file {video_file}: {e}", flush=True)
            if os.path.exists(video_file):
                os.remove(video_file)

    final_count = len(glob.glob(os.path.join(OUTPUT_FOLDER, "*.mp4")))
    print(f"\n[SUCCESS] Pipeline Complete! {final_count} high-res 9:16 reels successfully verified and saved inside '{OUTPUT_FOLDER}/'.", flush=True)


# ==============================================================================
# EXECUTION CONTROLLER
# ==============================================================================
if __name__ == "__main__":
    # Execution Flow: Run sequential automation chain
    run()                       # Trigger Scraping Engine
    download_reels_pipeline()   # Trigger Downloader Engine