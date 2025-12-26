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

FRANCHISE_MAP = {
    "ZELDA": "#LegendOfZelda", "MARIO": "#SuperMario", "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog", "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil", "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania", "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter", "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar", "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan",
    "EVERMORE": "#SecretOfEvermore", "CHRONO": "#ChronoTrigger"
}

RETRO_PLATFORMS = {
    167: "Sega Genesis", 79: "SNES", 24: "GBA", 27: "PS1", 15: "PS2", 
    83: "N64", 106: "Dreamcast", 80: "Xbox", 49: "NES", 105: "GameCube",
    109: "TurboGrafx-16", 117: "Sega 32X", 119: "Sega CD", 12: "Neo Geo", 43: "GBC"
}
RETRO_IDS_STR = ",".join(map(str, RETRO_PLATFORMS.keys()))
GENRES = {"Platformer": 83, "Shooter": 2, "RPG": 5, "Fighting": 6, "Racing": 1}

# Full 3-post-per-day schedule (21 unique slots)
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
    except Exception as e:
        logger.error(f"Failed to load {filename}: {e}")
    return default

def save_json(filename, data):
    try:
        with open(filename, 'w') as f: json.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save {filename}: {e}")

def download_image(url):
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

def clean_game_hashtag(game_name, existing_tags):
    upper = game_name.upper()
    for k, v in FRANCHISE_MAP.items():
        if k in upper: return v
    
    clean = re.sub(r'[^a-zA-Z0-9]', '', "".join(game_name.split(':')[0].split('-')[0].split()[:2]))
    tag = f"#{clean}"
    
    # Logic: Skip if > 20 chars, replace with #Nostalgia if not already present
    if len(tag) > 20:
        return "#Nostalgia" if "#Nostalgia" not in existing_tags else None
    return tag if len(clean) > 2 else None

def get_platform_tags(game_data):
    found = []
    for p in game_data.get('platforms', []):
        pid = p['platform']['id']
        if pid in RETRO_PLATFORMS:
            tag = f"#{RETRO_PLATFORMS[pid].replace(' ', '')}"
            if len(tag) <= 20: found.append(tag)
            break
    return found[:1] if found else ["#RetroGaming"]

def fetch_games_list(count=1, genre_id=None, dates=None):
    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&platforms={RETRO_IDS_STR}&page_size=40"
    if genre_id: url += f"&genres={genre_id}"
    if dates: url += f"&dates={dates}"
    try:
        resp = requests.get(url, timeout=10).json()
        results = resp.get('results', [])
        history = load_json('history_games.json', [])
        available = [g for g in results if g['id'] not in history]
        return random.sample(available, min(len(available), count)) if available else random.sample(results, min(len(results), count))
    except: return []

def deep_fetch_game(game_id):
    url = f"https://api.rawg.io/api/games/{game_id}?key={RAWG_API_KEY}"
    try: return requests.get(url, timeout=10).json()
    except: return None

# --- CORE HANDLERS ---

def run_rivalry(bsky):
    g_name, g_id = random.choice(list(GENRES.items()))
    games_basic = fetch_games_list(count=2, genre_id=g_id)
    if len(games_basic) < 2: return
    
    g1, g2 = deep_fetch_game(games_basic[0]['id']), deep_fetch_game(games_basic[1]['id'])
    
    p = (f"Compare '{g1['name']}' and '{g2['name']}' ({g_name}). Focus on why fans loved one over the other. "
         f"Ask a question to settle the debate. Keep under 120 chars. No hashtags.")
    
    msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    )
    text = msg.content[0].text.strip()
    
    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n")
    
    # Dynamic Hashtags
    tags = ["#Retro", "#RetroGaming", "#Rivalry"]
    t1 = clean_game_hashtag(g1['name'], tags)
    if t1: tags.append(t1)
    t2 = clean_game_hashtag(g2['name'], tags)
    if t2: tags.append(t2)
    
    tags = list(set(tags))
    for i, t in enumerate(tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(tags)-1: tb.text(" ")

    imgs = []
    c1, c2 = download_image(g1.get('background_image')), download_image(g2.get('background_image'))
    if c1 and c2: imgs.append(create_collage([c1, c2]))
    
    # Randomly sample from screenshots 5-10 if possible
    all_shots = g1.get('short_screenshots', []) + g2.get('short_screenshots', [])
    random.shuffle(all_shots)
    for shot in all_shots:
        if len(imgs) >= 3: break
        img = download_image(shot['image'])
        if img: imgs.append(img)

    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: imgs.append(ad.copy())

    blobs = [models.AppBskyEmbedImages.Image(alt="Versus", image=bsky.upload_blob(image_to_bytes(i)).blob) for i in imgs[:4]]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))

