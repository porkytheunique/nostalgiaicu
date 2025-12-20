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
BSKY_PASSWORD = os.environ.get("BSKY_PASSWORD")

# --- AUTHORITY FRANCHISE MAP (Option B) ---
FRANCHISE_MAP = {
    "ZELDA": "#LegendOfZelda", "MARIO": "#SuperMario", "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog", "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil", "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania", "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter", "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar", "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan"
}

# --- RETRO CONSTANTS ---
RETRO_PLATFORMS = {
    167: "Sega Genesis", 79: "SNES", 24: "GBA", 27: "PS1", 15: "PS2", 
    83: "N64", 106: "Dreamcast", 80: "Xbox", 49: "NES", 105: "GameCube",
    109: "TurboGrafx-16", 117: "Sega 32X", 119: "Sega CD", 12: "Neo Geo", 43: "GBC"
}
RETRO_IDS_STR = ",".join(map(str, RETRO_PLATFORMS.keys()))
GENRES = {"Platformer": 83, "Shooter": 2, "RPG": 5, "Fighting": 6, "Racing": 1}

# UTC SCHEDULE
SCHEDULE = {
    0: {9: 1, 15: 2, 21: 13}, 1: {9: 9, 15: 3, 21: 14}, 2: {9: 4, 15: 17, 21: 13},
    3: {9: 6, 15: 18, 21: 14}, 4: {9: 7, 15: 8, 21: 13}, 5: {9: 9, 15: 10, 21: 15},
    6: {9: 11, 15: 12, 21: 13}
}

# --- CORE HELPERS ---

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
    buf = BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

def create_collage(images, grid=(2,1)):
    if not images: return None
    target_h = 600
    resized_imgs = []
    for img in images:
        aspect = img.width / img.height
        resized_imgs.append(img.resize((int(target_h * aspect), target_h)))
    if grid == (2,1):
        total_w = sum(i.width for i in resized_imgs)
        collage = Image.new('RGB', (total_w, target_h))
        x_off = 0
        for img in resized_imgs:
            collage.paste(img, (x_off, 0)); x_off += img.width
        return collage
    return images[0]

# --- AUTHORITY LOGIC ---

def clean_game_hashtag(game_name):
    words = game_name.split(':')[0].split('-')[0].split()
    short = "".join(words[:2])
    clean = re.sub(r'[^a-zA-Z0-9]', '', short)
    return f"#{clean}" if len(clean) > 2 else "#RetroGaming"

def get_authority_tags(game_name, platforms_data):
    tags = ["#Retro", "#RetroGaming"]
    upper_name = game_name.upper()
    found_f = False
    for key, tag in FRANCHISE_MAP.items():
        if key in upper_name:
            tags.append(tag); found_f = True; break
    if not found_f: tags.append(clean_game_hashtag(game_name))
    
    console_tag, pc_tag = None, None
    for p in platforms_data:
        p_id = p['platform']['id']
        if p_id in RETRO_PLATFORMS:
            console_tag = f"#{RETRO_PLATFORMS[p_id].replace(' ', '')}"
            break 
        elif "PC" in p['platform']['name']: pc_tag = "#PCGaming"
    tags.append(console_tag if console_tag else pc_tag if pc_tag else "#RetroGaming")
    return " ".join(list(set(tags)))

def get_milestone_info(game_data):
    try:
        r_year = datetime.strptime(game_data.get('released', '1900-01-01'), "%Y-%m-%d").year
        age = 2025 - r_year
        return f"This is the {age}th anniversary year." if age > 0 else ""
    except: return ""

def deep_fetch_game(game_id):
    url = f"https://api.rawg.io/api/games/{game_id}?key={RAWG_API_KEY}"
    logger.info(f"💎 [DEEP FETCH] Querying game_id {game_id}")
    return requests.get(url).json()

def fetch_games_list(count=1, genre_id=None):
    used = load_json('history_games.json', [])
    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&ordering=-rating&page_size=30&platforms={RETRO_IDS_STR}"
    if genre_id: url += f"&genres={genre_id}"
    data = requests.get(url).json().get('results', [])
    valid = [g for g in data if g['id'] not in used]
    return random.sample(valid, min(count, len(valid)))

# --- POSTING SYSTEM ---

