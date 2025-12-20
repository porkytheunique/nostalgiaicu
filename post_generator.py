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

# 09:00, 15:00, 21:00 UTC
SCHEDULE = {
    0: {9: 1, 15: 2, 21: 13}, 1: {9: 9, 15: 3, 21: 14}, 2: {9: 4, 15: 17, 21: 13},
    3: {9: 6, 15: 18, 21: 14}, 4: {9: 7, 15: 8, 21: 13}, 5: {9: 9, 15: 10, 21: 15},
    6: {9: 11, 15: 12, 21: 13}
}

# --- AUTHORITY HELPERS ---

def get_authority_tags(game_name, platforms_data):
    tags = ["#Retro", "#RetroGaming"]
    upper_name = game_name.upper()
    found_f = False
    for key, tag in FRANCHISE_MAP.items():
        if key in upper_name:
            tags.append(tag); found_f = True; break
    if not found_f:
        words = game_name.split(':')[0].split('-')[0].split()
        tags.append(f"#{re.sub(r'[^a-zA-Z0-9]', '', ''.join(words[:2]))}")

    console_tag, pc_tag = None, None
    for p in platforms_data:
        p_id, p_name = p['platform']['id'], p['platform']['name']
        if p_id in RETRO_PLATFORMS:
            console_tag = f"#{RETRO_PLATFORMS[p_id].replace(' ', '')}"
            break 
        elif "PC" in p_name: pc_tag = "#PCGaming"
            
    tags.append(console_tag if console_tag else pc_tag if pc_tag else "#RetroGaming")
    return list(set(tags))

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

# --- POSTING ENGINE ---

def post_with_retry(bsky, game_id, theme, custom_header=""):
    full_game = deep_fetch_game(game_id)
    name, genre = full_game['name'], ", ".join([g['name'] for g in full_game['genres'][:2]])
    r_date, m_info = full_game.get('released', 'N/A'), get_milestone_info(full_game)
    tags = " ".join(get_authority_tags(name, full_game['platforms']))
    
    logger.info(f"📊 [DATA PACK] {name} | Year: {r_date} | Genre: {genre}")

    for attempt in range(1, 4):
        if attempt == 1:
            p = f"Write a {theme} post about '{name}' ({genre}) released {r_date}. {m_info} Under 100 chars. No hashtags."
        elif attempt == 2:
            p = f"RETRY: Summarize {name} in one punchy sentence under 70 chars."
        
        if attempt == 3:
            text = f"Remember the {genre} classic {name}? Released {r_date[:4]}."
        else:
            msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                model="claude-3-haiku-20240307", max_tokens=150,
                messages=[{"role": "user", "content": p}]
            )
            text = msg.content[0].text.strip().replace('"', '')

        final_post = f"{custom_header}{text}\n\n{tags}"
        
        if len(final_post) < 298:
            img = download_image(full_game['background_image'])
            if post_to_bsky(bsky, final_text=final_post, imgs=[img] if img else []):
                return True
    return False

# --- SLOTS ---

def run_on_this_day(bsky):
    m, d = datetime.now().month, datetime.now().day
    logger.info(f"📅 [ON THIS DAY] Checking {m}/{d}...")
    for _ in range(10): 
        y = random.randint(1985, 2005)
        ds = f"{y}-{m:02d}-{d:02d}"
        resp = requests.get(f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={ds},{ds}&platforms={RETRO_IDS_STR}").json()
        if resp.get('results'):
            if post_with_retry(bsky, resp['results'][0]['id'], "celebratory", f"📅 On This Day in {y}\n\n"):
                return
    run_fact(bsky)

def run_rivalry(bsky):
    g_name, g_id = random.choice(list(GENRES.items()))
    logger.info(f"⚔️ [RIVALRY] Genre: {g_name}")
    games = fetch_games(count=2, genre_id=g_id)
    if len(games) < 2: return
    
    t1, t2 = clean_game_hashtag(games[0]['name']), clean_game_hashtag(games[1]['name'])
    p = f"Compare {games[0]['name']} and {games[1]['name']} (both {g_name}). Under 130 chars. Ask fans to pick. No hashtags."
    text = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    ).content[0].text.strip()
    
    collage = create_collage([download_image(g['background_image']) for g in games], grid=(2,1))
    post_to_bsky(bsky, f"{text}\n\n#Retro #RetroGaming {t1} {t2}", [collage])

# --- DISPATCHER ---

def main():
    logger.info("--- 🚀 NOSTALGIA BOT STARTING ---")
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("📡 [AUTH] Connected.")
    except Exception as e:
        logger.error(f"❌ [AUTH FAIL]: {e}"); return

    forced = os.environ.get("FORCED_SLOT", "")
    manual = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', forced).group(1)) if manual else SCHEDULE.get(now.weekday(), {}).get(now.hour)

    if not slot_id:
        logger.info("⏳ No slot scheduled."); return

    logger.info(f"🚀 Executing Slot {slot_id}")
    handlers = {
        13: run_on_this_day, 14: run_on_this_day,
        3: run_rivalry, 18: run_rivalry,
        4: lambda b: run_single_game(b, "unpopular opinion"),
        6: lambda b: run_single_game(b, "hidden gem"),
        9: lambda b: run_single_game(b, "aesthetic pixel art"),
        11: lambda b: run_single_game(b, "nostalgic memory")
    }
    
    if slot_id in handlers:
        handlers[slot_id](bsky)
    
    logger.info("--- 🏁 BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
