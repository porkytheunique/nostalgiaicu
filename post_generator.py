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

# --- CONSTANTS & SCHEDULE ---
# Times are UTC. 
# 09:00 = Morning Visuals
# 15:00 = Afternoon Engagement
# 21:00 = Evening History/Facts
SCHEDULE = {
    0: {9: 1, 15: 2, 21: 13},   # Mon: Ad, Generic Q, On This Day
    1: {9: 9, 15: 3, 21: 14},   # Tue: Aesthetic, Rivalry, Fact
    2: {9: 4, 15: 17, 21: 13},  # Wed: Unpopular, Generic Q, On This Day
    3: {9: 6, 15: 18, 21: 14},  # Thu: Obscure, Rivalry, Fact
    4: {9: 7, 15: 8, 21: 13},   # Fri: Elimination (Old Starter Pack), Generic Q, On This Day
    5: {9: 9, 15: 10, 21: 15},  # Sat: Aesthetic, Fact, Memory
    6: {9: 11, 15: 12, 21: 13}  # Sun: Memory, Fact, On This Day
}

# --- GENRE & PLATFORM DEFINITIONS ---
RETRO_PLATFORM_IDS = "27,15,83,79,24,167,80,106,49,105,109,107,12,119,117,43"

# Platforms specifically for "Pixel Art" posts (No PS1/N64/Xbox)
PIXEL_PLATFORMS_IDS = "79,24,167,49,109,12,43" # SNES, GBA, Genesis, NES, TurboGrafx, NeoGeo, GBC

GENRES = {
    "Platformer": 83,
    "Shooter": 2,
    "RPG": 5,
    "Fighting": 6,
    "Racing": 1
}

# --- MONDAY FEATURE DEFINITIONS ---
MONDAY_FEATURES = [
    {
        "name": "Magazine Library",
        "url": "https://www.nostalgia.icu/library/",
        "img": "images/ad_library.jpg",
        "texts": ["Flip through history! 📖 Thousands of classic gaming magazines preserved.", "Revisit the golden era of gaming journalism. 📰"],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Library"]
    },
    {
        "name": "Retro Media Player",
        "url": "https://www.nostalgia.icu/media/",
        "img": "images/ad_media.jpg",
        "texts": ["Tune in to the past! 📺 Vintage cartoons and commercials streaming now.", "Your portal to broadcast history. 📡"],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#RetroTV"]
    },
    {
        "name": "Retro Radio",
        "url": "https://www.nostalgia.icu/radio/",
        "img": "images/ad_radio.jpg",
        "texts": ["Vibe to the classics. 📻 24/7 Retro Radio playing the best VGM.", "The soundtrack of your childhood is live. 🎧"],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Radio"]
    },
    {
        "name": "System Advisor",
        "url": "https://www.nostalgia.icu/advisor/",
        "img": "images/ad_advisor.jpg",
        "texts": ["Stuck in a game? 🤖 Chat with our System Curator.", "Find the value of your old carts. 💡"],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Advisor"]
    },
    {
        "name": "Nostalgia Quest",
        "url": "https://www.nostalgia.icu/quest/",
        "img": "images/ad_quest.jpg",
        "texts": ["Enter the dungeon! ⚔️ Join the Nostalgia Quest.", "Earn street cred. 🛡️ Prove your mastery."],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Quest"]
    },
    {
        "name": "Gaming History",
        "url": "https://www.nostalgia.icu/history/",
        "img": "images/ad_history.jpg",
        "texts": ["On this day... 📅 Check which legends were released today.", "Travel back in time. ⏳ See what happened today in gaming."],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#GamingHistory"]
    },
    {
        "name": "Game Database",
        "url": "https://www.nostalgia.icu/database/",
        "img": "images/ad_database.jpg",
        "texts": ["The ultimate index. 💾 Search our massive Retro Database.", "Need info? 💽 Our Database has the data."],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#GameDB"]
    },
    {
        "name": "Pixel Challenge",
        "url": "https://www.nostalgia.icu/quest/",
        "img": "images/ad_challenge.jpg",
        "texts": ["Test your eyes! 👀 Can you identify the game from a few pixels?", "Take the Daily Pixel Challenge. 🧩"],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#PixelArt"]
    }
]