def post_to_bsky(bsky, final_text, imgs):
    try:
        blobs = []
        for img in imgs:
            blob = bsky.upload_blob(image_to_bytes(img)).blob
            blobs.append(models.AppBskyEmbedImages.Image(alt="Retro Gaming", image=blob))
        embed = models.AppBskyEmbedImages.Main(images=blobs[:4])
        bsky.send_post(final_text, embed=embed)
        logger.info("✅ Post successful.")
        return True
    except Exception as e:
        logger.error(f"❌ Post failed: {e}")
        return False

def post_with_retry(bsky, game_id, theme, custom_header=""):
    full_game = deep_fetch_game(game_id)
    name, genre = full_game['name'], ", ".join([g['name'] for g in full_game['genres'][:2]])
    r_date, m_info = full_game.get('released', 'N/A'), get_milestone_info(full_game)
    tags = get_authority_tags(name, full_game['platforms'])
    
    logger.info(f"📊 Processing: {name}")

    for attempt in range(1, 4):
        if attempt == 1: p = f"Post about '{name}' ({genre}) released {r_date}. {m_info} Theme: {theme}. Under 100 chars. No hashtags."
        elif attempt == 2: p = f"RETRY: Summarize {name} in one short, punchy sentence. Max 60 chars."
        
        if attempt == 3: text = f"The {genre} classic {name} ({r_date[:4]})."
        else:
            msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                model="claude-3-haiku-20240307", max_tokens=150, messages=[{"role": "user", "content": p}]
            )
            text = msg.content[0].text.strip().replace('"', '')

        final_post = f"{custom_header}{text}\n\n{tags}"
        if len(final_post) < 298:
            img = download_image(full_game['background_image'])
            if post_to_bsky(bsky, final_post, [img] if img else []):
                used = load_json('history_games.json', [])
                save_json('history_games.json', (used + [game_id])[-2000:])
                return True
    return False

# --- SLOT HANDLERS ---

def run_on_this_day(bsky):
    m, d = datetime.now().month, datetime.now().day
    for _ in range(10): 
        y = random.randint(1985, 2005)
        ds = f"{y}-{m:02d}-{d:02d}"
        resp = requests.get(f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={ds},{ds}&platforms={RETRO_IDS_STR}").json()
        if resp.get('results'):
            if post_with_retry(bsky, resp['results'][0]['id'], "celebratory", f"📅 On This Day in {y}\n\n"): return
    run_single_game(bsky, "hidden gem")

def run_rivalry(bsky):
    g_name, g_id = random.choice(list(GENRES.items()))
    games = fetch_games_list(count=2, genre_id=g_id)
    if len(games) < 2: return
    t1, t2 = clean_game_hashtag(games[0]['name']), clean_game_hashtag(games[1]['name'])
    p = f"Compare {games[0]['name']} and {games[1]['name']} (both {g_name}). Under 120 chars. Ask fans to pick. No hashtags."
    text = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    ).content[0].text.strip()
    collage = create_collage([download_image(g['background_image']) for g in games])
    post_to_bsky(bsky, f"{text}\n\n#Retro #RetroGaming {t1} {t2}", [collage])

def run_single_game(bsky, theme):
    game = fetch_games_list(count=1)
    if game: post_with_retry(bsky, game[0]['id'], theme)

# --- MAIN ---

def main():
    logger.info("--- 🚀 NOSTALGIA BOT STARTING ---")
    try:
        if not BSKY_HANDLE or not BSKY_PASSWORD: raise ValueError("Missing BSKY credentials.")
        bsky = Client()
        bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("📡 [AUTH] Connected.")
    except Exception as e:
        logger.error(f"❌ [AUTH FAIL]: {e}"); return

    forced = os.environ.get("FORCED_SLOT", "")
    manual = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', forced).group(1)) if manual else SCHEDULE.get(now.weekday(), {}).get(now.hour)

    if not slot_id: logger.info("⏳ No slot scheduled."); return
    logger.info(f"🚀 Slot {slot_id}")

    handlers = {
        13: run_on_this_day, 14: run_on_this_day, 3: run_rivalry, 18: run_rivalry,
        4: lambda b: run_single_game(b, "unpopular opinion"),
        6: lambda b: run_single_game(b, "hidden gem"),
        9: lambda b: run_single_game(b, "aesthetic pixel art visuals"),
        11: lambda b: run_single_game(b, "nostalgic childhood memory")
    }
    
    if slot_id in handlers: handlers[slot_id](bsky)
    logger.info("--- 🏁 BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
