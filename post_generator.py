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
SCHEDULE = {
    0: {10: 1, 15: 2},   # Mon
    1: {10: 3},          # Tue
    2: {10: 4, 15: 5},   # Wed
    3: {10: 6},          # Thu
    4: {10: 7, 15: 8},   # Fri
    5: {10: 9, 15: 10},  # Sat
    6: {10: 11, 15: 12}  # Sun
}

# --- MONDAY FEATURE DEFINITIONS ---
MONDAY_FEATURES = [
    {
        "name": "Magazine Library",
        "url": "https://www.nostalgia.icu/library/",
        "img": "images/ad_library.jpg",
        "texts": [
            "Flip through the pages of history! 📖 Our Archive contains thousands of classic gaming magazines preserved for you.",
            "Remember the hype? Revisit the golden era of gaming journalism in our digital Magazine Library. 📰",
            "From strategy guides to old ads, explore the print heritage of video games in our Library."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Library"]
    },
    {
        "name": "Retro Media Player",
        "url": "https://www.nostalgia.icu/media/",
        "img": "images/ad_media.jpg",
        "texts": [
            "Tune in to the past! 📺 Watch live retro gaming streams, vintage cartoons, and classic commercials on our Media Player.",
            "Your portal to broadcast history. 📡 Catch documentaries, game promos, and TV ads from the CRT era.",
            "Need something to watch? Our Retro Media Player streams vintage content, cartoons, and gameplay 24/7."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#RetroTV"]
    },
    {
        "name": "Retro Radio",
        "url": "https://www.nostalgia.icu/radio/",
        "img": "images/ad_radio.jpg",
        "texts": [
            "Vibe to the classics. 📻 Our 24/7 Retro Radio plays the best video game soundtracks and chiptunes all day long.",
            "Work, study, or relax to the sounds of 8-bit and 16-bit mastery. Tune in to Nostalgia.ICU Radio now! 🎵",
            "The soundtrack of your childhood is streaming live. 🎧 Listen to pure VGM goodness on our Radio."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Radio"]
    },
    {
        "name": "System Advisor",
        "url": "https://www.nostalgia.icu/advisor/",
        "img": "images/ad_advisor.jpg",
        "texts": [
            "Stuck in a game or need a recommendation? 🤖 Chat with our System Curator for instant retro guidance.",
            "Find the value of your old carts or get tech support for vintage hardware. Our Advisor is online. 💡",
            "Not sure what to play next? Ask our System Curator to unearth a hidden gem just for you."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Advisor"]
    },
    {
        "name": "Nostalgia Quest",
        "url": "https://www.nostalgia.icu/quest/",
        "img": "images/ad_quest.jpg",
        "texts": [
            "Enter the dungeon! ⚔️ Join the Nostalgia Quest, an infinite crawler where your skills will be tested to the max.",
            "Earn and share your street cred. 🛡️ Prove your mastery in our Dungeon Crawler Nostalgia Quest.",
            "Adventure awaits. Clear floors, collect loot, and challenge yourself in the Nostalgia Quest."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#Quest"]
    },
    {
        "name": "Gaming History",
        "url": "https://www.nostalgia.icu/history/",
        "img": "images/ad_history.jpg",
        "texts": [
            "On this day in gaming... 📅 Check out which legendary titles were released on this exact date.",
            "Travel back in time. ⏳ See what happened today in video game history with our daily chronicle.",
            "Celebrate the anniversaries of the games that defined us. Check today's releases in the History section."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#GamingHistory"]
    },
    {
        "name": "Game Database",
        "url": "https://www.nostalgia.icu/database/",
        "img": "images/ad_database.jpg",
        "texts": [
            "The ultimate index. 💾 Search our massive Database to find details on almost every Retro game ever made.",
            "Need info, release dates, or other info? 💽 Our Game Database has the data you're looking for.",
            "Cataloging the past. Explore our comprehensive Database and discover games you missed."
        ],
        "tags": ["#Retro", "#RetroGaming", "#Nostalgia", "#GameDB"]
    },
    {
        "name": "Pixel Challenge",
        "url": "https://www.nostalgia.icu/quest/",
        "img": "images/ad_challenge.jpg",
        "texts": [
            "Test your eyes! 👀 Can you identify the games from a pixelated screenshot? Test your might.",
            "Take the Daily Pixel Challenge. 🧩 Guess the retro classic and keep your streak alive.",
            "Think you know your sprites? Prove it in our Pixel Challenge and show off your retro IQ."
        ],
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
    "Game Boy": "#GameBoy", "Game Boy Advance": "#GBA", "Sega Genesis": "#SegaGenesis",
    "Dreamcast": "#Dreamcast", "PC": "#PCGaming"
}

# --- NEW LISTS FOR VARIETY ---
CONSOLE_IMAGES = [
    "images/console_nes.jpg", "images/console_snes.jpg", "images/console_n64.jpg",
    "images/console_gamecube.jpg", "images/console_ps1.jpg", "images/console_ps2.jpg",
    "images/console_xbox.jpg", "images/console_genesis.jpg", "images/console_dreamcast.jpg"
]

FACT_INTROS = [
    "Did you know?",
    "Retro Fact:",
    "Gaming History:",
    "Fun Fact:",
    "Trivia Time:",
    "Classic Gaming Fact:"
]

RIVAL_PAIRS = [
    {"p1": "27", "p2": "83", "t1": "#PS1", "t2": "#N64"},      # PS1 vs N64
    {"p1": "15", "p2": "80", "t1": "#PS2", "t2": "#Xbox"},     # PS2 vs Xbox
    {"p1": "79", "p2": "167", "t1": "#SNES", "t2": "#Sega"},   # SNES vs Genesis
    {"p1": "106", "p2": "15", "t1": "#Dreamcast", "t2": "#PS2"} # Dreamcast vs PS2
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
        # STRIP QUOTES AND HASHTAGS to clean up output
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

def get_platform_tags(game_data):
    """
    Returns a list of up to 2 hashtags.
    Prioritizes Retro Consoles found in PLATFORM_TAGS.
    Filters out modern consoles (PS4, Switch) because they aren't in the dict.
    Allows matches like [#PCGaming, #PS1].
    """
    found_tags = []
    
    for p in game_data.get('platforms', []):
        name = p['platform']['name']
        
        # Exact match (e.g., "PlayStation")
        if name in PLATFORM_TAGS:
            found_tags.append(PLATFORM_TAGS[name])
        else:
            # Partial match check (e.g. "Sega Genesis" vs "Genesis")
            for key, val in PLATFORM_TAGS.items():
                if key in name:
                    found_tags.append(val)
                    break
    
    # Remove duplicates
    found_tags = list(set(found_tags))
    
    # If empty, default to RetroGaming
    if not found_tags:
        return ["#RetroGaming"]
        
    # If we found multiple, return up to 2 (e.g., #PCGaming and #PS1)
    return found_tags[:2]

def fetch_games_from_rawg(count=1, platform_ids=None):
    used_games = load_json('history_games.json', [])
    found_games = []
    
    for _ in range(10): 
        if len(found_games) >= count: break
        page = random.randint(1, 200)
        platforms = platform_ids if platform_ids else "27,15,83,79,24,167,80,106"
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&platforms={platforms}&ordering=-rating&page_size={count*2}&page={page}"
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

# --- SLOT HANDLERS ---
def run_slot_1_ad(bsky):
    """Monday 10:00: Rotates through 8 website features with varied text."""
    history = load_json('history_ads.json', {'last_index': -1})
    idx = (history['last_index'] + 1) % len(MONDAY_FEATURES)
    feature = MONDAY_FEATURES[idx]
    
    # Select one of the 3 random messages
    message = random.choice(feature['texts'])
    
    logger.info(f"📢 Preparing Monday Ad for: {feature['name']}")

    tb = client_utils.TextBuilder()
    tb.text(message)
    tb.text("\n\n🔗 Visit: ")
    tb.link(feature['url'], feature['url'])
    tb.text("\n\n")
    
    # Loop through the list of tags provided in MONDAY_FEATURES
    for tag in feature.get('tags', []):
        tb.tag(tag, tag.replace("#", ""))
        tb.text(" ")
    
    img_bytes = None
    if os.path.exists(feature['img']):
        with open(feature['img'], 'rb') as f: img_bytes = f.read()
    else:
        logger.warning(f"⚠️ Slot 1 Image missing: {feature['img']}")
    
    if img_bytes:
        upload = bsky.upload_blob(img_bytes)
        embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=feature['name'], image=upload.blob)])
        bsky.send_post(tb, embed=embed)
        save_json('history_ads.json', {'last_index': idx})
        logger.info(f"✅ Slot 1 Posted: {feature['name']}")

def run_generic_q(bsky):
    """
    Dual Mode Generic Question:
    Mode A (50%): Broad "Engagement Bait" topic + Random Console Image (Vibe).
    Mode B (50%): Specific Console Nostalgia + Matching Console Image.
    """
    used_q = load_json('history_questions.json', [])
    
    # Check which console images actually exist
    valid_images = [img for img in CONSOLE_IMAGES if os.path.exists(img)]
    
    # --- DETERMINE MODE ---
    # If we have console images, we can do the 50/50 split.
    # If we don't have images yet, force Mode A (Topic) only.
    mode = "topic"
    if valid_images and random.random() > 0.5:
        mode = "console"

    img_embed = None
    topic_text = ""

    if mode == "console":
        # MODE B: Specific Console Match
        # 1. Pick the image first
        chosen_img = random.choice(valid_images)
        
        # 2. Extract console name from filename (e.g., "images/console_ps1.jpg" -> "PS1")
        console_name = chosen_img.replace("images/console_", "").replace(".jpg", "").upper()
        # Clean up names for the AI prompt
        if "NES" in console_name: console_name = "Nintendo Entertainment System (NES)"
        elif "SNES" in console_name: console_name = "Super Nintendo (SNES)"
        elif "N64" in console_name: console_name = "Nintendo 64"
        elif "GENESIS" in console_name: console_name = "Sega Genesis"
        
        # 3. Generate specific prompt
        topic_text = f"the {console_name}"
        prompt = f"Write a short, nostalgic question specifically about the {console_name}. Under 200 chars. DO NOT use hashtags. DO NOT use quotation marks."
        
        # 4. Attach the matching image
        with open(chosen_img, 'rb') as f:
            upload = bsky.upload_blob(f.read())
            img_embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=f"{console_name} Console", image=upload.blob)])
            
        logger.info(f"🎮 Mode: Console Specific ({console_name})")

    else:
        # MODE A: Broad Engagement Topic
        # 1. Pick a topic
        topic = random.choice([t for t in GENERIC_TOPICS if t not in used_q[-5:]])
        topic_text = topic
        
        # 2. Generate broad prompt
        prompt = f"Write a broad, engaging question for retro gamers about '{topic}'. It should apply to ANY console. Under 200 chars. DO NOT use hashtags. DO NOT use quotation marks."
        
        # 3. Attach a RANDOM console image just for "Retro Vibes" (if available)
        if valid_images:
            chosen_img = random.choice(valid_images)
            with open(chosen_img, 'rb') as f:
                upload = bsky.upload_blob(f.read())
                img_embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt="Retro Console", image=upload.blob)])
        
        logger.info(f"🗣️ Mode: Broad Topic ({topic})")
        
        # Track history for topics only
        used_q.append(topic)
        save_json('history_questions.json', used_q[-50:])

    # --- GENERATE & POST ---
    text = get_claude_text(prompt) or f"What's your take on {topic_text}?"
    
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming")
    
    bsky.send_post(tb, embed=img_embed)
    logger.info(f"✅ Generic Q Posted ({mode}): {topic_text}")

