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

# --- LOGGING SETUP (Comprehensive Diagnostic) ---
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

# --- AUTHORITY FRANCHISE MAP (Option B) ---
FRANCHISE_MAP = {
    "ZELDA": "#LegendOfZelda", "MARIO": "#SuperMario", "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog", "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil", "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania", "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter", "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar", "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan",
    "GODZILLA": "#Godzilla", "KUNIO": "#KunioKun", "NEKKETSU": "#KunioKun",
    "ACE COMBAT": "#AceCombat", "KINGDOM HEARTS": "#KingdomHearts"
}

RETRO_PLATFORMS = {
    167: "Sega Genesis", 79: "SNES", 24: "GBA", 27: "PS1", 15: "PS2", 
    83: "N64", 106: "Dreamcast", 80: "Xbox", 49: "NES", 105: "GameCube",
    109: "TurboGrafx-16", 117: "Sega 32X", 119: "Sega CD", 12: "Neo Geo", 43: "GBC"
}
RETRO_IDS_STR = ",".join(map(str, RETRO_PLATFORMS.keys()))
GENRES = {"Platformer": 83, "Shooter": 2, "RPG": 5, "Fighting": 6, "Racing": 1}

# 09:00, 15:00, 21:00 UTC Dispatcher
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
        resp = requests.get(url, timeout=12)
        return Image.open(BytesIO(resp.content)) if resp.status_code == 200 else None
    except: return None

def image_to_bytes(img):
    """Recursive compressor ensuring < 970KB."""
    quality = 85
    for i in range(5):
        buf = BytesIO()
        temp_img = img.convert("RGB")
        temp_img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) < 950000:
            logger.info(f"📸 Compressed: {len(data)/1024:.1f}KB (Q:{quality})")
            return data
        quality -= 15
    return data

def create_collage(images, grid=(2,1)):
    if not images: return None
    target_h = 600
    resized = [img.resize((int(target_h * (img.width/img.height)), target_h)) for img in images]
    if grid == (2,1):
        total_w = sum(i.width for i in resized)
        collage = Image.new('RGB', (total_w, target_h))
        x = 0
        for i in resized: collage.paste(i, (x,0)); x += i.width
        return collage
    elif grid == (2,2):
        sz = 600
        collage = Image.new('RGB', (sz*2, sz*2))
        for idx, img in enumerate(resized[:4]):
            m = min(img.width, img.height); l, t = (img.width-m)/2, (img.height-m)/2
            crop = img.crop((l, t, l+m, t+m)).resize((sz, sz))
            collage.paste(crop, ((idx%2)*sz, (idx//2)*sz))
        return collage
    return images[0]

# --- AUTHORITY LOGIC ---

def clean_game_hashtag(game_name):
    upper = game_name.upper()
    for k, v in FRANCHISE_MAP.items():
        if k in upper: return v
    clean = re.sub(r'[^a-zA-Z0-9]', '', "".join(game_name.split(':')[0].split('-')[0].split()[:2]))
    return f"#{clean}" if len(clean) > 2 else "#RetroGaming"

def get_platform_tags(game_data):
    found = []
    for p in game_data.get('platforms', []):
        pid = p['platform']['id']
        if pid in RETRO_PLATFORMS:
            found.append(f"#{RETRO_PLATFORMS[pid].replace(' ', '')}")
            break
    if not found:
        for p in game_data.get('platforms', []):
            if "PC" in p['platform']['name']: found.append("#PCGaming"); break
    return found[:1] if found else ["#RetroGaming"]

def deep_fetch_game(game_id):
    url = f"https://api.rawg.io/api/games/{game_id}?key={RAWG_API_KEY}"
    try:
        logger.info(f"💎 [DEEP FETCH] {url}")
        return requests.get(url, timeout=10).json()
    except: return None

def fetch_games_list(count=1, genre_id=None):
    used = load_json('history_games.json', [])
    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&ordering=-rating&page_size=40&platforms={RETRO_IDS_STR}"
    if genre_id: url += f"&genres={genre_id}"
    try:
        data = requests.get(url, timeout=10).json().get('results', [])
        valid = [g for g in data if g['id'] not in used]
        return random.sample(valid, min(count, len(valid))) if valid else []
    except: return []

# --- POSTING ENGINE ---

def post_with_retry(bsky, game_id, theme, slot_tag, custom_header=""):
    full = deep_fetch_game(game_id)
    if not full: return False
    
    name, genre, r_date = full['name'], ", ".join([g['name'] for g in full['genres'][:2]]), full.get('released', 'N/A')
    p_tags, g_tag = get_platform_tags(full), clean_game_hashtag(name)
    
    logger.info(f"📊 [METADATA] Game: {name} | Rating: {full.get('rating')}")

    for attempt in range(1, 4):
        p = (f"Write a {theme} post about '{name}' ({genre}) released {r_date}. "
             f"MANDATORY: End with a thought-provoking question for fans. Under 110 chars. No hashtags.")
        if attempt == 2: p = f"RETRY: Summarize {name} in one punchy sentence with a question. Max 70 chars."
        
        try:
            msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                model="claude-3-haiku-20240307", max_tokens=150, messages=[{"role": "user", "content": p}]
            )
            text = msg.content[0].text.strip().replace('"', '')
        except: text = f"Does {name} ({r_date[:4]}) still hold up today?"

        tb = client_utils.TextBuilder()
        tb.text(f"{custom_header}{text}\n\n")
        tags = list(set(["#Retro", "#RetroGaming", g_tag, slot_tag] + p_tags))
        for i, t in enumerate(tags):
            tb.tag(t, t.replace("#", ""))
            if i < len(tags)-1: tb.text(" ")

        if len(tb.build_text()) < 298:
            imgs = []
            bg_url = full.get('background_image')
            bg = download_image(bg_url)
            if bg: imgs.append(bg)
            
            for shot in full.get('short_screenshots', []):
                if len(imgs) >= 3: break
                s_url = shot.get('image')
                if s_url == bg_url: continue
                s_img = download_image(s_url)
                if s_img: imgs.append(s_img)
            
            if os.path.exists("images/promo_ad.jpg"):
                with Image.open("images/promo_ad.jpg") as ad: imgs.append(ad.copy())

            logger.info(f"📸 [IMAGE LOG] Final Count: {len(imgs)}")
            blobs = [models.AppBskyEmbedImages.Image(alt=f"{name}", image=bsky.upload_blob(image_to_bytes(i)).blob) for i in imgs[:4]]
            bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
            save_json('history_games.json', (load_json('history_games.json', []) + [game_id])[-2000:])
            return True
    return False

# --- SLOT HANDLERS ---

def run_on_this_day(bsky):
    m, d = datetime.now().month, datetime.now().day
    for _ in range(10):
        y = random.randint(1985, 2005)
        ds = f"{y}-{m:02d}-{d:02d}"
        try:
            r = requests.get(f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={ds},{ds}&platforms={RETRO_IDS_STR}").json()
            if r.get('results'):
                if post_with_retry(bsky, r['results'][0]['id'], "celebratory", "#OnThisDay", f"📅 On This Day in {y}\n\n"): return
        except: continue
    run_single_game(bsky, "hidden gem", "#HiddenGem")

def run_rivalry(bsky):
    g_name, g_id = random.choice(list(GENRES.items()))
    games = fetch_games_list(count=2, genre_id=g_id)
    if len(games) < 2: return
    t1, t2 = clean_game_hashtag(games[0]['name']), clean_game_hashtag(games[1]['name'])
    p = f"Compare {games[0]['name']} and {games[1]['name']} (both {g_name}). Under 120 chars. Ask fans to pick."
    text = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    ).content[0].text.strip()
    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n")
    tags = ["#Retro", "#RetroGaming", t1, t2, "#Rivalry"]
    for i, t in enumerate(tags):
        tb.tag(t, t.replace("#", "")); 
        if i < len(tags)-1: tb.text(" ")
    collage = create_collage([download_image(g['background_image']) for g in games], grid=(2,1))
    blobs = []
    if collage: blobs.append(models.AppBskyEmbedImages.Image(alt="Rivalry", image=bsky.upload_blob(image_to_bytes(collage)).blob))
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: blobs.append(models.AppBskyEmbedImages.Image(alt="Promo", image=bsky.upload_blob(image_to_bytes(ad.copy())).blob))
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs[:4]))