GENERIC_TOPICS = [
    "Memory Cards", "Cheat Codes", "Couch Co-op", "Game Over Screens", "Demo Discs", 
    "Instruction Manuals", "Boss Fights", "Soundtracks", "Loading Screens", "Controller Cables",
    "Video Rental Stores", "Strategy Guides", "Save Points", "Easter Eggs", "Start Menus"
]

PLATFORM_TAGS = {
    "PlayStation": "#PS1", "PlayStation 2": "#PS2", "PlayStation 3": "#PS3",
    "Xbox": "#Xbox", "Xbox 360": "#Xbox360",
    "SNES": "#SNES", "NES": "#NES", "Nintendo 64": "#N64", "GameCube": "#GameCube",
    "Game Boy": "#GameBoy", "Game Boy Advance": "#GBA", "Game Boy Color": "#GameBoyColor",
    "Sega Genesis": "#SegaGenesis", "Dreamcast": "#Dreamcast", "Sega Saturn": "#SegaSaturn",
    "Sega CD": "#SegaCD", "Sega 32X": "#Sega32X",
    "Neo Geo": "#NeoGeo", "TurboGrafx-16": "#TurboGrafx16", "PC": "#PCGaming"
}

CONSOLE_IMAGES = [
    "images/console_nes.jpg", "images/console_snes.jpg", "images/console_n64.jpg",
    "images/console_gamecube.jpg", "images/console_ps1.jpg", "images/console_ps2.jpg",
    "images/console_xbox.jpg", "images/console_genesis.jpg", "images/console_dreamcast.jpg",
    "images/console_saturn.jpg", "images/console_turbografx.jpg", "images/console_neogeo.jpg",
    "images/console_segacd.jpg", "images/console_32x.jpg", "images/console_gbc.jpg"
]

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

def create_collage(images, grid=(2,1)):
    if not images: return None
    target_h = 600
    resized_imgs = []
    
    # Pre-resize logic
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
            # Center crop to square
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
    """
    Creates a clean hashtag from a game name.
    e.g. "Super Mario World" -> "#SuperMarioWorld"
    """
    clean = re.sub(r'[^a-zA-Z0-9]', '', game_name)
    if not clean: return "#RetroGame"
    return f"#{clean}"

def get_platform_tags(game_data, limit=1):
    """
    Returns platform hashtags.
    limit: How many tags to return (default 1 for single game posts).
    """
    found_tags = []
    
    for p in game_data.get('platforms', []):
        name = p['platform']['name']
        if name in PLATFORM_TAGS:
            found_tags.append(PLATFORM_TAGS[name])
        else:
            for key, val in PLATFORM_TAGS.items():
                if key in name:
                    found_tags.append(val)
                    break
    
    found_tags = list(set(found_tags))
    
    # Sort PC gaming to end
    if "#PCGaming" in found_tags and len(found_tags) > 1:
        found_tags.remove("#PCGaming")
        found_tags.append("#PCGaming")
    
    if not found_tags:
        return ["#RetroGaming"]
        
    return found_tags[:limit]

def fetch_games_from_rawg(count=1, platform_ids=None, genre_id=None):
    used_games = load_json('history_games.json', [])
    found_games = []
    
    platforms = platform_ids if platform_ids else RETRO_PLATFORM_IDS
    
    # Attempt loop
    for _ in range(10): 
        if len(found_games) >= count: break
        page = random.randint(1, 100)
        
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&platforms={platforms}&ordering=-rating&page_size={count*2}&page={page}"
        
        if genre_id:
            url += f"&genres={genre_id}"
            
        try:
            data = requests.get(url).json()
            for cand in data.get('results', []):
                if cand['id'] not in used_games and cand['id'] not in [g['id'] for g in found_games]:
                    if cand.get('background_image'):
                        found_games.append(cand)
                        if len(found_games) == count: break
        except Exception as e:
            logger.error(f"RAWG Error: {e}")

    if found_games:
        new_ids = [g['id'] for g in found_games]
        used_games.extend(new_ids)
        if len(used_games) > 2000: used_games = used_games[-2000:]
        save_json('history_games.json', used_games)
        
    return found_games

