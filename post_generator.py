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
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan"
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
    elif grid == (2,2):
        target_size = 600
        collage = Image.new('RGB', (target_size*2, target_size*2))
        for idx, img in enumerate(resized_imgs[:4]):
            min_dim = min(img.width, img.height)
            left, top = (img.width - min_dim)/2, (img.height - min_dim)/2
            img = img.crop((left, top, left+min_dim, top+min_dim)).resize((target_size, target_size))
            collage.paste(img, ((idx % 2) * target_size, (idx // 2) * target_size))
        return collage
    return images[0]

# --- AUTHORITY LOGIC ---

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
    return requests.get(url).json()

def fetch_games_list(count=1, genre_id=None):
    used = load_json('history_games.json', [])
    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&ordering=-rating&page_size=40&platforms={RETRO_IDS_STR}"
    if genre_id: url += f"&genres={genre_id}"
    resp = requests.get(url).json().get('results', [])
    valid = [g for g in resp if g['id'] not in used]
    return random.sample(valid, min(count, len(valid))) if valid else []

# --- POSTING SYSTEM ---

def post_with_retry(bsky, game_id, theme, custom_header=""):
    full_game = deep_fetch_game(game_id)
    name, genre = full_game['name'], ", ".join([g['name'] for g in full_game['genres'][:2]])
    r_date = full_game.get('released', 'N/A')
    p_tags = get_platform_tags(full_game, 1)
    g_tag = clean_game_hashtag(name)
    
    logger.info(f"📊 Processing: {name}")

    for attempt in range(1, 4):
        p = f"Write a {theme} post about '{name}' ({genre}) released {r_date}. Under 100 chars. No hashtags."
        if attempt == 2: p = f"RETRY: Summarize {name} in one short sentence. Max 60 chars."
        
        if attempt == 3: text = f"The {genre} classic {name} ({r_date[:4] if len(r_date)>4 else r_date})."
        else:
            msg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                model="claude-3-haiku-20240307", max_tokens=150, messages=[{"role": "user", "content": p}]
            )
            text = msg.content[0].text.strip().replace('"', '')

        tb = client_utils.TextBuilder()
        tb.text(f"{custom_header}{text}\n\n")
        all_tags = list(set(["#Retro", "#RetroGaming", g_tag] + p_tags))
        for i, tag in enumerate(all_tags):
            tb.tag(tag, tag.replace("#", ""))
            if i < len(all_tags) - 1: tb.text(" ")

        if len(tb.build_text()) < 298:
            imgs = []
            main_img = download_image(full_game['background_image'])
            if main_img: imgs.append(main_img)
            
            screens = 0
            for shot in full_game.get('short_screenshots', []):
                if screens >= 2: break
                if shot['image'] == full_game['background_image']: continue
                s_img = download_image(shot['image'])
                if s_img: imgs.append(s_img); screens += 1
            
            if os.path.exists("images/promo_ad.jpg"):
                with Image.open("images/promo_ad.jpg") as ad:
                    imgs.append(ad.copy()) # Copy ensures file isn't closed prematurely

            blobs = []
            for img in imgs[:4]:
                blob = bsky.upload_blob(image_to_bytes(img)).blob
                blobs.append(models.AppBskyEmbedImages.Image(alt=f"{name} Screenshot", image=blob))
            
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
    
    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n")
    all_tags = ["#Retro", "#RetroGaming", t1, t2, "#Rivalry"]
    for i, tag in enumerate(all_tags):
        tb.tag(tag, tag.replace("#", "")); 
        if i < len(all_tags) - 1: tb.text(" ")

    collage_imgs = []
    for g in games:
        img = download_image(g['background_image'])
        if img: collage_imgs.append(img)
    
    collage = create_collage(collage_imgs, grid=(2,1))
    
    blobs = []
    if collage:
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        blobs.append(models.AppBskyEmbedImages.Image(alt="Rivalry Collage", image=blob))
    
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad:
            blob = bsky.upload_blob(image_to_bytes(ad.copy())).blob
            blobs.append(models.AppBskyEmbedImages.Image(alt="Promo", image=blob))

    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs[:4]))

def run_elimination(bsky):
    g_name, g_id = random.choice(list(GENRES.items()))
    games = fetch_games_list(count=4, genre_id=g_id)
    if len(games) < 4: return
    
    game_list_text = ""
    for idx, g in enumerate(games): game_list_text += f"{idx+1}. {g['name']}\n"
    
    p = f"Ask: 'Delete one of these {g_name} classics forever. Which one goes?' Under 100 chars. No hashtags."
    text = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": p}]
    ).content[0].text.strip()
    
    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n{game_list_text}\n")
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming"); tb.text(" "); tb.tag("#Nostalgia", "Nostalgia")

    pil_imgs = [download_image(g['background_image']) for g in games]
    collage = create_collage([p for p in pil_imgs if p], grid=(2,2))
    
    blobs = []
    if collage:
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        blobs.append(models.AppBskyEmbedImages.Image(alt="Elimination Collage", image=blob))
    
    if os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad:
            blob = bsky.upload_blob(image_to_bytes(ad.copy())).blob
            blobs.append(models.AppBskyEmbedImages.Image(alt="Promo", image=blob))

    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))

def run_single_game(bsky, theme):
    games = fetch_games_list(count=1)
    if games: post_with_retry(bsky, games[0]['id'], theme)

def main():
    logger.info("--- 🚀 NOSTALGIA BOT STARTING ---")
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
    except Exception as e:
        logger.error(f"❌ [AUTH FAIL]: {e}"); return

    forced = os.environ.get("FORCED_SLOT", "")
    manual = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    slot_id = int(re.search(r'Slot\s*(\d+)', forced).group(1)) if manual else SCHEDULE.get(now.weekday(), {}).get(now.hour)

    if not slot_id: return
    logger.info(f"🚀 Executing Slot {slot_id}")

    handlers = {
        4: lambda b: run_single_game(b, "unpopular opinion"),
        6: lambda b: run_single_game(b, "hidden gem"),
        7: run_elimination,
        3: run_rivalry, 18: run_rivalry,
        13: run_on_this_day, 14: run_on_this_day,
        9: lambda b: run_single_game(b, "aesthetic pixel art visuals"),
        11: lambda b: run_single_game(b, "nostalgic childhood memory")
    }
    
    if slot_id in handlers: handlers[slot_id](bsky)
    logger.info("--- 🏁 BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
