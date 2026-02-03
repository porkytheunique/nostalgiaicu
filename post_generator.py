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
    # 1. Check Franchise Map
    for k, v in FRANCHISE_MAP.items():
        if k in upper: return v
    
    # 2. Smart Slugger: Remove special chars, join words, max 3 words
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', game_name)
    words = clean_name.split()[:3]
    tag = "#" + "".join(word.capitalize() for word in words)
    
    if len(tag) > 25 or len(tag) < 3:
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
    # Dig deeper by picking a random page between 1 and 10
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

    def add_from_url(url):
        if url and url not in seen_urls and len(final_imgs) < limit:
            img = download_image(url)
            if img:
                final_imgs.append(img)
                seen_urls.add(url)

    add_from_url(full_game_obj.get('background_image_additional'))
    add_from_url(full_game_obj.get('background_image'))
    
    try:
        ss_url = f"https://api.rawg.io/api/games/{full_game_obj['id']}/screenshots?key={api_key}"
        res = requests.get(ss_url, timeout=10).json().get('results', [])
        for s in res:
            add_from_url(s.get('image'))
            if len(final_imgs) >= limit: break
    except: pass

    if len(final_imgs) < limit:
        for s in full_game_obj.get('short_screenshots', []):
            add_from_url(s.get('image'))
            if len(final_imgs) >= limit: break
            
    return final_imgs

# --- CORE HANDLERS ---

def run_rivalry(bsky, api_key, anthropic_key):
    g_name, g_id = random.choice(list(GENRES.items()))
    games_basic = fetch_games_list(api_key, count=2, genre_id=g_id)
    if len(games_basic) < 2: return
    g1, g2 = deep_fetch_game(api_key, games_basic[0]['id']), deep_fetch_game(api_key, games_basic[1]['id'])
    
    logger.info(f"⚔️ Rivalry: {g1['name']} vs {g2['name']}")
    
    prompt = (f"Compare '{g1['name']}' and '{g2['name']}'. "
              f"Act like a retro gaming enthusiast. Briefly state what made each special, "
              f"then end with a punchy 'Pick one' question. Limit: 200 chars. No hashtags.")

    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=200, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace('"', '')

    tags = ["#Retro", "#RetroGaming", "#Rivalry"]
    for g in [g1, g2]:
        t = clean_game_hashtag(g['name'], tags)
        if t: tags.append(t)
    unique_tags = list(dict.fromkeys(tags))

    tb = client_utils.TextBuilder()
    tb.text(f"{text}\n\n")
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(unique_tags)-1: tb.text(" ")

    final_imgs = []
    c1 = download_image(g1.get('background_image_additional') or g1.get('background_image'))
    c2 = download_image(g2.get('background_image_additional') or g2.get('background_image'))
    if c1 and c2: final_imgs.append(create_collage([c1, c2]))
    
    g1_screens = get_deep_images(api_key, g1, limit=5)
    if len(g1_screens) > 1: final_imgs.append(g1_screens[1])
    g2_screens = get_deep_images(api_key, g2, limit=5)
    if len(g2_screens) > 1: final_imgs.append(g2_screens[1])

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
            m_name, yr_fallback = now.strftime('%B'), random.randint(1985, 2005)
            res = fetch_games_list(api_key, count=1, dates=f"{yr_fallback}-{now.strftime('%m')}-01,{yr_fallback}-{now.strftime('%m')}-28")
            if res: game, header = res[0], f"🗓️ In {m_name}, {yr_fallback}\n\n"
    
    if not game:
        res = fetch_games_list(api_key, count=1)
        game = res[0] if res else None
    
    if not game: return
    full = deep_fetch_game(api_key, game['id'])
    logger.info(f"🎮 Slot: {slot_tag} | Game: {full['name']}")

    # Enhanced Voice-specific prompts
    prompt = (f"Write a {theme_desc} post about '{full['name']}'. "
              f"Structure: 1. A catchy hook. 2. A brief, personal-sounding detail. 3. A question for the readers. "
              f"Strict limit: 220 characters. Do not use hashtags. Be evocative and nostalgic.")

    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=250, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace('"', '')
    
    tags = ["#Retro", "#RetroGaming", slot_tag] + get_platform_tags(full)
    gtag = clean_game_hashtag(full['name'], tags)
    if gtag: tags.append(gtag)
    unique_tags = list(dict.fromkeys(tags))

    # Safety Truncation: Slices at last space to avoid mid-word cutoff if over 250
    final_body = f"{header}{text}"
    if len(final_body) > 250:
        final_body = final_body[:247].rsplit(' ', 1)[0] + "..."
    
    tb = client_utils.TextBuilder()
    tb.text(f"{final_body}\n\n")
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(unique_tags)-1: tb.text(" ")
        
    final_imgs = get_deep_images(api_key, full, limit=3)
    if random.random() < RANDOM_PROMO_CHANCE and os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: final_imgs.append(ad.copy())
        
    logger.info(f"📸 Images prepared: {len(final_imgs)}")
    blobs = [models.AppBskyEmbedImages.Image(alt=full['name'], image=bsky.upload_blob(image_to_bytes(i)).blob) for i in final_imgs[:4] if i]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
    save_json('history_games.json', (load_json('history_games.json', []) + [full['id']])[-2000:])