def run_single_game(bsky, theme, slot_tag, force_on_this_day=False):
    game = None
    custom_header = ""
    
    if force_on_this_day:
        now = datetime.now()
        # Attempt exact day check first with random retro years
        for _ in range(5):
            year = random.randint(1985, 2005)
            date_str = f"{year}-{now.strftime('%m-%d')}"
            results = fetch_games_list(count=1, dates=f"{date_str},{date_str}")
            if results: 
                game = results[0]
                custom_header = f"📅 On This Day in {year}\n\n"
                break
        # Fallback to current month if no exact day match found
        if not game:
            month_start = now.strftime('%Y-%m-01')
            month_end = now.strftime('%Y-%m-31') # RAWG handles 31 safely
            results = fetch_games_list(count=1, dates=f"1985-01-01,2005-12-31") # Broad retro range
            if results:
                game = results[0]
                rel = game.get('released', 'N/A')
                month_name = now.strftime('%B')
                year_rel = rel.split('-')[0] if '-' in rel else "the past"
                custom_header = f"🗓️ In {month_name}, {year_rel}\n\n"

    if not game:
        results = fetch_games_list(count=1)
        game = results[0] if results else None
    
    if not game: return
    full = deep_fetch_game(game['id'])
    name, r_date = full['name'], full.get('released', 'N/A')
    
    p = (f"Write a {theme} post about '{name}' on {full.get('platforms', [{}])[0].get('platform', {}).get('name')}. "
         f"Released: {r_date}. Focus on why it matters. MANDATORY: End with a question. "
         f"Under 110 chars. No hashtags. SAFETY: If obscure, talk about {full.get('genres', [{}])[0].get('name')} era.")
    
    msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=150, messages=[{"role": "user", "content": p}]
    )
    text = msg.content[0].text.strip().replace('"', '')

    tb = client_utils.TextBuilder()
    tb.text(f"{custom_header}{text}\n\n")
    
    tags = ["#Retro", "#RetroGaming", slot_tag] + get_platform_tags(full)
    game_tag = clean_game_hashtag(name, tags)
    if game_tag: tags.append(game_tag)
    
    tags = list(set(tags))
    for i, t in enumerate(tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(tags)-1: tb.text(" ")

    imgs = []
    bg = download_image(full.get('background_image'))
    if bg: imgs.append(bg)
    
    # Pick 2-3 random screenshots from the first 10
    shots = full.get('short_screenshots', [])[1:11]
    if shots:
        selected = random.sample(shots, min(len(shots), 2))
        for s in selected:
            s_img = download_image(s['image'])
            if s_img: imgs.append(s_img)
            
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: imgs.append(ad.copy())

    blobs = [models.AppBskyEmbedImages.Image(alt=name, image=bsky.upload_blob(image_to_bytes(i)).blob) for i in imgs[:4]]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
    save_json('history_games.json', (load_json('history_games.json', []) + [full['id']])[-2000:])

def main():
    logger.info("--- 🚀 START ---")
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
    except: logger.error("Auth Fail"); return

    f = os.environ.get("FORCED_SLOT", ""); man = os.environ.get("IS_MANUAL") == "true"; now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', f).group(1)) if man else SCHEDULE.get(now.weekday(), {}).get(now.hour)
    
    if not slot_id:
        logger.info("No slot scheduled for this hour.")
        return

    handlers = {
        1: lambda b: run_single_game(b, "nostalgic memory", "#Nostalgia"),
        9: lambda b: run_single_game(b, "cool historical fact", "#RetroGaming"),
        4: lambda b: run_single_game(b, "unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, "hidden gem", "#HiddenGem"),
        11: lambda b: run_single_game(b, "relaxing weekend morning", "#RetroGaming"),
        2: lambda b: run_single_game(b, "quick spotlight", "#ClassicGaming"),
        3: run_rivalry, 18: run_rivalry,
        17: lambda b: run_single_game(b, "gameplay mechanics deep dive", "#RetroGaming"),
        8: lambda b: run_single_game(b, "tribute to the developers", "#RetroDev"),
        10: lambda b: run_single_game(b, "visual style and art direction", "#BoxArt"),
        12: lambda b: run_single_game(b, "Sunday afternoon playthrough", "#RetroGaming"),
        13: lambda b: run_single_game(b, "anniversary", "#OnThisDay", True),
        14: lambda b: run_single_game(b, "legacy and impact", "#OnThisDay", True),
        15: lambda b: run_single_game(b, "historical release context", "#OnThisDay", True)
    }
    
    if slot_id in handlers:
        handlers[slot_id](bsky)
    
    logger.info("--- 🏁 END ---")

if __name__ == "__main__":
    main()
