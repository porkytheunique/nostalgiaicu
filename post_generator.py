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

# --- CONSTANTS ---
RANDOM_PROMO_CHANCE = 0.33 
CURRENT_YEAR = 2026 # Force grounding

# Prioritized list to find the "Original/Iconic" platform
PLATFORM_PRIORITY = [
    49,  # NES
    79,  # SNES
    167, # Genesis
    109, # TG-16
    12,  # Neo Geo
    27,  # PS1
    83,  # N64
    106, # Dreamcast
    15,  # PS2
    105, # GameCube
    80,  # Xbox
    24,  # GBA
    43   # GBC
]

FRANCHISE_MAP = {
    "ZELDA": "#LegendOfZelda", "MARIO": "#SuperMario", "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog", "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil", "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania", "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter", "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar", "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan",
    "EVERMORE": "#SecretOfEvermore", "CHRONO": "#ChronoTrigger", "GRAND THEFT AUTO": "#GrandTheftAuto"
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
    3: {9: 6, 15: 18, 21: 14}, 4: {9: 9, 15: 8, 21: 13}, 5: {9: 9, 15: 10, 21: 15},
    6: {9: 11, 15: 12, 21: 13}
}

# --- HELPERS ---

def load_json(filename, default):
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f: return json.load(f)
    except: pass
    return default

def save_json(filename, data):
    try:
        with open(filename, 'w') as f: json.dump(data, f)
    except: pass

def download_image(url):
    if not url: return None
    try:
        resp = requests.get(url, timeout=12)
        return Image.open(BytesIO(resp.content)) if resp.status_code == 200 else None
    except: return None

def image_to_bytes(img):
    quality = 85
    for _ in range(5):
        buf = BytesIO()
        temp_img = img.convert("RGB")
        temp_img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) < 950000: return data
        quality -= 15
    return data

def create_collage(images):
    if not images or len(images) < 2: return images[0] if images else None
    target_h = 600
    resized = [img.resize((int(target_h * (img.width/img.height)), target_h)) for img in images[:2]]
    total_w = sum(i.width for i in resized)
    collage = Image.new('RGB', (total_w, target_h))
    x = 0
    for i in resized: collage.paste(i, (x,0)); x += i.width
    return collage

def clean_game_hashtag(game_name, current_tags):
    upper = game_name.upper()
    for k, v in FRANCHISE_MAP.items():
        if k in upper: return v
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', game_name)
    words = clean_name.split()[:3]
    tag = "#" + "".join(word.capitalize() for word in words)
    if len(tag) > 25 or len(tag) < 3:
        return "#Nostalgia" if "#Nostalgia" not in current_tags else None
    return tag

def get_platform_tags(game_data):
    # Search through platforms list based on our priority list
    p_ids = [p['platform']['id'] for p in game_data.get('platforms', [])]
    for priority_id in PLATFORM_PRIORITY:
        if priority_id in p_ids:
            tag = f"#{RETRO_PLATFORMS[priority_id].replace(' ', '')}"
            return [tag]
    return ["#RetroGaming"]

def fetch_games_list(api_key, count=1, genre_id=None, dates=None):
    rand_page = random.randint(1, 10)
    url = f"https://api.rawg.io/api/games?key={api_key}&platforms={RETRO_IDS_STR}&page_size=40&page={rand_page}"
    if genre_id: url += f"&genres={genre_id}"
    if dates: url += f"&dates={dates}"
    try:
        resp = requests.get(url, timeout=10).json()
        results = resp.get('results', [])
        history = load_json('history_games.json', [])
        available = [g for g in results if g['id'] not in history]
        if not available: available = results
        return random.sample(available, min(len(available), count))
    except: return []

def deep_fetch_game(api_key, game_id):
    url = f"https://api.rawg.io/api/games/{game_id}?key={api_key}"
    try: return requests.get(url, timeout=10).json()
    except: return None