def main():
    logger.info("--- 🚀 START ---")
    rawg_key = os.environ.get("RAWG_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_PASSWORD")

    if not handle or not password: return

    try:
        bsky = Client()
        bsky.login(handle, password)
        logger.info("Login Successful")
    except Exception as e:
        logger.error(f"Login Error: {e}")
        return

    f = os.environ.get("FORCED_SLOT", "")
    man = os.environ.get("IS_MANUAL") == "true"
    now = datetime.utcnow()
    
    slot_id = None
    if man and f and "Slot" in f:
        match = re.search(r'Slot\s*(\d+)', f)
        if match: slot_id = int(match.group(1))
    
    if slot_id is None:
        slot_id = SCHEDULE.get(now.weekday(), {}).get(now.hour)
    
    if not slot_id:
        logger.info(f"No slot for Hour {now.hour}")
        return

    # Descriptions now include a "voice" instruction
    handlers = {
        1: lambda b: run_single_game(b, raw_key, anth_key, "nostalgic and cozy memory", "#Nostalgia"),
        9: lambda b: run_single_game(b, raw_key, anth_key, "surprising and cool historical fact", "#RetroGaming"),
        4: lambda b: run_single_game(b, raw_key, anth_key, "spicy and controversial unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, raw_key, anth_key, "mysterious 'have you heard of this' hidden gem", "#HiddenGem"),
        11: lambda b: run_single_game(b, raw_key, anth_key, "lazy, relaxing weekend morning", "#RetroGaming"),
        2: lambda b: run_single_game(b, raw_key, anth_key, "fast-paced quick spotlight", "#ClassicGaming"),
        3: lambda b: run_rivalry(b, raw_key, anth_key),
        18: lambda b: run_rivalry(b, raw_key, anth_key),
        17: lambda b: run_single_game(b, raw_key, anth_key, "technical and nerdy gameplay mechanics deep dive", "#RetroGaming"),
        8: lambda b: run_single_game(b, raw_key, anth_key, "heartfelt tribute to the creative developers", "#RetroDev"),
        10: lambda b: run_single_game(b, raw_key, anth_key, "visually focused art direction and box art", "#BoxArt"),
        12: lambda b: run_single_game(b, raw_key, anth_key, "chilled Sunday afternoon playthrough", "#RetroGaming"),
        13: lambda b: run_single_game(b, raw_key, anth_key, "historical anniversary", "#OnThisDay", True),
        14: lambda b: run_single_game(b, raw_key, anth_key, "deep legacy and cultural impact", "#OnThisDay", True),
        15: lambda b: run_single_game(b, raw_key, anth_key, "context-heavy historical release", "#OnThisDay", True)
    }
    
    # Note: Passed rawg_key and anthropic_key aliases for brevity in handlers dict
    raw_key, anth_key = rawg_key, anthropic_key

    if slot_id in handlers:
        handlers[slot_id](bsky)
    
    logger.info("--- 🏁 END ---")

if __name__ == "__main__":
    main()
