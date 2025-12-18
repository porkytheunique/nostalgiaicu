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

# --- CONSTANTS & SCHEDULE ---
SCHEDULE = {
    0: {9: 1, 15: 2, 21: 13},   # Mon: Ad, Generic Q, On This Day
    1: {9: 9, 15: 3, 21: 14},   # Tue: Aesthetic, Rivalry, Fact
    2: {9: 4, 15: 17, 21: 13},  # Wed: Unpopular, Generic Q, On This Day
    3: {9: 6, 15: 18, 21: 14},  # Thu: Obscure, Rivalry, Fact
    4: {9: 7, 15: 8, 21: 13},   # Fri: Elimination, Generic Q, On This Day
    5: {9: 9, 15: 10, 21: 15},  # Sat: Aesthetic, Fact, Memory
    6: {9: 11, 15: 12, 21: 13}  # Sun: Memory, Fact, On This Day
}

RETRO_PLATFORM_IDS = "27,15,83,79,24,167,80,106,49,105,109,107,12,119,117,43"
PIXEL_PLATFORMS_IDS = "79,24,167,49,109,12,43"

GENRES = {
    "Platformer": 83,
    "Shooter": 2,
    "RPG": 5,
    "Fighting": 6,
    "Racing": 1
}

# --- MONDAY FEATURE DEFINITIONS ---
MONDAY_FEATURES = [
    {"name": "Magazine Library", "url": "https://www.nostalgia.icu/library/", "img": "images/ad_library.jpg", "texts": ["Flip through history! 📖 Thousands of classic gaming magazines preserved.", "Revisit the golden era of gaming journalism. 📰"], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Library"]},
    {"name": "Retro Media Player", "url": "https://www.nostalgia.icu/media/", "img": "images/ad_media.jpg", "texts": ["Tune in to the past! 📺 Vintage cartoons and commercials streaming now.", "Your portal to broadcast history. 📡"], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#RetroTV"]},
    {"name": "Retro Radio", "url": "https://www.nostalgia.icu/radio/", "img": "images/ad_radio.jpg", "texts": ["Vibe to the classics. 📻 24/7 Retro Radio playing the best VGM.", "The soundtrack of your childhood is live. 🎧"], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Radio"]},
    {"name": "System Advisor", "url": "https://www.nostalgia.icu/advisor/", "img": "images/ad_advisor.jpg", "texts": ["Stuck in a game? 🤖 Chat with our System Curator.", "Find the value of your old carts. 💡"], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Advisor"]},
    {"name": "Nostalgia Quest", "url": "https://www.nostalgia.icu/quest/", "img": "images/ad_quest.jpg", "texts": ["Enter the dungeon! ⚔️ Join the Nostalgia Quest.", "Earn street cred. 🛡️ Prove your mastery."], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Quest"]},
    {"name": "Gaming History", "url": "https://www.nostalgia.icu/history/", "img": "images/ad_history.jpg", "texts": ["On this day... 📅 Check which legends were released today.", "Travel back in time. ⏳ See what happened today in gaming."], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#GamingHistory"]},
    {"name": "Game Database", "url": "https://www.nostalgia.icu/database/", "img": "images/ad_database.jpg", "texts": ["The ultimate index. 💾 Search our massive Retro Database.", "Need info? 💽 Our Database has the data."], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#GameDB"]},
    {"name": "Pixel Challenge", "url": "https://www.nostalgia.icu/quest/", "img": "images/ad_challenge.jpg", "texts": ["Test your eyes! 👀 Can you identify the game from a few pixels?", "Take the Daily Pixel Challenge. 🧩"], "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#PixelArt"]}
]

GENERIC_TOPICS = ["Memory Cards", "Cheat Codes", "Couch Co-op", "Game Over Screens", "Demo Discs", "Instruction Manuals", "Boss Fights", "Soundtracks", "Loading Screens", "Video Rental Stores", "Strategy Guides", "Save Points", "Easter Eggs", "Start Menus"]

PLATFORM_TAGS = {
    "PlayStation": "#PS1", "PlayStation 2": "#PS2", "PlayStation 3": "#PS3",
    "Xbox": "#Xbox", "Xbox 360": "#Xbox360",
    "SNES": "#SNES", "NES": "#NES", "Nintendo 64": "#N64", "GameCube": "#GameCube",
    "Game Boy": "#GameBoy", "Game Boy Advance": "#GBA", "Game Boy Color": "#GameBoyColor",
    "Sega Genesis": "#SegaGenesis", "Dreamcast": "#Dreamcast", "Sega Saturn": "#SegaSaturn",
    "Sega CD": "#SegaCD", "Sega 32X": "#Sega32X",
    "Neo Geo": "#NeoGeo", "TurboGrafx-16": "#TurboGrafx16", "PC": "#PCGaming"
}

CONSOLE_IMAGES = ["images/console_nes.jpg", "images/console_snes.jpg", "images/console_n64.jpg", "images/console_gamecube.jpg", "images/console_ps1.jpg", "images/console_ps2.jpg", "images/console_xbox.jpg", "images/console_genesis.jpg", "images/console_dreamcast.jpg", "images/console_saturn.jpg", "images/console_turbografx.jpg", "images/console_neogeo.jpg", "images/console_segacd.jpg", "images/console_32x.jpg", "images/console_gbc.jpg"]

FACT_INTROS = ["Did you know?", "Retro Fact:", "Gaming History:", "Fun Fact:", "Trivia Time:"]

RIVAL_PAIRS = [
    {"p1": "27", "p2": "83", "t1": "#PS1", "t2": "#N64"},
    {"p1": "15", "p2": "80", "t1": "#PS2", "t2": "#Xbox"},
    {"p1": "79", "p2": "167", "t1": "#SNES", "t2": "#Sega"},
    {"p1": "106", "p2": "15", "t1": "#Dreamcast", "t2": "#PS2"}
]

# --- HELPERS ---

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f: return json.load(f)
        except: return default
    return default

def save_json(filename, data):
    with open(filename, 'w') as f: json.dump(data, f)

def get_claude_text(prompt):
    if not ANTHROPIC_API_KEY: return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-3-haiku-20240307", max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        text = text.replace("#", "").replace('"', '').replace("'", "")
        return text
    except Exception as e:
        logger.error(f"Claude Error: {e}")
        return None

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

def get_distinct_screenshot(game, exclude_url=None):
    screens = game.get('short_screenshots', [])
    if not screens: return None
    for shot in screens:
        if shot['image'] != exclude_url:
            return shot['image']
    return screens[0]['image']

def get_genre_name(game_data):
    genres = game_data.get('genres', [])
    if genres:
        return ", ".join([g['name'] for g in genres[:2]])
    return "Retro Game"

def create_collage(images, grid=(2,1)):
    if not images: return None
    target_h = 600
    resized_imgs = []
    for img in images:
        aspect = img.width / img.height
        new_w = int(target_h * aspect)
        resized_imgs.append(img.resize((new_w, target_h)))

    if grid == (2,1):
        total_w = sum(i.width for i in resized_imgs)
        collage = Image.new('RGB', (total_w, target_h))
        x_off = 0
        for img in resized_imgs:
            collage.paste(img, (x_off, 0))
            x_off += img.width
        return collage
    elif grid == (2,2):
        target_size = 600
        collage = Image.new('RGB', (target_size*2, target_size*2))
        for idx, img in enumerate(resized_imgs[:4]):
            min_dim = min(img.width, img.height)
            left = (img.width - min_dim)/2
            top = (img.height - min_dim)/2
            img = img.crop((left, top, left+min_dim, top+min_dim)).resize((target_size, target_size))
            x = (idx % 2) * target_size
            y = (idx // 2) * target_size
            collage.paste(img, (x, y))
        return collage
    return images[0]

def clean_game_hashtag(game_name):
    words = game_name.split()
    short_name = "".join(words[:2])
    clean = re.sub(r'[^a-zA-Z0-9]', '', short_name)
    return f"#{clean}" if (clean and len(clean) > 2) else "#RetroGaming"

def get_platform_tags(game_data, limit=1):
    """
    PRIORITY TAGS: Retro consoles first. Only adds #PCGaming if no consoles exist.
    """
    found_tags = []
    has_console = False
    
    # 1. First Pass: Check for Retro Consoles
    for p in game_data.get('platforms', []):
        name = p['platform']['name']
        if "PC" not in name: # If it's anything but PC
            for key, val in PLATFORM_TAGS.items():
                if "PC" not in key and key in name:
                    found_tags.append(val)
                    has_console = True
                    break
    
    # 2. Second Pass: Only add PC if we didn't find a console
    if not has_console:
        for p in game_data.get('platforms', []):
            if "PC" in p['platform']['name']:
                found_tags.append("#PCGaming")
                break

    found_tags = list(set(found_tags))
    return found_tags[:limit] if found_tags else ["#RetroGaming"]

def fetch_games_from_rawg(count=1, platform_ids=None, genre_id=None):
    used_games = load_json('history_games.json', [])
    found_games = []
    platforms = platform_ids if platform_ids else RETRO_PLATFORM_IDS
    for _ in range(10): 
        if len(found_games) >= count: break
        page = random.randint(1, 100)
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&platforms={platforms}&ordering=-rating&page_size={count*2}&page={page}"
        if genre_id: url += f"&genres={genre_id}"
        try:
            data = requests.get(url).json()
            for cand in data.get('results', []):
                if cand['id'] not in used_games and cand['id'] not in [g['id'] for g in found_games]:
                    if cand.get('background_image'):
                        found_games.append(cand)
                        if len(found_games) == count: break
        except Exception as e: logger.error(f"RAWG Error: {e}")
    if found_games:
        used_games.extend([g['id'] for g in found_games])
        save_json('history_games.json', used_games[-2000:])
    return found_games

def fetch_on_this_day_game():
    now = datetime.now()
    month, day = now.month, now.day
    for _ in range(5):
        year = random.randint(1985, 2005)
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={year}-{month:02d}-{day:02d},{year}-{month:02d}-{day:02d}&ordering=-added&page_size=5"
        try:
            data = requests.get(url).json()
            results = data.get('results', [])
            if results:
                game = random.choice(results[:3])
                if game.get('background_image'):
                    full_details = requests.get(f"https://api.rawg.io/api/games/{game['id']}?key={RAWG_API_KEY}").json()
                    full_details['release_year'] = year 
                    return full_details
        except: pass
    return None

# --- SLOT HANDLERS ---

def run_slot_1_ad(bsky):
    history = load_json('history_ads.json', {'last_index': -1})
    idx = (history['last_index'] + 1) % len(MONDAY_FEATURES)
    feature = MONDAY_FEATURES[idx]
    tb = client_utils.TextBuilder()
    tb.text(random.choice(feature['texts']) + "\n\n🔗 Visit: ")
    tb.link(feature['url'], feature['url'])
    tb.text("\n\n")
    for tag in feature['tags']: tb.tag(tag, tag.replace("#", "")); tb.text(" ")
    if os.path.exists(feature['img']):
        with open(feature['img'], 'rb') as f:
            upload = bsky.upload_blob(f.read())
            embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=feature['name'], image=upload.blob)])
            bsky.send_post(tb, embed=embed)
            save_json('history_ads.json', {'last_index': idx})

def run_generic_q(bsky):
    used_q = load_json('history_questions.json', [])
    valid_imgs = [img for img in CONSOLE_IMAGES if os.path.exists(img)]
    mode = "console" if valid_imgs and random.random() > 0.5 else "topic"
    img_embed, console_tag = None, None

    if mode == "console":
        chosen_img = random.choice(valid_imgs)
        raw = chosen_img.replace("images/console_", "").replace(".jpg", "").upper()
        console_map = {"NES": ("NES", "#NES"), "SNES": ("SNES", "#SNES"), "N64": ("N64", "#N64"), "GAMECUBE": ("GameCube", "#GameCube"), "GENESIS": ("Genesis", "#SegaGenesis"), "SATURN": ("Saturn", "#SegaSaturn"), "DREAMCAST": ("Dreamcast", "#Dreamcast"), "PS1": ("PS1", "#PS1"), "PS2": ("PS2", "#PS2"), "XBOX": ("Xbox", "#Xbox"), "GBC": ("GBC", "#GameBoyColor"), "NEOGEO": ("Neo Geo", "#NeoGeo"), "TURBOGRAFX": ("TurboGrafx", "#TurboGrafx16")}
        c_info = next((v for k, v in console_map.items() if k in raw), ("Retro Console", "#RetroGaming"))
        console_tag = c_info[1]
        prompt = f"Write a short, nostalgic question about the {c_info[0]}. Under 110 characters. NO hashtags."
        with open(chosen_img, 'rb') as f:
            upload = bsky.upload_blob(f.read())
            img_embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=c_info[0], image=upload.blob)])
    else:
        topic = random.choice([t for t in GENERIC_TOPICS if t not in used_q[-5:]])
        prompt = f"Write a broad question for retro gamers about '{topic}'. Under 110 characters. NO hashtags."
        if valid_imgs:
            with open(random.choice(valid_imgs), 'rb') as f:
                upload = bsky.upload_blob(f.read())
                img_embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt="Retro Console", image=upload.blob)])
        used_q.append(topic); save_json('history_questions.json', used_q[-50:])

    text = get_claude_text(prompt) or "What's your take on this?"
    tb = client_utils.TextBuilder(); tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming")
    if console_tag: tb.text(" "); tb.tag(console_tag, console_tag.replace("#", ""))
    bsky.send_post(tb, embed=img_embed)