def get_deep_images(api_key, full_game_obj, limit=3):
    final_imgs = []
    seen_urls = set()
    def add_url(url):
        if url and url not in seen_urls and len(final_imgs) < limit:
            img = download_image(url)
            if img:
                final_imgs.append(img)
                seen_urls.add(url)
    add_url(full_game_obj.get('background_image_additional'))
    add_url(full_game_obj.get('background_image'))
    try:
        ss_url = f"https://api.rawg.io/api/games/{full_game_obj['id']}/screenshots?key={api_key}"
        res = requests.get(ss_url, timeout=10).json().get('results', [])
        for s in res: add_url(s.get('image'))
    except: pass
    if len(final_imgs) < limit:
        for s in full_game_obj.get('short_screenshots', []): add_url(s.get('image'))
    return final_imgs

# --- CORE HANDLERS ---

def run_rivalry(bsky, api_key, anthropic_key):
    g_name, g_id = random.choice(list(GENRES.items()))
    games_basic = fetch_games_list(api_key, count=2, genre_id=g_id)
    if len(games_basic) < 2: return
    g1, g2 = deep_fetch_game(api_key, games_basic[0]['id']), deep_fetch_game(api_key, games_basic[1]['id'])
    
    logger.info(f"⚔️ Rivalry: {g1['name']} vs {g2['name']}")
    prompt = (f"Compare '{g1['name']}' and '{g2['name']}' in a cool, nostalgic way. "
              f"Ask followers a 'Pick one' question at the end. Limit: 200 chars. No hashtags.")
    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=250, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace('"', '')

    tags = ["#Retro", "#RetroGaming", "#Rivalry"]
    for g in [g1, g2]:
        t = clean_game_hashtag(g['name'], tags); 
        if t: tags.append(t)
    unique_tags = list(dict.fromkeys(tags))

    tb = client_utils.TextBuilder()
    tb.text(f"{text[:220]}\n\n")
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", "")); 
        if i < len(unique_tags)-1: tb.text(" ")

    final_imgs = []
    c1 = download_image(g1.get('background_image_additional') or g1.get('background_image'))
    c2 = download_image(g2.get('background_image_additional') or g2.get('background_image'))
    if c1 and c2: final_imgs.append(create_collage([c1, c2]))
    
    for g in [g1, g2]:
        screens = get_deep_images(api_key, g, limit=5)
        if len(screens) > 1: final_imgs.append(screens[1])

    if random.random() < RANDOM_PROMO_CHANCE and os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: final_imgs.append(ad.copy())

    blobs = [models.AppBskyEmbedImages.Image(alt="Rivalry", image=bsky.upload_blob(image_to_bytes(i)).blob) for i in final_imgs[:4] if i]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))

def run_single_game(bsky, api_key, anthropic_key, theme_desc, slot_tag, force_on_this_day=False):
    game, header, now = None, "", datetime.now()
    if force_on_this_day:
        for _ in range(5):
            yr = random.randint(1985, 2005)
            d_str = f"{yr}-{now.strftime('%m-%d')}"
            res = fetch_games_list(api_key, count=1, dates=f"{d_str},{d_str}")
            if res:
                game, header = res[0], f"📅 On This Day in {yr}\n\n"
                break
        if not game:
            m_name, yr_fb = now.strftime('%B'), random.randint(1985, 2005)
            res = fetch_games_list(api_key, count=1, dates=f"{yr_fb}-{now.strftime('%m')}-01,{yr_fb}-{now.strftime('%m')}-28")
            if res: game, header = res[0], f"🗓️ In {m_name}, {yr_fb}\n\n"
    
    if not game:
        res = fetch_games_list(api_key, count=1)
        game = res[0] if res else None
    
    if not game: return
    full = deep_fetch_game(api_key, game['id'])
    
    # --- Python Calculation for Grounding ---
    rel_str = full.get('released', 'Unknown')
    age_text = ""
    if rel_str != 'Unknown':
        try:
            rel_year = int(rel_str.split('-')[0])
            age = CURRENT_YEAR - rel_year
            age_text = f"This game is exactly {age} years old in 2026."
        except: pass

    logger.info(f"🎮 {slot_tag} | {full['name']} | Released: {rel_str}")

    prompt = (f"Write a {theme_desc} post about '{full['name']}'. "
              f"FACT: It was released in {rel_str}. Today is February 2026. {age_text} "
              f"Instructions: Use a strong hook, one personal detail, and MUST end with a question. "
              f"Limit: 220 chars. Ground yourself in the year {CURRENT_YEAR}. No hashtags.")

    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=250, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace('"', '')
    
    tags = ["#Retro", "#RetroGaming", slot_tag] + get_platform_tags(full)
    gtag = clean_game_hashtag(full['name'], tags)
    if gtag: tags.append(gtag)
    unique_tags = list(dict.fromkeys(tags))

    # Safe Truncation Logic
    final_body = f"{header}{text}"
    if len(final_body) > 250:
        final_body = final_body[:245].rsplit('.', 1)[0] + "." # Cut at last sentence

    tb = client_utils.TextBuilder()
    tb.text(f"{final_body}\n\n")
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", "")); 
        if i < len(unique_tags)-1: tb.text(" ")
        
    final_imgs = get_deep_images(api_key, full, limit=3)
    if random.random() < RANDOM_PROMO_CHANCE and os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: final_imgs.append(ad.copy())
        
    blobs = [models.AppBskyEmbedImages.Image(alt=full['name'], image=bsky.upload_blob(image_to_bytes(i)).blob) for i in final_imgs[:4] if i]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
    save_json('history_games.json', (load_json('history_games.json', []) + [full['id']])[-2000:])