def run_elimination(bsky):
    g_name, g_id = random.choice(list(GENRES.items()))
    games = fetch_games_list(count=4, genre_id=g_id)
    if len(games) < 4: return
    lst = "".join([f"{idx+1}. {g['name']}\n" for idx, g in enumerate(games)])
    p = f"Ask: 'Delete one of these {g_name} classics forever. Which one goes?' Under 100 chars."
    text = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    ).content[0].text.strip()
    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n{lst}\n")
    tags = ["#Retro", "#RetroGaming", "#Nostalgia", "#Elimination"]
    for i, t in enumerate(tags):
        tb.tag(t, t.replace("#", "")); 
        if i < len(all_tags)-1: tb.text(" ")
    collage = create_collage([download_image(g['background_image']) for g in games], grid=(2,2))
    blobs = []
    if collage: blobs.append(models.AppBskyEmbedImages.Image(alt="Elimination", image=bsky.upload_blob(image_to_bytes(collage)).blob))
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: blobs.append(models.AppBskyEmbedImages.Image(alt="Promo", image=bsky.upload_blob(image_to_bytes(ad.copy())).blob))
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))

def run_single_game(bsky, theme, slot_tag):
    games = fetch_games_list(count=1)
    if games: post_with_retry(bsky, games[0]['id'], theme, slot_tag)

def main():
    logger.info("--- 🚀 NOSTALGIA BOT STARTING ---")
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
    except: logger.error("❌ Auth fail"); return

    f = os.environ.get("FORCED_SLOT", ""); man = os.environ.get("IS_MANUAL") == "true"; now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', f).group(1)) if man else SCHEDULE.get(now.weekday(), {}).get(now.hour)

    if not slot_id: return
    logger.info(f"🚀 Executing Slot {slot_id}")

    handlers = {
        1: lambda b: run_single_game(b, "nostalgic memory", "#Nostalgia"),
        2: lambda b: run_single_game(b, "fun trivia", "#FunFact"),
        3: run_rivalry, 4: lambda b: run_single_game(b, "unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, "obscure hidden gem", "#HiddenGem"),
        7: run_elimination, 8: lambda b: run_single_game(b, "fun fact", "#FunFact"),
        9: lambda b: run_single_game(b, "aesthetic visuals", "#PixelArt"),
        10: lambda b: run_single_game(b, "trivia", "#FunFact"),
        11: lambda b: run_single_game(b, "childhood memory", "#Nostalgia"),
        12: lambda b: run_single_game(b, "fun fact", "#FunFact"),
        13: run_on_this_day, 14: run_on_this_day,
        15: lambda b: run_single_game(b, "nostalgic memory", "#Nostalgia"),
        17: lambda b: run_single_game(b, "trivia", "#FunFact"),
        18: run_rivalry
    }
    if slot_id in handlers: handlers[slot_id](bsky)
    logger.info("--- 🏁 BOT RUN FINISHED ---")

if __name__ == "__main__": main()