def run_rivalry(bsky):
    pair = random.choice(RIVAL_PAIRS)
    g1s, g2s = fetch_games_from_rawg(1, pair['p1']), fetch_games_from_rawg(1, pair['p2'])
    if not g1s or not g2s: return
    g1, g2 = g1s[0], g2s[0]
    prompt = f"Compare the {get_genre_name(g1)} game {g1['name']} and the {get_genre_name(g2)} game {g2['name']}. Under 110 characters. NO hashtags."
    text = get_claude_text(prompt) or f"{g1['name']} vs {g2['name']}."
    imgs = []
    i1, i2 = download_image(g1['background_image']), download_image(g2['background_image'])
    if i1 and i2:
        collage = create_collage([i1, i2], grid=(2,1))
        imgs.append(models.AppBskyEmbedImages.Image(alt="Rivalry", image=bsky.upload_blob(image_to_bytes(collage)).blob))
    for g in [g1, g2]:
        s_img = download_image(get_distinct_screenshot(g, g['background_image']))
        if s_img: imgs.append(models.AppBskyEmbedImages.Image(alt=g['name'], image=bsky.upload_blob(image_to_bytes(s_img)).blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f: imgs.append(models.AppBskyEmbedImages.Image(alt="Nostalgia", image=bsky.upload_blob(f.read()).blob))
    tb = client_utils.TextBuilder(); tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(pair['t1'], pair['t1'].replace("#", "")); tb.text(" "); tb.tag(pair['t2'], pair['t2'].replace("#", ""))
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs[:4]))

