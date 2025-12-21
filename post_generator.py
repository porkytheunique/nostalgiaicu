import os
import sys
import json
import random
import requests
import logging
import re
from io import BytesIO
from datetime import datetime
from PIL import Image
from atproto import Client, models, client_utils
import anthropic

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

# --- CONFIGURATION ---
RAWG_API_KEY = os.environ.get("RAWG_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BSKY_HANDLE = os.environ.get("BLUESKY_HANDLE")
BSKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD")

# --- AUTHORITY FRANCHISE MAP ---
FRANCHISE_MAP = {
    "ZELDA": "#LegendOfZelda", "MARIO": "#SuperMario", "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog", "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil", "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania", "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter", "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar", "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan",
    "GODZILLA": "#Godzilla", "KUNIO": "#KunioKun", "NEKKETSU": "#KunioKun"
}

RETRO_PLATFORMS = {
    167: "Sega Genesis", 79: "SNES", 24: "GBA", 27: "PS1", 15: "PS2", 
    83: "N64", 106: "Dreamcast", 80: "Xbox", 49: "NES", 105: "GameCube",
    109: "TurboGrafx-16", 117: "Sega 32X", 119: "Sega CD", 12: "Neo Geo", 43: "GBC"
}
RETRO_IDS_STR = ",".join(map(str, RETRO_PLATFORMS.keys()))
GENRES = {"Platformer": 83, "Shooter": 2, "RPG": 5, "Fighting": 6, "Racing": 1}

SCHEDULE = {
    0: {9: 1, 15: 2, 21: 13}, 1: {9: 9, 15: 3, 21: 14}, 2: {9: 4, 15: 17, 21: 13},
    3: {9: 6, 15: 18, 21: 14}, 4: {9: 7, 15: 8, 21: 13}, 5: {9: 9, 15: 10, 21: 15},
    6: {9: 11, 15: 12, 21: 13}
}

# --- HELPERS ---

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f: return json.load(f)
        except: return default
    return default

def save_json(filename, data):
    with open(filename, 'w') as f: json.dump(data, f)

def download_image(url):
    try:
        resp = requests.get(url, timeout=10)
        return Image.open(BytesIO(resp.content)) if resp.status_code == 200 else None
    except: return None

def image_to_bytes(img):
    quality = 85
    for i in range(5):
        buf = BytesIO()
        temp_img = img.convert("RGB")
        temp_img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) < 950000: return data
        quality -= 15
    return data

def clean_game_hashtag(game_name):
    upper_name = game_name.upper()
    for key, tag in FRANCHISE_MAP.items():
        if key in upper_name: return tag
    words = game_name.split(':')[0].split('-')[0].split()
    clean = re.sub(r'[^a-zA-Z0-9]', '', "".join(words[:2]))
    return f"#{clean}" if len(clean) > 2 else "#RetroGaming"

def get_platform_tags(game_data, limit=1):
    found_tags, has_console = [], False
    for p in game_data.get('platforms', []):
        p_id = p['platform']['id']
        if p_id in RETRO_PLATFORMS:
            found_tags.append(f"#{RETRO_PLATFORMS[p_id].replace(' ', '')}")
            has_console = True; break
    if not has_console:
        for p in game_data.get('platforms', []):
            if "PC" in p['platform']['name']: found_tags.append("#PCGaming"); break
    return list(set(found_tags))[:limit] if found_tags else ["#RetroGaming"]

def deep_fetch_game(game_id):
    url = f"https://api.rawg.io/api/games/{game_id}?key={RAWG_API_KEY}"
    try:
        resp = requests.get(url, timeout=10)
        return resp.json()
    except: return None

def fetch_games_list(count=1, genre_id=None):
    used = load_json('history_games.json', [])
    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&ordering=-rating&page_size=40&platforms={RETRO_IDS_STR}"
    if genre_id: url += f"&genres={genre_id}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json().get('results', [])
        valid = [g for g in data if g['id'] not in used]
        return random.sample(valid, min(count, len(valid))) if valid else []
    except: return []