def main():
    logger.info("--- 🚀 START ---")
    raw_key, anth_key = os.environ.get("RAWG_API_KEY"), os.environ.get("ANTHROPIC_API_KEY")
    handle, pwd = os.environ.get("BLUESKY_HANDLE"), os.environ.get("BLUESKY_PASSWORD")
    if not handle or not pwd: return
    try:
        bsky = Client(); bsky.login(handle, pwd)
        logger.info("Login Successful")
    except Exception as e:
        logger.error(f"Login Error: {e}"); return

    f, man, now = os.environ.get("FORCED_SLOT", ""), os.environ.get("IS_MANUAL") == "true", datetime.utcnow()
    slot_id = None
    if man and "Slot" in f:
        match = re.search(r'Slot\s*(\d+)', f)
        if match: slot_id = int(match.group(1))
    if slot_id is None: slot_id = SCHEDULE.get(now.weekday(), {}).get(now.hour)
    if not slot_id: return

    handlers = {
        1: lambda b: run_single_game(b, raw_key, anth_key, "nostalgic and cozy memory", "#Nostalgia"),
        9: lambda b: run_single_game(b, raw_key, anth_key, "surprising historical fact", "#RetroGaming"),
        4: lambda b: run_single_game(b, raw_key, anth_key, "spicy unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, raw_key, anth_key, "mysterious hidden gem", "#HiddenGem"),
        11: lambda b: run_single_game(b, raw_key, anth_key, "relaxing weekend morning", "#RetroGaming"),
        2: lambda b: run_single_game(b, raw_key, anth_key, "fast quick spotlight", "#ClassicGaming"),
        3: lambda b: run_rivalry(b, raw_key, anth_key),
        18: lambda b: run_rivalry(b, raw_key, anth_key),
        17: lambda b: run_single_game(b, raw_key, anth_key, "nerdy gameplay mechanics dive", "#RetroGaming"),
        8: lambda b: run_single_game(b, raw_key, anth_key, "tribute to the developers", "#RetroDev"),
        10: lambda b: run_single_game(b, raw_key, anth_key, "visual art direction focus", "#BoxArt"),
        12: lambda b: run_single_game(b, raw_key, anth_key, "Sunday playthrough", "#RetroGaming"),
        13: lambda b: run_single_game(b, raw_key, anth_key, "historical anniversary", "#OnThisDay", True),
        14: lambda b: run_single_game(b, raw_key, anth_key, "deep legacy impact", "#OnThisDay", True),
        15: lambda b: run_single_game(b, raw_key, anth_key, "historical release context", "#OnThisDay", True)
    }
    if slot_id in handlers: handlers[slot_id](bsky)
    logger.info("--- 🏁 END ---")

if __name__ == "__main__": main()