def run_single_game_post(bsky, slot_type):
    game_list = fetch_games_from_rawg(1, platform_ids=PIXEL_PLATFORMS_IDS if slot_type == "Aesthetic" else None)
    if not game_list: return
    game = game_list[0]
    genre = get_genre_name(game)
    configs = {"Unpopular": {"p": "unpopular opinion about difficulty/design", "t": "#UnpopularOpinion"}, "Obscure": {"p": "why it's a hidden gem", "t": "#HiddenGem"}, "Aesthetic": {"p": "praise pixel art visuals", "t": "#PixelArt"}, "Memory": {"p": "ask for a childhood memory", "t": "#Nostalgia"}}
    cfg = configs[slot_type]
    prompt = f"Write about '{game['name']}' (Genre: {genre}). Theme: {cfg['p']}. Keep it EXTREMELY BRIEF (Under 110 chars). NO hashtags."
    text = get_claude_text(prompt) or f"Remember {game['name']}?"
    imgs = []
    main_img = download_image(game['background_image'])
    if main_img: imgs.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=bsky.upload_blob(image_to_bytes(main_img)).blob))
    screens = 0
    for shot in game.get('short_screenshots', []):
        if screens >= 2: break
        if shot['image'] == game['background_image']: continue
        s_img = download_image(shot['image'])
        if s_img:
            imgs.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=bsky.upload_blob(image_to_bytes(s_img)).blob))
            screens += 1
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f: imgs.append(models.AppBskyEmbedImages.Image(alt="Nostalgia", image=bsky.upload_blob(f.read()).blob))
    
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    if slot_type == "Obscure" and random.random() < 0.3:
        tb.text("Uncovered in the Archive. 📂 "); tb.link("nostalgia.icu/database", "https://www.nostalgia.icu/database/"); tb.text("\n\n")
    
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    g_tag = clean_game_hashtag(game['name'])
    if g_tag != "#RetroGame": tb.tag(g_tag, g_tag.replace("#", "")); tb.text(" ")
    plat = get_platform_tags(game, 1)[0]
    tb.tag(plat, plat.replace("#", "")); tb.text(" "); tb.tag(cfg['t'], cfg['t'].replace("#", ""))
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs[:4]))

