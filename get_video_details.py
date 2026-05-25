import os
import json
import time
import base64
import random
import shutil
import sys
import requests
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


# =========================
# CONFIG
# =========================
HEADLESS = True

GROK_COOKIES_FILE = "grok_cookies.json.encrypted"
VIDEOS_DIR = Path("videos")
OUTPUT_JSON_FILE = Path("video.json")

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

PBKDF2_ITERATIONS = 200_000

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# =========================
# ENV
# =========================
load_dotenv()

DECRYPT_KEY = os.getenv("DECRYPT_KEY")

if not DECRYPT_KEY:
    raise RuntimeError("DECRYPT_KEY missing")


# =========================
# CUSTOM RANDOM WAIT
# =========================
def custom_random_wait(min_sec: float, max_sec: float):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


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

    for c in cookies:
        if "sameSite" in c:
            val = str(c["sameSite"]).lower()

            if val in ["no_restriction", "none", "unspecified", "null"]:
                c["sameSite"] = "None"
            elif val == "lax":
                c["sameSite"] = "Lax"
            elif val == "strict":
                c["sameSite"] = "Strict"
            else:
                c["sameSite"] = "Lax"

        if "partitionKey" in c:
            p_key = c["partitionKey"]
            if isinstance(p_key, dict):
                if "topLevelSite" in p_key and isinstance(p_key["topLevelSite"], str):
                    c["partitionKey"] = p_key["topLevelSite"]
                else:
                    del c["partitionKey"]
            elif not isinstance(p_key, str):
                del c["partitionKey"]

    print("[OK] Cookies loaded and sanitized", flush=True)
    return cookies