def fetch_on_this_day_game():
    now = datetime.now()
    month = now.month
    day = now.day
    
    for _ in range(5):
        year = random.randint(1985, 2005)
        date_str = f"{year}-{month:02d}-{day:02d}"
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={date_str},{date_str}&ordering=-added&page_size=5"
        try:
            data = requests.get(url).json()
            results = data.get('results', [])
            if results:
                game = random.choice(results[:3])
                if game.get('background_image'):
                    full_game_url = f"https://api.rawg.io/api/games/{game['id']}?key={RAWG_API_KEY}"
                    full_details = requests.get(full_game_url).json()
                    full_details['release_year'] = year 
                    return full_details
        except: pass
    return None

# --- SLOT HANDLERS ---

def run_slot_1_ad(bsky):
    history = load_json('history_ads.json', {'last_index': -1})
    idx = (history['last_index'] + 1) % len(MONDAY_FEATURES)
    feature = MONDAY_FEATURES[idx]
    
    message = random.choice(feature['texts'])
    logger.info(f"📢 Preparing Monday Ad for: {feature['name']}")

    tb = client_utils.TextBuilder()
    tb.text(message)
    tb.text("\n\n🔗 Visit: ")
    tb.link(feature['url'], feature['url'])
    tb.text("\n\n")
    
    for tag in feature.get('tags', []):
        tb.tag(tag, tag.replace("#", ""))
        tb.text(" ")
    
    img_bytes = None
    if os.path.exists(feature['img']):
        with open(feature['img'], 'rb') as f: img_bytes = f.read()
    
    if img_bytes:
        upload = bsky.upload_blob(img_bytes)
        embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=feature['name'], image=upload.blob)])
        bsky.send_post(tb, embed=embed)
        save_json('history_ads.json', {'last_index': idx})
        logger.info(f"✅ Slot 1 Posted: {feature['name']}")

def run_generic_q(bsky):
    used_q = load_json('history_questions.json', [])
    valid_images = [img for img in CONSOLE_IMAGES if os.path.exists(img)]
    
    mode = "topic"
    if valid_images and random.random() > 0.5:
        mode = "console"

    img_embed = None
    topic_text = ""
    console_tag = None

    if mode == "console":
        chosen_img = random.choice(valid_images)
        raw_name = chosen_img.replace("images/console_", "").replace(".jpg", "").upper()
        
        # Mapping logic for nice names and specific tags
        console_map = {
            "NES": ("Nintendo Entertainment System (NES)", "#NES"),
            "SNES": ("Super Nintendo (SNES)", "#SNES"),
            "N64": ("Nintendo 64", "#N64"),
            "GAMECUBE": ("GameCube", "#GameCube"),
            "GENESIS": ("Sega Genesis", "#SegaGenesis"),
            "SATURN": ("Sega Saturn", "#SegaSaturn"),
            "DREAMCAST": ("Dreamcast", "#Dreamcast"),
            "PS1": ("PlayStation 1", "#PS1"),
            "PS2": ("PlayStation 2", "#PS2"),
            "XBOX": ("Original Xbox", "#Xbox"),
            "GBC": ("Game Boy Color", "#GameBoyColor"),
            "NEOGEO": ("Neo Geo", "#NeoGeo"),
            "TURBOGRAFX": ("TurboGrafx-16", "#TurboGrafx16")
        }
        
        c_info = None
        for k, v in console_map.items():
            if k in raw_name:
                c_info = v
                break
        
        console_name = c_info[0] if c_info else "Retro Console"
        console_tag = c_info[1] if c_info else "#RetroGaming"

        topic_text = f"the {console_name}"
        prompt = f"Write a short, nostalgic question specifically about the {console_name}. Under 200 chars. DO NOT use hashtags."
        
        with open(chosen_img, 'rb') as f:
            upload = bsky.upload_blob(f.read())
            img_embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=f"{console_name} Console", image=upload.blob)])
    else:
        topic = random.choice([t for t in GENERIC_TOPICS if t not in used_q[-5:]])
        topic_text = topic
        prompt = f"Write a broad question for retro gamers about '{topic}'. Under 200 chars. DO NOT use hashtags."
        
        if valid_images:
            chosen_img = random.choice(valid_images)
            with open(chosen_img, 'rb') as f:
                upload = bsky.upload_blob(f.read())
                img_embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt="Retro Console", image=upload.blob)])
        
        used_q.append(topic)
        save_json('history_questions.json', used_q[-50:])

    text = get_claude_text(prompt) or f"What's your take on {topic_text}?"
    
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming")
    
    if console_tag:
        tb.text(" ")
        tb.tag(console_tag, console_tag.replace("#", ""))
    
    bsky.send_post(tb, embed=img_embed)
    logger.info(f"✅ Generic Q Posted: {topic_text}")