def run_fact(bsky):
    game_list = fetch_games_from_rawg(1)
    if not game_list: return
    game = game_list[0]
    genre = get_genre_name(game)
    prompt = f"Tell a trivia fact about the {genre} game '{game['name']}'. Keep it EXTREMELY BRIEF (Under 110 characters). NO hashtags."
    text = get_claude_text(prompt) or f"Did you know {game['name']} is a classic?"
    imgs = []
    main_img = download_image(game['background_image'])
    if main_img: imgs.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=bsky.upload_blob(image_to_bytes(main_img)).blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f: imgs.append(models.AppBskyEmbedImages.Image(alt="Nostalgia", image=bsky.upload_blob(f.read()).blob))
    
    tb = client_utils.TextBuilder(); tb.text(f"{random.choice(FACT_INTROS)} 🧠\n\n{text}\n\n")
    if random.random() < 0.3: tb.text("More history: "); tb.link("nostalgia.icu/history", "https://www.nostalgia.icu/history/"); tb.text("\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming"); tb.text(" "); tb.tag("#FunFact", "FunFact"); tb.text(" ")
    plat = get_platform_tags(game, 1)[0]; tb.tag(plat, plat.replace("#", ""))
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs))
    save_json('history_facts.json', load_json('history_facts.json', []) + [game['id']])

