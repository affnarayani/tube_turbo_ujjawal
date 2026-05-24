import os
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
VIDEO_FILE_NAME = "my_short_video.mp4"

VIDEO_TITLE = "Mera Automated Short"
VIDEO_DESCRIPTION = "Buffer GraphQL + tmpfile.link uploader system"
YOUTUBE_CATEGORY_ID = "22"

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

    for c in channels:
        if c.get("service") == "youtube":
            print("✅ YouTube Channel:", c["name"])
            return c["id"]

    print("❌ No YouTube channel found")
    return None


# =========================================================
# BUFFER POST (FIXED FINAL WORKING VERSION)
# =========================================================

def upload_to_buffer(channel_id, video_url):

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
        "text": f"{VIDEO_TITLE}\n\n{VIDEO_DESCRIPTION} #Shorts",
        "videoUrl": video_url,
        "title": VIDEO_TITLE,
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

    file_path = os.path.join(VIDES_FOLDER if False else VIDEOS_FOLDER, VIDEO_FILE_NAME)

    # 1. Org
    org_id = get_org_id()
    if not org_id:
        exit()

    # 2. Channel
    channel_id = get_youtube_channel(org_id)
    if not channel_id:
        exit()

    # 3. Upload to tmpfile.link
    video_url = upload_to_tmpfile(file_path)
    if not video_url:
        exit()

    # 4. Buffer upload
    upload_to_buffer(channel_id, video_url)