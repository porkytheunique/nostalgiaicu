import os
import sys
import json
import random
import requests
import logging
from datetime import datetime
from atproto import Client, models
import anthropic

# --- CONFIGURATION ---
RAWG_API_KEY = os.environ.get("RAWG_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BSKY_HANDLE = os.environ.get("BLUESKY_HANDLE")
BSKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD")

# --- LOGGING SETUP ---
# This sets up the logging to print to the GitHub Action console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

# --- CONSTANTS ---
# Feature list for Mondays
MONDAY_FEATURES = [
    {"name": "Retro Radio", "url": "https://nostalgia.icu/radio", "img": "images/ad_radio.jpg"},
    {"name": "Nostalgia Quest", "url": "https://nostalgia.icu/login", "img": "images/ad_quest.jpg"},
    {"name": "Game Database", "url": "https://nostalgia.icu", "img": "images/ad_general.jpg"},
    {"name": "Pixel Challenge", "url": "https://nostalgia.icu/challenge", "img": "images/ad_general.jpg"} 
]

# --- HELPER FUNCTIONS ---

def load_json(filename, default):
    """Loads a JSON file or returns default if it doesn't exist."""
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    """Saves data to a JSON file."""
    with open(filename, 'w') as f:
        json.dump(data, f)

def get_claude_text(prompt):
    """Asks Claude to generate text."""
    if not ANTHROPIC_API_KEY:
        logger.error("❌ Anthropic API Key is missing!")
        return None

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"❌ Claude API Error: {e}")
        return None

def download_image_bytes(url):
    """Downloads an image and returns the raw bytes."""
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
        else:
            logger.warning(f"⚠️ Failed to download image: {url} (Status: {resp.status_code})")
            return None
    except Exception as e:
        logger.error(f"❌ Error downloading image: {e}")
        return None

# --- MONDAY LOGIC ---
def run_monday_ad(bsky):
    logger.info("📅 It is Monday. Initiating Ad Protocol.")
    
    # Load history to rotate ads
    history = load_json('history_ads.json', {'last_index': -1})
    idx = (history['last_index'] + 1) % len(MONDAY_FEATURES)
    feature = MONDAY_FEATURES[idx]
    
    logger.info(f"🔹 Selected Feature: {feature['name']}")

    # 1. Generate Text
    prompt = (
        f"Write a short, high-energy social media post for Bluesky promoting the '{feature['name']}' feature on Nostalgia.icu. "
        "Do not use hashtags. Keep it under 200 characters. "
        "Tone: Enthusiastic, retro-tech."
    )
    caption = get_claude_text(prompt)
    if not caption:
        caption = f"Check out the {feature['name']} on Nostalgia.icu! 🕹️"

    final_text = f"{caption}\n\nTry it here: {feature['url']}\n\n#RetroGaming #NostalgiaICU"

    # 2. Get Image
    # Check if specific image exists, otherwise fallback to general
    image_path = feature['img']
    if not os.path.exists(image_path):
        logger.warning(f"⚠️ Image {image_path} not found. Using fallback 'images/ad_general.jpg'")
        image_path = "images/ad_general.jpg"
    
    # 3. Post
    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            img_data = f.read()
            
        # Upload blob
        upload = bsky.upload_blob(img_data)
        images_embed = models.AppBskyEmbedImages.Main(
            images=[models.AppBskyEmbedImages.Image(alt=f"Promo for {feature['name']}", image=upload.blob)]
        )
        
        bsky.send_post(text=final_text, embed=images_embed)
        logger.info("✅ Monday Ad Posted Successfully.")
    else:
        logger.error("❌ CRITICAL: No ad images found in repository. Post aborted.")

    # Save state
    save_json('history_ads.json', {'last_index': idx})


# --- REGULAR DAY LOGIC (Tue-Sun) ---
def run_regular_post(bsky):
    logger.info("📅 It is a Regular Day. Initiating Game Spotlight.")

    # 1. Fetch Game from RAWG
    used_games = load_json('history_games.json', [])
    
    # Try 5 times to find a game we haven't used
    game = None
    for attempt in range(5):
        random_page = random.randint(1, 200)
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&platforms=27,21,18&ordering=-rating&page_size=1&page={random_page}"
        
        try:
            data = requests.get(url).json()
            if data['results']:
                candidate = data['results'][0]
                if candidate['id'] not in used_games and candidate.get('short_screenshots'):
                    game = candidate
                    break
        except Exception as e:
            logger.error(f"⚠️ RAWG API Error on attempt {attempt}: {e}")

    if not game:
        logger.error("❌ Could not find a fresh game after 5 attempts. Aborting.")
        return

    logger.info(f"🎮 Game Found: {game['name']} (ID: {game['id']})")

    # 2. Generate Text
    prompt = (
        f"Write a nostalgic Bluesky post about the video game '{game['name']}'. "
        "Mention a specific detail about gameplay or atmosphere. "
        "End with a thought-provoking question. "
        "Under 240 characters. No quotes."
    )
    caption = get_claude_text(prompt)
    if not caption:
        caption = f"Remember {game['name']}? What a classic! 🕹️"

    final_text = f"{caption}\n\nMore info: https://nostalgia.icu/game/{game['slug']}\n\n#RetroGaming #{game['name'].replace(' ', '')}"

    # 3. Prepare Images
    # We want 1-3 Game Screenshots + 1 Promo Card
    images_to_embed = []
    
    # A. Get Screenshots
    screenshots = game.get('short_screenshots', [])
    count = 0
    for shot in screenshots:
        if count >= 3: break # Max 3 screenshots
        img_bytes = download_image_bytes(shot['image'])
        if img_bytes:
            upload = bsky.upload_blob(img_bytes)
            images_to_embed.append(models.AppBskyEmbedImages.Image(alt=f"Screenshot of {game['name']}", image=upload.blob))
            count += 1
    
    logger.info(f"📸 Downloaded {count} screenshots.")

    # B. Add Promo Card (The 4th Image)
    promo_path = "images/promo_ad.jpg"
    if os.path.exists(promo_path):
        with open(promo_path, 'rb') as f:
            promo_bytes = f.read()
            upload = bsky.upload_blob(promo_bytes)
            images_to_embed.append(models.AppBskyEmbedImages.Image(alt="Visit Nostalgia.icu", image=upload.blob))
            logger.info("✅ Promo card attached.")
    else:
        logger.warning("⚠️ 'promo_ad.jpg' not found! Posting without it.")

    # 4. Post
    if images_to_embed:
        bsky.send_post(text=final_text, embed=models.AppBskyEmbedImages.Main(images=images_to_embed))
        logger.info(f"✅ Post for {game['name']} sent successfully!")
        
        # Save to history
        used_games.append(game['id'])
        # Keep history file from getting too big (last 1000 games)
        if len(used_games) > 1000: used_games.pop(0)
        save_json('history_games.json', used_games)
    else:
        logger.error("❌ No images available to post. Aborting.")

# --- MAIN EXECUTION ---
def main():
    logger.info("--- BOT RUN STARTED ---")
    
    # Authenticate Bluesky
    try:
        bsky = Client()
        bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("✅ Connected to Bluesky.")
    except Exception as e:
        logger.error(f"❌ Bluesky Login Failed: {e}")
        return

    # Check Day
    # Monday is 0, Sunday is 6
    day_of_week = datetime.now().weekday()
    
    if day_of_week == 0:
        run_monday_ad(bsky)
    else:
        run_regular_post(bsky)

    logger.info("--- BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