# =========================
# MAIN
# =========================
def run():
    print("[START] Script started", flush=True)

    cookies = load_cookies(Path(GROK_COOKIES_FILE))
    print(f"[OK] Total cookies loaded: {len(cookies)}", flush=True)

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
            user_agent=USER_AGENT
        )

        print("[STEP] Adding cookies to browser context...", flush=True)
        context.add_cookies(cookies)

        page = context.new_page()
        print("[OK] Cookies added successfully", flush=True)

        print("[STEP] Opening Grok...", flush=True)
        page.goto("https://grok.com/", wait_until="domcontentloaded")
        print("[OK] Grok opened with cookies (Logged In)", flush=True)

        # 1. Login ke baad random wait between 30, 60 seconds
        print("[STEP] Waiting after login (30-60s)...", flush=True)
        custom_random_wait(30, 60)

        # 2. Videos/ folder mein se random .mp4 select karna
        if not VIDEOS_DIR.exists():
            raise RuntimeError(f"❌ '{VIDEOS_DIR}' folder nahi mila!")
        
        mp4_files = list(VIDEOS_DIR.glob("*.mp4"))
        if not mp4_files:
            raise RuntimeError(f"❌ '{VIDEOS_DIR}' folder mein koi .mp4 file nahi mili!")
        
        selected_video = random.choice(mp4_files)
        video_filename = selected_video.name
        print(f"[OK] Selected item: {video_filename}", flush=True)

        # 3. Attach button par click karna
        print("[STEP] Clicking attach button...", flush=True)
        page.get_by_test_id("attach-button").click()
        print("[OK] Attach button clicked", flush=True)
        custom_random_wait(15, 30)

        # 4 & 5. Bina file window open kiye directly file inject karna
        print("[STEP] Initiating direct background file upload...", flush=True)
        try:
            with page.expect_file_chooser() as fc_info:
                page.get_by_role("menuitem", name="Upload a file").click()
            
            file_chooser = fc_info.value
            file_chooser.set_files(str(selected_video.resolve()))
            print("[OK] File successfully injected directly via file chooser", flush=True)
        except Exception as upload_err:
            print(f"[WARNING] expect_file_chooser failed: {upload_err}. Trying fallback hidden selector...", flush=True)
            page.locator("input[type='file']").set_input_files(str(selected_video.resolve()))
            print("[OK] File uploaded via fallback input method", flush=True)

        custom_random_wait(15, 30)

        # 6. Text input field mein strict prompt fill karna
        print("[STEP] Inputting upgraded strict prompt into chat box...", flush=True)
        chat_input = page.get_by_test_id("chat-input").get_by_role("paragraph")
        
        prompt_text = (
            "Analyze this video and provide a highly engaging, catchy, and curiosity-driven 'title' and 'description' optimized for YouTube. "
            "STRICTLY follow these formatting and content rules:\n"
            "1. Output MUST be rendered inside a valid markdown code block (code editor format) starting with ```json.\n"
            "2. The structure must ONLY and STRICTLY contain two JSON keys: 'title' and 'description'.\n"
            "3. Do NOT create any separate key or array for hashtags or keywords.\n"
            "4. Put 6 to 12 relevant hashtags inside the 'description' value itself. The hashtags must appear directly at the very end of the description prose without any labels, introduction, introductory text, or intermediate phrases like 'Hashtags:' or 'Keywords:'.\n"
            "5. STRICTLY DO NOT INCLUDE ANY EMOJIS anywhere in the title, description, or hashtags. Keep the text entirely plain-text.\n"
            "6. No pre-text, no conversational intro, no post-text outside the code block. Just pure JSON output enclosed in a code block.\n"
            "7. PSYCHOLOGICAL HOOK RULE: Do NOT summarize or spoil the ending/secret of the video. Instead, create a 'curiosity gap'. The title must be clickbait/intriguing, and the description must build intense suspense, forcing the viewer to watch the video to find the answer.\n"
            "8. CHARACTER LIMITS: The 'title' value MUST be efficient and strictly under 60 to 70 characters (optimized to prevent truncation on mobile screens). The 'description' prose (excluding the hashtags) MUST be concise, powerful, and strictly limited to 150 to 250 characters to maintain a high-impact, fast-reading hook."
        )
        
        chat_input.fill(prompt_text)
        print("[OK] Upgraded prompt text filled", flush=True)
        custom_random_wait(15, 30)

        # 7. Chat submit button click karna (With 5 Retries and Smart Fallbacks)
        print("[STEP] Attempting to click chat submit button...", flush=True)
        submit_clicked = False
        for attempt in range(1, 6):
            try:
                # 1st Option: Jo aapka test-id chal raha tha
                submit_btn = page.get_by_test_id("chat-submit")
                
                # 2nd Option (Aapka bataya hua Aria structure): Button jiska naam 'Submit' hai
                submit_btn_fallback = page.get_by_role("button", name="Submit", exact=True)
                
                if submit_btn.is_visible():
                    submit_btn.click()
                    print(f"[OK] Chat submit button (test-id) clicked on attempt {attempt}", flush=True)
                    submit_clicked = True
                    break
                elif submit_btn_fallback.is_visible():
                    submit_btn_fallback.click()
                    print(f"[OK] Chat submit button (ARIA Role 'Submit') clicked on attempt {attempt}", flush=True)
                    submit_clicked = True
                    break
                else:
                    # 3rd Option: Agar upar dono nahi mile toh raw HTML selector check karega
                    submit_selector = page.locator("button:has-text('Submit'), button[type='submit']")
                    if submit_selector.first.is_visible():
                        submit_selector.first.click()
                        print(f"[OK] Chat submit button (Selector Fallback) clicked on attempt {attempt}", flush=True)
                        submit_clicked = True
                        break
                    else:
                        print(f"[WARNING] Chat submit button not visible anywhere yet (Attempt {attempt}/5)", flush=True)
            except Exception as e:
                print(f"[WARNING] Error finding submit button (Attempt {attempt}/5): {e}", flush=True)
            
            print(f"[RETRY] Waiting before next try...", flush=True)
            custom_random_wait(30, 60)
        
        if not submit_clicked:
            raise RuntimeError("❌ 5 Retries ke baad bhi chat submit button nahi mila.")

        # Wait random 30, 60 after successful send
        print("[STEP] Waiting after successful submission (30-60s)...", flush=True)
        custom_random_wait(30, 60)

        # 8. Output content fetch karna (Code Editor container targeted)
        print("[STEP] Waiting and searching for code block JSON output...", flush=True)
        output_found = False
        generated_text = ""
        
        for attempt in range(1, 6):
            try:
                possible_elements = page.locator("pre, code").all()
                
                for elem in possible_elements:
                    if elem.is_visible():
                        text_content = elem.inner_text()
                        if '"title"' in text_content and '"description"' in text_content and "{" in text_content:
                            generated_text = text_content
                            print(f"[OK] Valid Code Editor JSON block found on attempt {attempt}!", flush=True)
                            output_found = True
                            break
                
                if output_found:
                    break
                else:
                    fallback_elements = page.locator("div[class*='message-message'], div[class*='prose']").all()
                    for elem in fallback_elements:
                        if elem.is_visible():
                            text_content = elem.inner_text()
                            if '"title"' in text_content and '"description"' in text_content and "{" in text_content:
                                generated_text = text_content
                                print(f"[OK] Valid JSON structure found via fallback prose element on attempt {attempt}!", flush=True)
                                output_found = True
                                break
                    if output_found:
                        break
                    
                    print(f"[WARNING] Target JSON block not found/visible yet (Attempt {attempt}/5)", flush=True)
            except Exception as e:
                print(f"[WARNING] Error searching output (Attempt {attempt}/5): {e}", flush=True)
            
            print(f"[RETRY] Waiting before next output check...", flush=True)
            custom_random_wait(30, 60)

        if not output_found:
            raise RuntimeError("❌ 5 Retries ke baad bhi Grok ka generated JSON output nahi mila.")

        # 9. JSON Clean karna aur save karna (Clears previous data automatically)
        print("[STEP] Restructuring and overwriting JSON file...", flush=True)
        try:
            start_idx = generated_text.find("{")
            end_idx = generated_text.rfind("}") + 1
            json_string = generated_text[start_idx:end_idx]
            
            grok_data = json.loads(json_string)
            
            # Alag filename key ke saath structured dict
            final_data = {"filename": video_filename}
            final_data.update(grok_data)
            
            # Agar file pehle se hai, toh use clear karke fresh naya data write karne ke liye "w" mode use kiya hai
            if OUTPUT_JSON_FILE.exists():
                print(f"[INFO] Old '{OUTPUT_JSON_FILE.name}' file found. Clearing previous content...", flush=True)

            with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)
            
            print(f"[OK] Fresh data successfully saved to '{OUTPUT_JSON_FILE}'.", flush=True)

        except Exception as json_err:
            print(f"[CRITICAL ERROR] JSON parse/save karne mein issue aaya: {json_err}", flush=True)
            raise json_err

        # 10. Close browser after waiting 15, 30 seconds
        print("[STEP] Final wait before closing browser (15-30s)...", flush=True)
        custom_random_wait(15, 30)

    except Exception as e:
        print(f"[CRITICAL RUN ERROR] Script execution failed: {e}", flush=True)
        print("[FALLBACK] Script fail ho gayi hai. Backup generic YouTube JSON write kar raha hoon...", flush=True)
        try:
            fallback_data = {
                "filename": video_filename if 'video_filename' in locals() else "video.mp4",
                "title": "Wait For The End! Infact nobody expected this...",
                "description": "This is hands down the most unbelievable thing on the internet today. Watch closely because you will miss the craziest part if you blink! #viral #trending #unbelievable #mustwatch #insane #epic #wow #exploring #youtubeshorts"
            }
            with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(fallback_data, f, indent=2, ensure_ascii=False)
            print(f"[OK] Fallback data '{OUTPUT_JSON_FILE.name}' mein successfully save ho gaya. Pipeline safe hai.", flush=True)
        except Exception as write_err:
            print(f"[CRITICAL ERROR] Fallback write bhi nahi ho paya: {write_err}", flush=True)

    finally:
        try:
            browser.close()
        except:
            pass

        try:
            if TEMP_DIR.exists():
                shutil.rmtree(TEMP_DIR)
            TEMP_DIR.mkdir(exist_ok=True)
            print("[CLEANUP] Temp cleared", flush=True)
        except Exception as e:
            print("[CLEANUP ERROR]", e, flush=True)

        try:
            pw_cm.__exit__(None, None, None)
        except:
            pass

        print("[DONE] Script finished", flush=True)


if __name__ == "__main__":
    try:
        run()
    except SystemExit as se:
        sys.exit(se.code)
    except Exception as final_err:
        print(f"❌ [FATAL WORKFLOW ERROR]: {final_err}", file=sys.stderr)
        sys.exit(1)