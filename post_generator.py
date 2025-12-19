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
    "ZELDA": "#LegendOfZelda",
    "MARIO": "#SuperMario",
    "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog",
    "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil",
    "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania",
    "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter",
    "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar",
    "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken",
    "MORTAL KOMBAT": "#MortalKombat"
}

# --- RETRO CONSTANTS ---
RETRO_PLATFORMS = {
    167: "Sega Genesis", 79: "SNES", 24: "GBA", 27: "PS1", 15: "PS2", 
    83: "N64", 106: "Dreamcast", 80: "Xbox", 49: "NES", 105: "GameCube",
    109: "TurboGrafx-16", 117: "Sega 32X", 119: "Sega CD", 12: "Neo Geo", 43: "GBC"
}
RETRO_IDS_STR = ",".join(map(str, RETRO_PLATFORMS.keys()))
GENRES = {"Platformer": 83, "Shooter": 2, "RPG": 5, "Fighting": 6, "Racing": 1}

# --- AUTHORITY HELPERS ---

def get_authority_tags(game_name, platforms_data):
    """
    1. Checks the Authority Map for franchise tags.
    2. Identifies the original console (prioritizing retro consoles over PC).
    """
    tags = ["#Retro", "#RetroGaming"]
    
    # Franchise Tag
    upper_name = game_name.upper()
    found_franchise = False
    for key, tag in FRANCHISE_MAP.items():
        if key in upper_name:
            tags.append(tag)
            found_franchise = True
            break
    if not found_franchise:
        words = game_name.split(':')[0].split('-')[0].split()
        clean = re.sub(r'[^a-zA-Z0-9]', '', "".join(words[:2]))
        tags.append(f"#{clean}")

    # Console Priority Tag
    console_tag = None
    pc_tag = None
    for p in platforms_data:
        p_id = p['platform']['id']
        p_name = p['platform']['name']
        if p_id in RETRO_PLATFORMS:
            console_tag = f"#{RETRO_PLATFORMS[p_id].replace(' ', '')}"
            break # Found a priority console
        elif "PC" in p_name:
            pc_tag = "#PCGaming"
            
    tags.append(console_tag if console_tag else pc_tag if pc_tag else "#RetroGaming")
    return list(set(tags))

def get_anniversary_string(released_at):
    """Calculates if this is a milestone year."""
    try:
        release_year = datetime.strptime(released_at, "%Y-%m-%d").year
        age = 2025 - release_year
        if age > 0:
            return f"It is the {age}th Anniversary of this launch!"
    except: pass
    return ""

def deep_fetch_game(game_id):
    """Fetches full metadata to ensure 100% accuracy on dates and platforms."""
    url = f"https://api.rawg.io/api/games/{game_id}?key={RAWG_API_KEY}"
    logger.info(f"💎 [DEEP FETCH] Querying game details: {url}")
    return requests.get(url).json()

# --- MAIN POSTING LOGIC ---

def generate_and_post(bsky, game_data, theme_prompt, custom_header=""):
    # Double-Fetch for accuracy
    full_game = deep_fetch_game(game_data['id'])
    
    name = full_game['name']
    genre = ", ".join([g['name'] for g in full_game['genres'][:2]])
    release_date = full_game.get('released', 'Unknown')
    anniversary = get_anniversary_string(release_date)
    tags = get_authority_tags(name, full_game['platforms'])
    
    # Diagnostic Log
    logger.info(f"📊 [DATA PACK] Game: {name} | Year: {release_date} | Genre: {genre}")

    base_prompt = (f"Write a {theme_prompt} post about '{name}'. "
                   f"Context: {genre} game released in {release_date}. {anniversary} "
                   f"Keep it EXTREMELY BRIEF and ENGAGING (Under 100 chars). NO hashtags.")

    for attempt in range(1, 4):
        text = ""
        if attempt == 1:
            text = get_claude_response(base_prompt)
        elif attempt == 2:
            text = get_claude_response(f"RETRY: Write only ONE punchy sentence about {name} and its {genre}. Max 70 chars.")
        else:
            text = f"Remember this {genre} classic? {name} from {release_date}."

        final_text = f"{custom_header}{text}\n\n{' '.join(tags)}"
        
        # Length Validation
        if len(final_text) < 295:
            img = download_image(full_game['background_image'])
            if post_to_bluesky(bsky, final_text, [img] if img else []):
                return True
        logger.warning(f"⚠️ Attempt {attempt} too long ({len(final_text)} chars).")

    return False

# --- SLOT HANDLERS ---

def run_on_this_day(bsky):
    now = datetime.now()
    month, day = now.month, now.day
    logger.info(f"📅 [ON THIS DAY] Searching for games released on {month}/{day}...")
    
    # Search for games released on this day in any retro year
    for _ in range(5):
        year = random.randint(1985, 2005)
        date_str = f"{year}-{month:02d}-{day:02d}"
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={date_str},{date_str}&platforms={RETRO_IDS_STR}"
        resp = requests.get(url).json()
        if resp.get('results'):
            game = random.choice(resp['results'])
            header = f"📅 On This Day in {year}\n\n"
            if generate_and_post(bsky, game, "celebratory", custom_header=header):
                return
    logger.error("❌ No games found for 'On This Day'. Falling back to Random Fact.")
    run_fact(bsky)

# (Other slots: run_rivalry, run_single_game, run_fact follow this same 'generate_and_post' structure)

# --- MAIN EXECUTION ---
def main():
    logger.info("--- 🚀 NOSTALGIA BOT STARTING ---")
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("📡 Connected.")
    except Exception as e:
        logger.error(f"❌ Auth Fail: {e}"); return

    # Manual vs Auto Logic
    forced = os.environ.get("FORCED_SLOT", "")
    manual = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', forced).group(1)) if manual else SCHEDULE.get(now.weekday(), {}).get(now.hour)

    if not slot_id: return
    logger.info(f"🚀 Executing Slot {slot_id}")

    # Handler mapping
    if slot_id in [13, 14]: run_on_this_day(bsky)
    elif slot_id == 4: run_single_game(bsky, "unpopular opinion")
    elif slot_id == 6: run_single_game(bsky, "hidden gem")
    elif slot_id == 3: run_rivalry(bsky)
    # ... Add remaining slot mappings ...

if __name__ == "__main__":
    main()