def run_rivalry(bsky):
    pair = random.choice(RIVAL_PAIRS)
    games_p1 = fetch_games_from_rawg(1, pair['p1'])
    games_p2 = fetch_games_from_rawg(1, pair['p2'])
    if not games_p1 or not games_p2: return
    g1, g2 = games_p1[0], games_p2[0]
    
    prompt = f"Write a 'vs' question comparing {g1['name']} ({pair['t1']}) and {g2['name']} ({pair['t2']}). Who won this generation? Under 240 chars. DO NOT use hashtags."
    text = get_claude_text(prompt) or f"{g1['name']} vs {g2['name']}. Which one did you play?"
    
    imgs_to_upload = []
    
    url1 = g1['background_image']
    url2 = g2['background_image']
    i1 = download_image(url1)
    i2 = download_image(url2)
    if i1 and i2:
        collage = create_collage([i1, i2], grid=(2,1))
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Rivalry Collage", image=blob))
    
    s_url1 = get_distinct_screenshot(g1, exclude_url=url1)
    s_img1 = download_image(s_url1)
    if s_img1:
        blob = bsky.upload_blob(image_to_bytes(s_img1)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=g1['name'], image=blob))
        
    s_url2 = get_distinct_screenshot(g2, exclude_url=url2)
    s_img2 = download_image(s_url2)
    if s_img2:
        blob = bsky.upload_blob(image_to_bytes(s_img2)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=g2['name'], image=blob))

    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))
    else:
        logger.warning("⚠️ Promo image 'images/promo_ad.jpg' not found. Skipping.")

    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(pair['t1'], pair['t1'].replace("#", "")); tb.text(" ")
    tb.tag(pair['t2'], pair['t2'].replace("#", ""))
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info("✅ Rivalry Posted")