def run_rivalry(bsky):
    pair = random.choice(RIVAL_PAIRS)
    games_p1 = fetch_games_from_rawg(1, pair['p1'])
    games_p2 = fetch_games_from_rawg(1, pair['p2'])
    if not games_p1 or not games_p2: return
    g1, g2 = games_p1[0], games_p2[0]
    
    prompt = f"Write a 'vs' question comparing {g1['name']} ({pair['t1']}) and {g2['name']} ({pair['t2']}). Who won? Under 240 chars. DO NOT use hashtags."
    text = get_claude_text(prompt) or f"{g1['name']} vs {g2['name']}."
    
    imgs_to_upload = []
    i1 = download_image(g1['background_image'])
    i2 = download_image(g2['background_image'])
    if i1 and i2:
        collage = create_collage([i1, i2], grid=(2,1))
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Rivalry Collage", image=blob))
    
    # Extra screens
    for g, img_url in [(g1, g1['background_image']), (g2, g2['background_image'])]:
        s_url = get_distinct_screenshot(g, exclude_url=img_url)
        s_img = download_image(s_url)
        if s_img:
            blob = bsky.upload_blob(image_to_bytes(s_img)).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=g['name'], image=blob))

    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))

    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(pair['t1'], pair['t1'].replace("#", "")); tb.text(" ")
    tb.tag(pair['t2'], pair['t2'].replace("#", ""))
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info("✅ Rivalry Posted")

def run_single_game_post(bsky, slot_type):
    # Special Check for Aesthetic (Pixel Art Only)
    platform_override = None
    if slot_type == "Aesthetic":
        platform_override = PIXEL_PLATFORMS_IDS
        
    game_list = fetch_games_from_rawg(1, platform_ids=platform_override)
    if not game_list: return
    game = game_list[0]
    
    configs = {
        "Unpopular": {"prompt": "unpopular opinion about difficulty or design", "tag": "#UnpopularOpinion"},
        "Obscure": {"prompt": "why this is a hidden gem", "tag": "#HiddenGem"},
        "Aesthetic": {"prompt": "praise the pixel art or visuals. Mention the beauty.", "tag": "#PixelArt"},
        "Memory": {"prompt": "ask for a specific childhood memory", "tag": "#Nostalgia"}
    }
    cfg = configs[slot_type]
    
    prompt = f"Write a post about '{game['name']}'. Theme: {cfg['prompt']}. Under 240 chars. DO NOT use hashtags."
    text = get_claude_text(prompt) or f"Remember {game['name']}?"
    
    imgs_to_upload = []
    main_img = download_image(game['background_image'])
    if main_img:
        blob = bsky.upload_blob(image_to_bytes(main_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=blob))
        
    screens_added = 0
    for shot in game.get('short_screenshots', []):
        if screens_added >= 2: break
        if shot['image'] == game['background_image']: continue 
        s_img = download_image(shot['image'])
        if s_img:
            blob = bsky.upload_blob(image_to_bytes(s_img)).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=blob))
            screens_added += 1
            
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))

    # TAG LOGIC: #Retro #RetroGaming #GameName #Platform
    game_tag = clean_game_hashtag(game['name'])
    plat_tag = get_platform_tags(game, limit=1)[0]
    
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    
    if slot_type == "Obscure" and random.random() < 0.3:
        tb.text("Uncovered in the Archive. 📂 ")
        tb.link("nostalgia.icu/database", "https://www.nostalgia.icu/database/")
        tb.text("\n\n")

    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    
    # Add Game Name Tag (if not too generic)
    if game_tag != "#RetroGame":
        tb.tag(game_tag, game_tag.replace("#", ""))
        tb.text(" ")
    
    # Add Platform Tag
    tb.tag(plat_tag, plat_tag.replace("#", ""))
    
    # Optional: Add the specific theme tag (PixelArt/HiddenGem) if we have space/relevance
    # User requested sticking strictly to Retro/Gaming/Name/Platform, but allowed PixelArt.
    if slot_type == "Aesthetic":
        tb.text(" ")
        tb.tag("#PixelArt", "PixelArt")
    elif slot_type == "Obscure":
         tb.text(" ")
         tb.tag("#HiddenGem", "HiddenGem")

    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info(f"✅ {slot_type} Posted: {game['name']}")