def run_on_this_day(bsky):
    game = fetch_on_this_day_game()
    if not game: run_fact(bsky); return
    genre = get_genre_name(game)
    prompt = f"Celebrate that the {genre} game '{game['name']}' was released today in {game['release_year']}. Keep it EXTREMELY BRIEF (Under 110 characters). NO hashtags."
    text = get_claude_text(prompt) or f"On this day, {game['name']} was released!"
    imgs = []
    main_img = download_image(game['background_image'])
    if main_img: imgs.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=bsky.upload_blob(image_to_bytes(main_img)).blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f: imgs.append(models.AppBskyEmbedImages.Image(alt="Nostalgia", image=bsky.upload_blob(f.read()).blob))
    
    tb = client_utils.TextBuilder(); tb.text(f"📅 On This Day ({game['release_year']})\n\n{text}\n\nSee what else launched: ")
    tb.link("nostalgia.icu/history", "https://www.nostalgia.icu/history/"); tb.text("\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming"); tb.text(" "); plat = get_platform_tags(game, 1)[0]; tb.tag(plat, plat.replace("#", "")); tb.text(" "); tb.tag("#OnThisDay", "OnThisDay")
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs))

def run_elimination(bsky):
    genre_name, genre_id = random.choice(list(GENRES.items()))
    games = fetch_games_from_rawg(4, genre_id=genre_id)
    if len(games) < 4: return
    game_list_text, all_plats = "", []
    for idx, g in enumerate(games):
        game_list_text += f"{idx+1}. {g['name']}\n"
        all_plats.extend(get_platform_tags(g, 2))
    all_plats = list(set(all_plats))
    prompt = f"Ask: 'Delete one of these {genre_name} classics forever. Which one goes?' Under 100 chars. NO hashtags."
    text = get_claude_text(prompt) or "One has to go. Choose."
    imgs, pil_imgs = [], [download_image(g['background_image']) for g in games]
    pil_imgs = [p for p in pil_imgs if p]
    if len(pil_imgs) >= 4:
        collage = create_collage(pil_imgs[:4], grid=(2,2))
        imgs.append(models.AppBskyEmbedImages.Image(alt=f"{genre_name} Elimination", image=bsky.upload_blob(image_to_bytes(collage)).blob))
    for g in games[:2]:
        s_img = download_image(get_distinct_screenshot(g, g['background_image']))
        if s_img: imgs.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=bsky.upload_blob(image_to_bytes(s_img)).blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f: imgs.append(models.AppBskyEmbedImages.Image(alt="Nostalgia", image=bsky.upload_blob(f.read()).blob))
    
    tb = client_utils.TextBuilder(); tb.text(text + "\n\n" + game_list_text + "\n")
    tb.tag("#Retro", "Retro"); tb.text(" "); tb.tag("#RetroGaming", "RetroGaming"); tb.text(" "); tb.tag("#Nostalgia", "Nostalgia"); tb.text(" ")
    for tag in all_plats: tb.tag(tag, tag.replace("#", "")); tb.text(" ")
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs[:4]))