def run_single_game_post(bsky, slot_type):
    game_list = fetch_games_from_rawg(1)
    if not game_list: return
    game = game_list[0]
    
    configs = {
        "Unpopular": {"prompt": "unpopular opinion about difficulty or design", "tag": "#UnpopularOpinion"},
        "Obscure": {"prompt": "why this is a hidden gem", "tag": "#HiddenGem"},
        "Aesthetic": {"prompt": "praise the art style, graphics, or atmosphere (mention if it is pixel art or low-poly 3D)", "tag": "#RetroAesthetics"},
        "Memory": {"prompt": "ask for a specific childhood memory", "tag": None}
    }
    cfg = configs[slot_type]
    
    prompt = f"Write a Bluesky post about '{game['name']}'. Theme: {cfg['prompt']}. Under 240 chars. DO NOT use hashtags. DO NOT use quotation marks."
    text = get_claude_text(prompt) or f"Remember {game['name']}?"
    
    imgs_to_upload = []
    
    main_url = game['background_image']
    main_img = download_image(main_url)
    if main_img:
        blob = bsky.upload_blob(image_to_bytes(main_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=blob))
        
    screens_added = 0
    for shot in game.get('short_screenshots', []):
        if screens_added >= 2: break
        if shot['image'] == main_url: continue 
        s_img = download_image(shot['image'])
        if s_img:
            blob = bsky.upload_blob(image_to_bytes(s_img)).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=blob))
            screens_added += 1
            
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))
    else:
        logger.warning("⚠️ Promo image 'images/promo_ad.jpg' not found. Skipping.")

    # UPDATED: Get list of up to 2 platform tags
    plat_tags = get_platform_tags(game)
    
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    
    for tag in plat_tags:
        tb.tag(tag, tag.replace("#", ""))
        tb.text(" ")
        
    if cfg['tag']:
        tb.tag(cfg['tag'], cfg['tag'].replace("#", ""))
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info(f"✅ {slot_type} Posted: {game['name']}")

