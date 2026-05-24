import os
import json
import shutil
import glob
from pathlib import Path
import yt_dlp
import ffmpeg  # REQUIRED: pip install ffmpeg-python

# =========================
# CONFIG
# =========================
REELS_JSON_FILE = "reels.json"
OUTPUT_FOLDER = "videos"
FACEBOOK_BASE_URL = "https://www.facebook.com"

# Target 9:16 aspect ratio configuration
TARGET_RATIO = 9 / 16  # 0.5625
MARGIN = 0.02          # 2% error tolerance margin


def clear_and_create_folder(folder_path):
    """Deletes existing files and safely recreates the directory."""
    path = Path(folder_path)
    if path.exists():
        print(f"[CLEANUP] Clearing old content from '{folder_path}'...", flush=True)
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    print(f"[OK] Directory ready: '{folder_path}'", flush=True)


def get_video_aspect_ratio(video_path):
    """Uses ffprobe to calculate exact dynamic video aspect ratio."""
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if not video_stream:
            return None
        
        width = int(video_stream['width'])
        height = int(video_stream['height'])
        
        if height == 0:
            return None
            
        return width / height
    except Exception as e:
        print(f"[ERROR] Failed probing metadata for {video_path}: {e}", flush=True)
        return None


def download_reels_pipeline():
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

    for video_file in downloaded_files:
        ratio = get_video_aspect_ratio(video_file)
        
        if ratio is None:
            print(f"[REMOVE] Deleting corrupted file structure: {video_file}", flush=True)
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

    final_count = len(glob.glob(os.path.join(OUTPUT_FOLDER, "*.mp4")))
    print(f"\n[SUCCESS] Pipeline Complete! {final_count} high-res 9:16 reels successfully verified and saved inside '{OUTPUT_FOLDER}/'.", flush=True)


if __name__ == "__main__":
    download_reels_pipeline()