# --- MAIN DISPATCHER ---
def main():
    try:
        bsky = Client(); bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("✅ Connected.")
    except: return
    now = datetime.utcnow()
    day, hour = now.weekday(), now.hour
    forced, manual = os.environ.get("FORCED_SLOT", ""), os.environ.get("IS_MANUAL") == "true"
    slot_id = None
    if manual and "Slot" in forced:
        try: slot_id = int(forced.split(":")[0].replace("Slot", "").strip())
        except: pass
    elif manual and "Auto-Detect" in forced:
        slots = list(SCHEDULE.get(day, {}).values())
        if slots: slot_id = slots[0]
    elif not manual:
        slot_id = SCHEDULE.get(day, {}).get(hour)
    if not slot_id: return
    logger.info(f"🚀 Slot {slot_id}")
    handlers = {1: lambda: run_slot_1_ad(bsky), 2: lambda: run_generic_q(bsky), 3: lambda: run_rivalry(bsky), 4: lambda: run_single_game_post(bsky, "Unpopular"), 5: lambda: run_fact(bsky), 6: lambda: run_single_game_post(bsky, "Obscure"), 7: lambda: run_elimination(bsky), 8: lambda: run_generic_q(bsky), 9: lambda: run_single_game_post(bsky, "Aesthetic"), 10: lambda: run_fact(bsky), 11: lambda: run_single_game_post(bsky, "Memory"), 12: lambda: run_fact(bsky), 13: lambda: run_on_this_day(bsky), 14: lambda: run_fact(bsky), 15: lambda: run_single_game_post(bsky, "Memory"), 17: lambda: run_generic_q(bsky), 18: lambda: run_rivalry(bsky)}
    if slot_id in handlers: handlers[slot_id]()

if __name__ == "__main__":
    main()