def run_fact(bsky):
    game_list = fetch_games_from_rawg(1)
    if not game_list: return
    game = game_list[0]
    
    intro = random.choice(FACT_INTROS)
    prompt = f"Tell a short trivia fact about '{game['name']}'. Under 200 chars. DO NOT use hashtags."
    text = get_claude_text(prompt) or f"Did you know {game['name']} is a classic?"
    
    imgs_to_upload = []
    main_img = download_image(game['background_image'])
    if main_img:
        blob = bsky.upload_blob(image_to_bytes(main_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=blob))
        
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))

    plat_tag = get_platform_tags(game, limit=1)[0]

    tb = client_utils.TextBuilder()
    tb.text(f"{intro} 🧠\n\n{text}\n\n")
    
    if random.random() < 0.3:
        tb.text("More history: ")
        tb.link("nostalgia.icu/history", "https://www.nostalgia.icu/history/")
        tb.text("\n\n")

    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag("#FunFact", "FunFact"); tb.text(" ")
    tb.tag(plat_tag, plat_tag.replace("#", ""))
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload))
    save_json('history_facts.json', load_json('history_facts.json', []) + [game['id']])
    logger.info(f"✅ Fact Posted: {game['name']}")

def run_on_this_day(bsky):
    game = fetch_on_this_day_game()
    if not game:
        run_fact(bsky)
        return

    year = game['release_year']
    prompt = f"Write a post celebrating that '{game['name']}' was released on this day in {year}. Under 200 chars. DO NOT use hashtags."
    text = get_claude_text(prompt) or f"On this day in {year}, {game['name']} was released!"
    
    imgs_to_upload = []
    main_img = download_image(game['background_image'])
    if main_img:
        blob = bsky.upload_blob(image_to_bytes(main_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=blob))
        
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))

    plat_tag = get_platform_tags(game, limit=1)[0]
    
    tb = client_utils.TextBuilder()
    tb.text(f"📅 On This Day ({year})\n\n{text}\n\n")
    tb.text("See what else launched today: ")
    tb.link("nostalgia.icu/history", "https://www.nostalgia.icu/history/")
    tb.text("\n\n")
    
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(plat_tag, plat_tag.replace("#", "")); tb.text(" ")
    tb.tag("#OnThisDay", "OnThisDay")
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload))
    logger.info(f"✅ On This Day Posted: {game['name']}")