def run_fact(bsky):
    # UPDATED: Varied Intros + Screenshot + Ending Question
    game_list = fetch_games_from_rawg(1)
    if not game_list: return
    game = game_list[0]
    
    intro = random.choice(FACT_INTROS)
    prompt = f"Tell a surprising, short trivia fact about the video game '{game['name']}'. Under 200 chars. DO NOT use hashtags. DO NOT use quotation marks. End with a short engaging question asking for the user's opinion."
    text = get_claude_text(prompt) or f"Did you know {game['name']} is considered a classic?"
    
    imgs_to_upload = []
    
    # 1. Main Image
    main_url = game['background_image']
    main_img = download_image(main_url)
    if main_img:
        blob = bsky.upload_blob(image_to_bytes(main_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=f"{game['name']} Box Art", image=blob))
        
    # 2. Random Screenshot (Added for more visual flair)
    s_url = get_distinct_screenshot(game, exclude_url=main_url)
    s_img = download_image(s_url)
    if s_img:
        blob = bsky.upload_blob(image_to_bytes(s_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=blob))
    
    # 3. Promo Card
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))

    # UPDATED: Get list of up to 2 platform tags
    plat_tags = get_platform_tags(game)

    tb = client_utils.TextBuilder()
    tb.text(f"{intro} 🧠\n\n{text}\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    
    for tag in plat_tags:
        tb.tag(tag, tag.replace("#", ""))
        tb.text(" ")
        
    tb.tag("#FunFact", "FunFact")
    
    if imgs_to_upload:
        bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload))
    else:
        bsky.send_post(tb)
        
    used_f = load_json('history_facts.json', [])
    used_f.append(game['id'])
    save_json('history_facts.json', used_f)
    logger.info(f"✅ Fact Posted: {game['name']}")

