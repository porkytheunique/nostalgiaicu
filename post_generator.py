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
CURRENT_YEAR = 2026 

PLATFORM_PRIORITY = [49, 79, 167, 109, 12, 27, 83, 106, 15, 105, 80, 24, 43]

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
    p_ids = [p['platform']['id'] for p in game_data.get('platforms', [])]
    for priority_id in PLATFORM_PRIORITY:
        if priority_id in p_ids:
            return [f"#{RETRO_PLATFORMS[priority_id].replace(' ', '')}"]
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
    final_imgs, seen_urls = [], set()
    def add_url(url):
        if url and url not in seen_urls and len(final_imgs) < limit:
            img = download_image(url)
            if img: final_imgs.append(img); seen_urls.add(url)
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
    
    prompt = (f"Compare '{g1['name']}' and '{g2['name']}'. Be punchy. Must end with a 'Pick one' question. 200 chars max.")
    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=250, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace('"', '')

    tags = ["#Retro", "#RetroGaming", "#Rivalry"]
    for g in [g1, g2]:
        t = clean_game_hashtag(g['name'], tags)
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
        sc = get_deep_images(api_key, g, limit=5)
        if len(sc) > 1: final_imgs.append(sc[1])

    if random.random() < RANDOM_PROMO_CHANCE and os.path.exists("images/promo_ad.jpg"):
        with Image.open("images/promo_ad.jpg") as ad: final_imgs.append(ad.copy())

    blobs = [models.AppBskyEmbedImages.Image(alt="Rivalry", image=bsky.upload_blob(image_to_bytes(i)).blob) for i in final_imgs[:4] if i]
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))

def run_single_game(bsky, api_key, anthropic_key, theme_desc, slot_tag, force_on_this_day=False):
    game, header, now = None, "", datetime.now()
    matched_exactly = False

    if force_on_this_day:
        yr = random.randint(1985, 2005)
        d_str = f"{yr}-{now.strftime('%m-%d')}"
        res = fetch_games_list(api_key, count=1, dates=f"{d_str},{d_str}")
        if res:
            game, header, matched_exactly = res[0], f"📅 On This Day in {yr}\n\n", True
        else:
            m_name, yr_fb = now.strftime('%B'), random.randint(1985, 2005)
            res = fetch_games_list(api_key, count=1, dates=f"{yr_fb}-{now.strftime('%m')}-01,{yr_fb}-{now.strftime('%m')}-28")
            if res: game, header = res[0], f"🗓️ In {m_name}, {yr_fb}\n\n"
    
    if not game: game = (fetch_games_list(api_key, count=1) or [None])[0]
    if not game: return
    full = deep_fetch_game(api_key, game['id'])
    
    # --- Better Grounding Logic ---
    rel_str = full.get('released', 'Unknown')
    tone_hint = "Speak about this game's legacy generally."
    if rel_str != 'Unknown':
        try:
            r_y, r_m, r_d = map(int, rel_str.split('-'))
            age = CURRENT_YEAR - r_y
            if matched_exactly and now.month == r_m and now.day == r_d:
                tone_hint = f"Celebrate its EXACT {age}th anniversary today! Be excited."
            elif now.month == r_m:
                tone_hint = f"It's the anniversary month! Mention it turns {age} this year."
            else:
                tone_hint = f"Looking back at this {r_y} classic (now {age} years old)."
        except: pass

    logger.info(f"🎮 {slot_tag} | {full['name']} | Tone: {tone_hint}")

    prompt = (f"Write a {theme_desc} post about '{full['name']}'. "
              f"Fact: {tone_hint}. Current Year: {CURRENT_YEAR}. "
              f"Rules: Hook, Detail, Question. Max 220 chars. Do NOT lie about dates.")

    msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
        model="claude-3-haiku-20240307", max_tokens=250, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace('"', '')
    
    tags = ["#Retro", "#RetroGaming", slot_tag] + get_platform_tags(full)
    gtag = clean_game_hashtag(full['name'], tags)
    if gtag: tags.append(gtag)
    unique_tags = list(dict.fromkeys(tags))

    final_body = f"{header}{text}"
    if len(final_body) > 250: final_body = final_body[:245].rsplit('.', 1)[0] + "."

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
    rk, ak = os.environ.get("RAWG_API_KEY"), os.environ.get("ANTHROPIC_API_KEY")
    h, p = os.environ.get("BLUESKY_HANDLE"), os.environ.get("BLUESKY_PASSWORD")
    if not h or not p: return
    try:
        bsky = Client(); bsky.login(h, p)
        logger.info("Login Successful")
    except Exception as e:
        logger.error(f"Login Error: {e}"); return

    f, m, n = os.environ.get("FORCED_SLOT", ""), os.environ.get("IS_MANUAL") == "true", datetime.utcnow()
    slot_id = None
    if m and "Slot" in f:
        match = re.search(r'Slot\s*(\d+)', f)
        if match: slot_id = int(match.group(1))
    if slot_id is None: slot_id = SCHEDULE.get(n.weekday(), {}).get(n.hour)
    if not slot_id: return

    handlers = {
        1: lambda b: run_single_game(b, rk, ak, "nostalgic and cozy memory", "#Nostalgia"),
        9: lambda b: run_single_game(b, rk, ak, "surprising historical fact", "#RetroGaming"),
        4: lambda b: run_single_game(b, rk, ak, "spicy unpopular opinion", "#UnpopularOpinion"),
        6: lambda b: run_single_game(b, rk, ak, "mysterious hidden gem", "#HiddenGem"),
        11: lambda b: run_single_game(b, rk, ak, "relaxing weekend morning", "#RetroGaming"),
        2: lambda b: run_single_game(b, rk, ak, "fast quick spotlight", "#ClassicGaming"),
        3: lambda b: run_rivalry(b, rk, ak),
        18: lambda b: run_rivalry(b, rk, ak),
        17: lambda b: run_single_game(b, rk, ak, "nerdy gameplay mechanics dive", "#RetroGaming"),
        8: lambda b: run_single_game(b, rk, ak, "tribute to the developers", "#RetroDev"),
        10: lambda b: run_single_game(b, rk, ak, "visual art direction focus", "#BoxArt"),
        12: lambda b: run_single_game(b, rk, ak, "Sunday playthrough", "#RetroGaming"),
        13: lambda b: run_single_game(b, rk, ak, "anniversary", "#OnThisDay", True),
        14: lambda b: run_single_game(b, rk, ak, "legacy impact", "#OnThisDay", True),
        15: lambda b: run_single_game(b, rk, ak, "historical release context", "#OnThisDay", True)
    }
    if slot_id in handlers: handlers[slot_id](bsky)
    logger.info("--- 🏁 END ---")

if __name__ == "__main__": main()