def run_elimination(bsky):
    """
    Slot 7 (Formerly Starter Pack).
    Picks 4 games from the SAME genre.
    Lists names in text.
    """
    genre_name, genre_id = random.choice(list(GENRES.items()))
    games = fetch_games_from_rawg(4, genre_id=genre_id)
    
    if len(games) < 4: 
        logger.error("❌ Not enough games found for Elimination.")
        return

    # Build the List of Names for the text
    game_list_text = ""
    all_platform_tags = []
    
    for idx, g in enumerate(games):
        game_list_text += f"{idx+1}. {g['name']}\n"
        # Collect unique platform tags
        all_platform_tags.extend(get_platform_tags(g, limit=2))
    
    all_platform_tags = list(set(all_platform_tags)) # Remove dupes

    prompt = f"Ask: 'You have to delete one of these {genre_name} classics forever. Which one goes?' Under 100 chars. DO NOT use hashtags. DO NOT list the games, I will do that."
    text = get_claude_text(prompt) or "One has to go. Which one do you choose?"
    
    imgs_to_upload = []
    
    # Collage
    pil_imgs = [download_image(g['background_image']) for g in games]
    pil_imgs = [p for p in pil_imgs if p]
    if len(pil_imgs) >= 4:
        collage = create_collage(pil_imgs[:4], grid=(2,2))
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=f"{genre_name} Elimination", image=blob))
        
    # Screenshots (Must be from the selected games)
    for g in games[:2]:
        main_url = g['background_image']
        s_url = get_distinct_screenshot(g, exclude_url=main_url)
        s_img = download_image(s_url)
        if s_img:
            blob = bsky.upload_blob(image_to_bytes(s_img)).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=blob))

    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))
            
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.text(game_list_text + "\n")
    
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag("#Nostalgia", "Nostalgia"); tb.text(" ")
    
    # Add all unique platform tags (allowed to exceed 4 total here)
    for tag in all_platform_tags:
        tb.tag(tag, tag.replace("#", ""))
        tb.text(" ")
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info(f"✅ Elimination Grid Posted ({genre_name})")

# --- MAIN DISPATCHER ---
def main():
    logger.info("--- BOT RUN STARTED ---")
    
    try:
        bsky = Client()
        bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("✅ Connected to Bluesky.")
    except Exception as e:
        logger.error(f"❌ Login Failed: {e}")
        return

    now = datetime.utcnow()
    day = now.weekday()
    hour = now.hour
    
    forced_input = os.environ.get("FORCED_SLOT", "")
    is_manual = os.environ.get("IS_MANUAL") == "true"
    
    slot_id = None

    if is_manual and "Slot" in forced_input:
        try:
            parts = forced_input.split(":")
            slot_id = int(parts[0].replace("Slot", "").strip())
            logger.info(f"🛠️ Manual Override: Slot {slot_id}")
        except: pass
    elif is_manual and "Auto-Detect" in forced_input:
        todays_slots = list(SCHEDULE.get(day, {}).values())
        if todays_slots:
            slot_id = todays_slots[0]
    elif not is_manual:
        slot_id = SCHEDULE.get(day, {}).get(hour)
        if not slot_id:
            logger.info(f"⏳ No slot scheduled. Exiting.")
            return

    logger.info(f"🚀 Executing Slot {slot_id}...")

    if slot_id == 1: run_slot_1_ad(bsky)
    elif slot_id == 2: run_generic_q(bsky)
    elif slot_id == 3: run_rivalry(bsky)
    elif slot_id == 4: run_single_game_post(bsky, "Unpopular")
    elif slot_id == 5: run_fact(bsky)
    elif slot_id == 6: run_single_game_post(bsky, "Obscure")
    elif slot_id == 7: run_elimination(bsky)    # UPDATED
    elif slot_id == 8: run_generic_q(bsky)
    elif slot_id == 9: run_single_game_post(bsky, "Aesthetic")
    elif slot_id == 10: run_fact(bsky)
    elif slot_id == 11: run_single_game_post(bsky, "Memory")
    elif slot_id == 12: run_fact(bsky)
    elif slot_id == 13: run_on_this_day(bsky)
    elif slot_id == 14: run_fact(bsky)
    elif slot_id == 15: run_single_game_post(bsky, "Memory")
    elif slot_id == 17: run_generic_q(bsky)
    elif slot_id == 18: run_rivalry(bsky)
    else:
        logger.error(f"❌ Unknown Slot ID: {slot_id}")

    logger.info("--- BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