def run_starter_pack(bsky):
    games = fetch_games_from_rawg(4)
    if len(games) < 4: return
    prompt = "Ask: 'You have to delete one of these classics forever. Which one goes?' Under 200 chars. DO NOT use hashtags. DO NOT use quotation marks."
    text = get_claude_text(prompt) or "One has to go. Which one do you choose?"
    
    imgs_to_upload = []
    
    pil_imgs = [download_image(g['background_image']) for g in games]
    pil_imgs = [p for p in pil_imgs if p]
    if len(pil_imgs) >= 4:
        collage = create_collage(pil_imgs[:4], grid=(2,2))
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Starter Pack", image=blob))
        
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
    else:
        logger.warning("⚠️ Promo image 'images/promo_ad.jpg' not found. Skipping.")
            
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag("#GamingSetup", "GamingSetup")
    
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info("✅ Starter Pack Posted")

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
            logger.info(f"🛠️ Manual Override: User selected Slot {slot_id}")
        except Exception as e:
            logger.error(f"❌ Could not parse slot ID: {e}")
            return

    elif is_manual and "Auto-Detect" in forced_input:
        todays_slots = list(SCHEDULE.get(day, {}).values())
        if todays_slots:
            slot_id = todays_slots[0]
            logger.info(f"⚡ Manual Auto-Run: Forcing today's Slot {slot_id}")
        else:
            logger.warning("⚠️ No slots found for today.")

    elif not is_manual:
        slot_id = SCHEDULE.get(day, {}).get(hour)
        if not slot_id:
            logger.info(f"⏳ No slot scheduled for UTC Day {day} Hour {hour}. Exiting.")
            return

    logger.info(f"🚀 Executing Slot {slot_id}...")

    if slot_id == 1: run_slot_1_ad(bsky)
    elif slot_id == 2: run_generic_q(bsky)
    elif slot_id == 3: run_rivalry(bsky)
    elif slot_id == 4: run_single_game_post(bsky, "Unpopular")
    elif slot_id == 5: run_fact(bsky)
    elif slot_id == 6: run_single_game_post(bsky, "Obscure")
    elif slot_id == 7: run_starter_pack(bsky)
    elif slot_id == 8: run_generic_q(bsky)
    elif slot_id == 9: run_single_game_post(bsky, "Aesthetic")
    elif slot_id == 10: run_fact(bsky)
    elif slot_id == 11: run_single_game_post(bsky, "Memory")
    elif slot_id == 12: run_fact(bsky)
    else:
        logger.error(f"❌ Unknown or Unscheduled Slot ID: {slot_id}")

    logger.info("--- BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