# --- POSTING SYSTEM ---

def post_with_retry(bsky, game_id, theme, slot_tag, custom_header=""):
    full_game = deep_fetch_game(game_id)
    if not full_game: return False
    
    name, genre = full_game['name'], ", ".join([g['name'] for g in full_game['genres'][:2]])
    r_date = full_game.get('released', 'N/A')
    p_tags = get_platform_tags(full_game, 1)
    g_tag = clean_game_hashtag(name)
    
    logger.info(f"📊 [STRICT FETCH] Starting collection for: {name}")

    for attempt in range(1, 4):
        p = (f"Write a {theme} post about '{name}' ({genre}) released {r_date}. "
             f"MANDATORY: End with a thought-provoking question for fans. Under 110 chars. No hashtags.")
        
        if attempt == 2: p = f"RETRY: Summarize {name} in one sentence with a question. Max 70 chars."
        
        if attempt == 3: text = f"Is {name} ({r_date[:4]}) a true classic? What do you think?"
        else:
            try:
                msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                    model="claude-3-haiku-20240307", max_tokens=150, messages=[{"role": "user", "content": p}]
                )
                text = msg.content[0].text.strip().replace('"', '')
            except: text = f"Remembering {name} ({r_date[:4]}). Thoughts?"

        tb = client_utils.TextBuilder()
        tb.text(f"{custom_header}{text}\n\n")
        
        # FIX: Combine all tags properly including slot_tag
        all_tags = list(set(["#Retro", "#RetroGaming", g_tag, slot_tag] + p_tags))
        for i, tag in enumerate(all_tags):
            tb.tag(tag, tag.replace("#", ""))
            if i < len(all_tags) - 1: tb.text(" ")

        if len(tb.build_text()) < 298:
            imgs = []
            bg_url = full_game.get('background_image')
            
            # 1. Main Background
            bg = download_image(bg_url)
            if bg: imgs.append(bg)
            
            # 2. Aggressive Screenshot Fetch
            all_screens = full_game.get('short_screenshots', [])
            for shot in all_screens:
                if len(imgs) >= 3: break
                s_url = shot.get('image')
                if s_url == bg_url: continue 
                s_img = download_image(s_url)
                if s_img: imgs.append(s_img)
            
            # 3. Final Promo Ad
            if os.path.exists("images/promo_ad.jpg"):
                with Image.open("images/promo_ad.jpg") as ad: imgs.append(ad.copy())

            logger.info(f"📸 [IMAGE LOG] Final count for upload: {len(imgs)}")

            blobs = []
            for img in imgs[:4]:
                blob_data = image_to_bytes(img)
                blob = bsky.upload_blob(blob_data).blob
                blobs.append(models.AppBskyEmbedImages.Image(alt=f"{name}", image=blob))
            
            bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
            save_json('history_games.json', (load_json('history_games.json', []) + [game_id])[-2000:])
            return True
    return False

# --- SLOT HANDLERS ---

def run_single_game(bsky, theme, slot_tag):
    games = fetch_games_list(count=1)
    if games: post_with_retry(bsky, games[0]['id'], theme, slot_tag)

def main():
    logger.info("--- 🚀 NOSTALGIA BOT STARTING ---")
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("📡 Connected.")
    except Exception as e:
        logger.error(f"❌ [AUTH FAIL]: {e}"); return

    forced = os.environ.get("FORCED_SLOT", "")
    manual = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', forced).group(1)) if manual else SCHEDULE.get(now.weekday(), {}).get(now.hour)

    if not slot_id: return
    logger.info(f"🚀 Executing Slot {slot_id}")

    handlers = {
        4: lambda b: run_single_game(b, "unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, "obscure hidden gem", "#HiddenGem"),
        9: lambda b: run_single_game(b, "aesthetic visuals", "#PixelArt"),
        11: lambda b: run_single_game(b, "childhood memory", "#Nostalgia")
    }
    
    if slot_id in handlers: handlers[slot_id](bsky)
    logger.info("--- 🏁 BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
