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
    clean = re.sub(r'[^a-zA-Z0-9]', '', "".join(game_name.split(':')[0].split('-')[0].split()[:2]))
    tag = f"#{clean}"
    if len(tag) > 20 or len(clean) < 2:
        return "#Nostalgia" if "#Nostalgia" not in current_tags else None
    return tag

def get_platform_tags(game_data):
    found = []
    for p in game_data.get('platforms', []):
        pid = p['platform']['id']
        if pid in RETRO_PLATFORMS:
            tag = f"#{RETRO_PLATFORMS[pid].replace(' ', '')}"
            if len(tag) <= 20: found.append(tag)
            break
    return found[:1] if found else ["#RetroGaming"]

def fetch_games_list(api_key, count=1, genre_id=None, dates=None):
    url = f"https://api.rawg.io/api/games?key={api_key}&platforms={RETRO_IDS_STR}&page_size=40"
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

# --- CORE HANDLERS ---

def run_rivalry(bsky, api_key, anthropic_key):
    g_name, g_id = random.choice(list(GENRES.items()))
    games_basic = fetch_games_list(api_key, count=2, genre_id=g_id)
    if len(games_basic) < 2: return
    g1, g2 = deep_fetch_game(api_key, games_basic[0]['id']), deep_fetch_game(api_key, games_basic[1]['id'])
    
    p = (f"Compare '{g1['name']}' and '{g2['name']}' ({g_name}). Briefly explain the rivalry or difference. "
         f"Ask followers to pick a side. Limit 120 chars. No hashtags.")
    
    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    )
    text = msg.content[0].text.strip().replace('"', '')
    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n")
    tags = ["#Retro", "#RetroGaming", "#Rivalry"]
    for g in [g1, g2]:
        t = clean_game_hashtag(g['name'], tags)
        if t: tags.append(t)
    unique_tags = list(dict.fromkeys(tags))
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(unique_tags)-1: tb.text(" ")
    imgs = []
    c1, c2 = download_image(g1.get('background_image')), download_image(g2.get('background_image'))
    if c1 and c2: imgs.append(create_collage([c1, c2]))
    all_shots = g1.get('short_screenshots', [])[1:6] + g2.get('short_screenshots', [])[1:6]
    random.shuffle(all_shots)
    for shot in all_shots:
        if len(imgs) >= 3: break
        img = download_image(shot['image'])
        if img: imgs.append(img)
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: imgs.append(ad.copy())
    blobs = [models.AppBskyEmbedImages.Image(alt="Versus", image=bsky.upload_blob(image_to_bytes(i)).blob) for i in imgs[:4]]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))

def run_single_game(bsky, api_key, anthropic_key, theme, slot_tag, force_on_this_day=False):
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
            m_name, yr_fallback = now.strftime('%B'), random.randint(1985, 2005)
            res = fetch_games_list(api_key, count=1, dates=f"{yr_fallback}-{now.strftime('%m')}-01,{yr_fallback}-{now.strftime('%m')}-28")
            if res: game, header = res[0], f"🗓️ In {m_name}, {yr_fallback}\n\n"
    
    if not game:
        res = fetch_games_list(api_key, count=1)
        game = res[0] if res else None
    
    if not game: return
    full = deep_fetch_game(api_key, game['id'])
    p = (f"Write a {theme} post about '{full['name']}' ({full.get('released', 'N/A')}). "
         f"Include a question for engagement. Max 110 chars. No hashtags. "
         f"Safety: If unfamiliar, focus on the {full.get('genres', [{}])[0].get('name', 'Retro')} era.")
    
    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=150, messages=[{"role": "user", "content": p}]
    )
    text = msg.content[0].text.strip().replace('"', '')
    tb = client_utils.TextBuilder()
    tb.text(f"{header}{text}\n\n")
    tags = ["#Retro", "#RetroGaming", slot_tag] + get_platform_tags(full)
    gtag = clean_game_hashtag(full['name'], tags)
    if gtag: tags.append(gtag)
    unique_tags = list(dict.fromkeys(tags))
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(unique_tags)-1: tb.text(" ")
    imgs = [download_image(full.get('background_image'))] if full.get('background_image') else []
    shots = full.get('short_screenshots', [])[1:11]
    if shots:
        selected = random.sample(shots, min(len(shots), 2))
        for s in selected:
            s_img = download_image(s['image'])
            if s_img: imgs.append(s_img)
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: imgs.append(ad.copy())
    blobs = [models.AppBskyEmbedImages.Image(alt=full['name'], image=bsky.upload_blob(image_to_bytes(i)).blob) for i in imgs[:4] if i]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
    save_json('history_games.json', (load_json('history_games.json', []) + [full['id']])[-2000:])

def main():
    logger.info("--- 🚀 START ---")
    
    # LOAD ENVIRONMENT VARIABLES INSIDE MAIN
    rawg_key = os.environ.get("RAWG_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_PASSWORD")

    if not handle or not password:
        logger.error(f"Credentials Check -> Handle: {'OK' if handle else 'MISSING'}, Pwd: {'OK' if password else 'MISSING'}")
        return

    try:
        bsky = Client()
        bsky.login(handle, password)
        logger.info("Login Successful")
    except Exception as e:
        logger.error(f"Bluesky Login Error: {e}")
        return

    f = os.environ.get("FORCED_SLOT", "")
    man = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    
    slot_id = None
    if man and f and "Slot" in f:
        match = re.search(r'Slot\s*(\d+)', f)
        if match: 
            slot_id = int(match.group(1))
            logger.info(f"Manual Override: Executing Slot {slot_id}")
    
    if slot_id is None:
        slot_id = SCHEDULE.get(now.weekday(), {}).get(now.hour)
    
    if not slot_id:
        logger.info(f"No slot scheduled for Hour {now.hour}")
        return

    handlers = {
        1: lambda b: run_single_game(b, rawg_key, anthropic_key, "nostalgic memory", "#Nostalgia"),
        9: lambda b: run_single_game(b, rawg_key, anthropic_key, "cool historical fact", "#RetroGaming"),
        4: lambda b: run_single_game(b, rawg_key, anthropic_key, "unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, rawg_key, anthropic_key, "hidden gem", "#HiddenGem"),
        11: lambda b: run_single_game(b, rawg_key, anthropic_key, "relaxing weekend morning", "#RetroGaming"),
        2: lambda b: run_single_game(b, rawg_key, anthropic_key, "quick spotlight", "#ClassicGaming"),
        3: lambda b: run_rivalry(b, rawg_key, anthropic_key),
        18: lambda b: run_rivalry(b, rawg_key, anthropic_key),
        17: lambda b: run_single_game(b, rawg_key, anthropic_key, "gameplay mechanics deep dive", "#RetroGaming"),
        8: lambda b: run_single_game(b, rawg_key, anthropic_key, "tribute to the developers", "#RetroDev"),
        10: lambda b: run_single_game(b, rawg_key, anthropic_key, "visual style and art direction", "#BoxArt"),
        12: lambda b: run_single_game(b, rawg_key, anthropic_key, "Sunday afternoon playthrough", "#RetroGaming"),
        13: lambda b: run_single_game(b, rawg_key, anthropic_key, "anniversary", "#OnThisDay", True),
        14: lambda b: run_single_game(b, rawg_key, anthropic_key, "legacy and impact", "#OnThisDay", True),
        15: lambda b: run_single_game(b, rawg_key, anthropic_key, "historical release context", "#OnThisDay", True)
    }
    
    if slot_id in handlers:
        handlers[slot_id](bsky)
    
    logger.info("--- 🏁 END ---")

if __name__ == "__main__":
    main()
