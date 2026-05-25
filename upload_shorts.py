import os
import sys
import json
import requests
from dotenv import load_dotenv

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BUFFER_KEY = os.getenv("BUFFER_KEY")

if not BUFFER_KEY:
    raise ValueError("❌ BUFFER_KEY missing in .env")

GRAPHQL_ENDPOINT = "https://api.buffer.com"

HEADERS = {
    "Authorization": f"Bearer {BUFFER_KEY}",
    "Content-Type": "application/json"
}

VIDEOS_FOLDER = "videos"
YOUTUBE_CATEGORY_ID = "24"

UPLOAD_ENDPOINT = "https://tmpfile.link/api/upload"

# =========================================================
# TMPFILE.LINK UPLOAD (CORRECT IMPLEMENTATION)
# =========================================================

def upload_to_tmpfile(file_path):

    if not os.path.exists(file_path):
        print("❌ File not found:", file_path)
        return None

    print(f"🚀 Uploading to tmpfile.link: {file_path}")

    try:
        with open(file_path, "rb") as f:

            response = requests.post(
                UPLOAD_ENDPOINT,
                files={"file": f}
            )

        if response.status_code != 200:
            print("❌ Upload failed:", response.text)
            return None

        data = response.json()

        download_link = data.get("downloadLink")

        if not download_link:
            print("❌ No downloadLink in response")
            print(data)
            return None

        print("🔗 tmpfile direct link:", download_link)

        return download_link

    except Exception as e:
        print("❌ tmpfile error:", e)
        return None


# =========================================================
# GET ORGANIZATION
# =========================================================

def get_org_id():

    query = """
    query {
      account {
        organizations {
          id
          name
        }
      }
    }
    """

    res = requests.post(
        GRAPHQL_ENDPOINT,
        headers=HEADERS,
        json={"query": query}
    )

    data = res.json()

    orgs = data.get("data", {}).get("account", {}).get("organizations", [])

    if not orgs:
        print("❌ No organization found")
        return None

    print("✅ Organization:", orgs[0]["name"])
    return orgs[0]["id"]


# =========================================================
# GET YOUTUBE CHANNEL
# =========================================================

def get_youtube_channel(org_id):

    query = """
    query ($orgId: OrganizationId!) {
      channels(input: { organizationId: $orgId }) {
        id
        name
        service
      }
    }
    """

    res = requests.post(
        GRAPHQL_ENDPOINT,
        headers=HEADERS,
        json={"query": query, "variables": {"orgId": org_id}}
    )

    channels = res.json().get("data", {}).get("channels", [])

    TARGET_CHANNEL_NAME = "Chull Factory"

    for c in channels:
        if c.get("service") == "youtube" and c.get("name") == TARGET_CHANNEL_NAME:
            print("✅ Targeted YouTube Channel Found:", c["name"])
            return c["id"]

    print("❌ No YouTube channel found")
    return None


# =========================================================
# BUFFER POST (FIXED FINAL WORKING VERSION)
# =========================================================

def upload_to_buffer(channel_id, video_url, title, description):

    print("📤 Sending to Buffer...")

    mutation = """
    mutation CreatePost(
      $channelId: ChannelId!,
      $text: String!,
      $videoUrl: String!,
      $title: String!,
      $categoryId: String!
    ) {
      createPost(input: {
        channelId: $channelId,
        text: $text,
        schedulingType: automatic,
        mode: addToQueue,
        assets: [{
          video: { url: $videoUrl }
        }],
        metadata: {
          youtube: {
            title: $title,
            categoryId: $categoryId
          }
        }
      }) {
        ... on PostActionSuccess {
          post { id }
        }
        ... on MutationError {
          message
        }
      }
    }
    """

    variables = {
        "channelId": channel_id,
        "text": f"{title}\n\n{description} #Shorts",
        "videoUrl": video_url,
        "title": title,
        "categoryId": YOUTUBE_CATEGORY_ID
    }

    res = requests.post(
        GRAPHQL_ENDPOINT,
        headers=HEADERS,
        json={"query": mutation, "variables": variables}
    )

    data = res.json()

    if "errors" in data:
        print("❌ GraphQL Error:", data["errors"])
        return

    result = data.get("data", {}).get("createPost", {})

    if "message" in result:
        print("❌ Buffer Error:", result["message"])
        return

    post_id = result.get("post", {}).get("id")

    print("\n💥 SUCCESS!")
    print("✅ Uploaded to Buffer Queue")
    print("🆔 Post ID:", post_id)


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    json_path = "video.json"
    
    # 🚨 [HARDCORE SYSTEM 1 CHECK] Agar file hi missing hai toh turant fatal exit
    if not os.path.exists(json_path):
        print(f"❌ [FATAL] '{json_path}' missing! Previous step failed or did not generate output.", file=sys.stderr)
        sys.exit(1)

    # 🚨 [HARDCORE PARSING CHECK] Agar json file khali hai ya corrupt hai toh fatal exit
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            video_data = json.load(f)
    except Exception as e:
        print(f"❌ [FATAL] JSON corruption/parsing failed: {e}", file=sys.stderr)
        sys.exit(1)

    video_file_name = video_data.get("filename")
    video_title = video_data.get("title")
    video_description = video_data.get("description")

    # Double safeguard: Agar data load ho gaya par keys hi khali hain
    if not video_file_name or not video_title:
        print("❌ [FATAL] Critical data fields missing inside video.json", file=sys.stderr)
        sys.exit(1)

    # Videos folder se path mapping
    file_path = os.path.join(VIDEOS_FOLDER, video_file_name)

    # 1. Org
    org_id = get_org_id()
    if not org_id:
        print("❌ [FATAL] Failed to retrieve Organization ID", file=sys.stderr)
        sys.exit(1)

    # 2. Channel
    channel_id = get_youtube_channel(org_id)
    if not channel_id:
        print("❌ [FATAL] Failed to retrieve YouTube Channel ID", file=sys.stderr)
        sys.exit(1)

    # 3. Upload to tmpfile.link
    video_url = upload_to_tmpfile(file_path)
    if not video_url:
        print("❌ [FATAL] File upload to tmpfile.link failed", file=sys.stderr)
        sys.exit(1)

    # 4. Buffer upload
    upload_to_buffer(channel_id, video_url, video_title, video_description)

    # 5. SUCCESS AND AUTO-DELETE LOGIC
    print(f"\n[CLEANUP] Post successful! Attempting to delete uploaded video file: {video_file_name}")
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"🗑️ [DELETED] '{video_file_name}' successfully removed from '{VIDEOS_FOLDER}' folder.", flush=True)
        except Exception as delete_err:
            print(f"⚠️ [WARNING] Video upload toh ho gaya par file delete nahi ho payi: {delete_err}", flush=True)
    else:
        print(f"⚠️ [WARNING] Target file '{video_file_name}' delete karne ke liye nahi mili.")