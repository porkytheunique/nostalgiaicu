def post_with_retry(bsky, game_id, theme, custom_header=""):
    full_game = deep_fetch_game(game_id)
    if not full_game: return False
    
    name, genre = full_game['name'], ", ".join([g['name'] for g in full_game['genres'][:2]])
    r_date = full_game.get('released', 'N/A')
    p_tags = get_platform_tags(full_game, 1)
    g_tag = clean_game_hashtag(name)
    
    logger.info(f"📊 [STRICT IMAGE FETCH] Starting image collection for: {name}")

    for attempt in range(1, 4):
        # PROMPT: Forced engagement question at the end
        p = (f"Write a {theme} post about '{name}' ({genre}) released {r_date}. "
             f"MANDATORY: End with a thought-provoking question for fans to encourage comments. "
             f"STRICT LIMIT: Under 110 chars. No hashtags.")
        
        if attempt == 2: p = f"RETRY: Summarize {name} in one punchy sentence ending with a question. Max 70 chars."
        
        if attempt == 3: text = f"Is {name} ({r_date[:4]}) actually a classic, or just nostalgia? What do you think?"
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
            imgs_to_upload = []
            
            # 1. Background Image
            bg_url = full_game.get('background_image')
            if bg_url:
                img = download_image(bg_url)
                if img: imgs_to_upload.append(img)
            
            # 2. Screenshots (Search more aggressively)
            screens_found = 0
            all_screens = full_game.get('short_screenshots', [])
            logger.info(f"🔍 [IMAGE LOG] RAWG provided {len(all_screens)} possible screenshots.")
            
            for shot in all_screens:
                if len(imgs_to_upload) >= 3: break # Stop once we have 3 game images
                shot_url = shot.get('image')
                if shot_url == bg_url: continue # Don't duplicate the main image
                
                s_img = download_image(shot_url)
                if s_img:
                    imgs_to_upload.append(s_img)
                    screens_found += 1
            
            # 3. Fallback: If RAWG is empty, try the second background image
            if len(imgs_to_upload) < 3 and full_game.get('background_image_additional'):
                add_img = download_image(full_game['background_image_additional'])
                if add_img: imgs_to_upload.append(add_img)

            # 4. Mandatory Promo Ad
            if os.path.exists("images/promo_ad.jpg"):
                with Image.open("images/promo_ad.jpg") as ad:
                    imgs_to_upload.append(ad.copy())
            
            logger.info(f"📸 [IMAGE LOG] Final count for upload: {len(imgs_to_upload)}")

            blobs = []
            for i, img in enumerate(imgs_to_upload[:4]):
                blob_data = image_to_bytes(img)
                blob = bsky.upload_blob(blob_data).blob
                blobs.append(models.AppBskyEmbedImages.Image(alt=f"{name} Visual {i+1}", image=blob))
            
            bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=blobs))
            save_json('history_games.json', (load_json('history_games.json', []) + [game_id])[-2000:])
            return True
    return False
