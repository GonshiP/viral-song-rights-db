import os, re, json, csv, datetime, time, requests, urllib.parse

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

MASTER_DB_PATH = 'src/data/rights_master.json'
CSV_OUTPUT_PATH = 'public/downloads/viral_song_rights_master.csv'
VALIDITY_DAYS = 90

def get_dates():
    today = datetime.date.today()
    return today.strftime("%Y-%m-%d"), (today + datetime.timedelta(days=VALIDITY_DAYS)).strftime("%Y-%m-%d")

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_season_tag(d_str):
    try:
        m = int(d_str.split('-')[1])
        return f"{d_str[:4]}年" + ("春" if m in [3,4,5] else "夏" if m in [6,7,8] else "秋" if m in [9,10,11] else "冬")
    except Exception: return "定番"

def parse_pub_date(pub_str):
    try:
        dt = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt
    except Exception:
        return get_dates()[0], datetime.datetime.now(datetime.timezone.utc)

def escape_lucene(text):
    return re.sub(r'[\+\-\!\(\)\{\}\[\]\^\"\~\*\?\:\&\|\\\/]', r'\\\g<0>', text)

def clean_song_and_artist_advanced(raw_title, raw_artist):
    """【完全版パターン解析】カギカッコ/引用符/スラッシュ/カバー動画/レーベル名の高精度分離"""
    clean_artist = re.sub(r'\s*-\s*Topic$', '', raw_artist, flags=re.IGNORECASE).strip()
    clean_artist = re.sub(r'Release$|Official$', '', clean_artist, flags=re.IGNORECASE).strip()

    is_generic_channel = any(kw in clean_artist.lower() for kw in [
        "hybe", "smtown", "jyp", "ジュニアchannel", "the first take", "release", "topic", "avex", "universal", "sony", "hoyofair"
    ]) or not clean_artist or (clean_artist == raw_artist and "topic" in raw_artist.lower())

    extracted_title = ""
    extracted_artist = clean_artist

    quote_match = re.search(r'「(.*?)」|『(.*?)』|【(.*?)】|\'(.*?)\'|"(.*?)"', raw_title)
    if quote_match:
        extracted_title = next(g for g in quote_match.groups() if g is not None)
        if extracted_title.lower() in ["mv", "official", "特報", "live"]:
            extracted_title = ""
        else:
            prefix_text = raw_title[:quote_match.start()].strip()
            prefix_artist = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', prefix_text).strip(" -/–—〜")
            if prefix_artist and (is_generic_channel or len(prefix_artist) < 30):
                extracted_artist = prefix_artist.split('(')[0].strip()

    if not extracted_title:
        title_work = re.sub(r'【.*?】|\[.*?\]|\(.*?\)|（.*?）', '', raw_title)
        noise = r'MV|Music Video|Official|歌ってみた|オリジナル曲|Cover|カバー|THE FIRST TAKE|Dance Practice.*|Dance Video|Performance.*|Live.*|Teaser|Audio|Lyric Video|より|feat\..*'
        title_work = re.sub(noise, '', title_work, flags=re.IGNORECASE).strip(" -/–—〜")

        if '/' in title_work or '／' in title_work:
            parts = re.split(r'[/／]', title_work)
            if len(parts) >= 2:
                if "cover" in parts[1].lower() or "カバー" in parts[1]:
                    extracted_title = parts[0].strip()
                    artist_part = re.sub(r'cover\s*-\s*|カバー\s*-\s*|cover|カバー', '', parts[1], flags=re.IGNORECASE).strip()
                    if artist_part:
                        extracted_artist = artist_part
                else:
                    extracted_artist = parts[0].strip()
                    extracted_title = parts[1].strip()
        elif '-' in title_work:
            parts = title_work.split('-')
            if is_generic_channel and len(parts) >= 2:
                extracted_artist, extracted_title = parts[0].strip(), parts[1].strip()
            else:
                extracted_title = parts[1].strip() if len(parts) > 1 else parts[0].strip()
        else:
            extracted_title = title_work

    final_title = re.sub(r'Official.*|MV.*|Music Video.*|Feat\..*', '', extracted_title, flags=re.IGNORECASE).strip(" -/–—〜")
    final_artist = re.sub(r'Official.*|Topic.*', '', extracted_artist, flags=re.IGNORECASE).strip(" -/–—〜")

    return final_title or raw_title, final_artist or raw_artist

def analyze_songs_batch_with_gemini(song_requests):
    """【Gemini API】15曲を一括(1リクエスト)でAI解析してクォータ消費を最小化"""
    if not GEMINI_API_KEY or not song_requests:
        return {}

    models = [
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite"
    ]
    
    songs_prompt_text = ""
    for item in song_requests:
        songs_prompt_text += f"ID: {item['id']}\n動画タイトル: \"{item['raw_title']}\"\nチャンネル名: \"{item['raw_artist']}\"\n---\n"

    prompt = f"""
以下のYouTube動画リストから、各楽曲の原曲の「正確な曲名」と「正確な原曲アーティスト名」を抽出し、指定のJSON形式で出力してください。

【対象リスト】
{songs_prompt_text}

【重要ルール】
1. チャンネル名が「Release - Topic」や「HYBE LABELS」「SMTOWN」「ジュニアCHANNEL」「THE FIRST TAKE」「HoYoFair」等の場合、動画タイトルから本当のアーティスト名（例: ILLIT, ACEes, aespa 等）を特定してください。
2. カバー動画（「/ Cover」「歌ってみた」等）の場合、曲名は「原曲名」、アーティスト名は「原曲アーティスト」を抽出してください。
3. 「MV」「Official」「歌ってみた」「Dance Practice」などのノイズは完全に除去してください。
4. 返答は以下のJSON配列形式のみを出力してください。

[
  {{
    "id": "1",
    "official_title": "正式な曲名",
    "official_artist": "正式な原曲アーティスト名",
    "risk_reason": "ディズニー・任天堂・ゲームBGM等のリスク（無ければ空文字）"
  }}
]
"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0}
    }

    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        print(f"  [DEBUG - Gemini API] 🤖 一括AI解析リクエスト送信中 (モデル: {model_name})...")
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                json_match = re.search(r'\[.*\]', text, re.DOTALL)
                if json_match:
                    parsed_list = json.loads(json_match.group(0))
                    result_map = {}
                    for p in parsed_list:
                        item_id = str(p.get("id"))
                        result_map[item_id] = {
                            "official_title": p.get("official_title", ""),
                            "official_artist": p.get("official_artist", ""),
                            "risk_reason": p.get("risk_reason", "")
                        }
                    print(f"    -> [Gemini Batch Hit] ✅ 成功モデル: '{model_name}' / {len(result_map)} 件一括解析完了")
                    return result_map
            else:
                print(f"  [DEBUG - Gemini Status {res.status_code} ({model_name})]: {res.text[:120]}")
        except Exception as e:
            print(f"  [DEBUG - Gemini Exception ({model_name})]: {e}")

    print("  [DEBUG - Gemini API] ⚠️ すべてのGeminiモデルで解析に失敗したため、高度ローカルパースへフォールバックします。")
    return {}

def get_official_info_itunes(title, artist):
    """【iTunes API】誤爆防止フィルタ付き照合"""
    clean_search_artist = re.sub(r'\(.*?\)|（.*?）', '', artist).split('&')[0].split(',')[0].strip()
    query = f"{clean_search_artist} {title}".strip()
    url = "https://itunes.apple.com/search"
    params = {"term": query, "country": "JP", "media": "music", "entity": "song", "limit": 1}
    
    print(f"  [DEBUG - iTunes API Request] Query: '{query}'")
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200 and (results := res.json().get("results")):
            t_name = results[0].get("trackName", title)
            a_name = results[0].get("artistName", artist)
            
            t_low, q_low = t_name.lower(), title.lower()
            if any(part in t_low for part in q_low.split() if len(part) > 1) or any(part in q_low for part in t_low.split() if len(part) > 1):
                print(f"    -> [iTunes Hit] 公式表記確定: '{t_name}' ({a_name})")
                return t_name, a_name
            else:
                print(f"    -> [iTunes Filtered] 誤判定不採用: '{t_name}' ➔ 元のタイトル保持: '{title}'")
    except Exception as e:
        print(f"    -> [iTunes Exception]: {e}")
    return title, artist

def get_iswc_musicbrainz(title, artist):
    """【2段階ファクト検索】演者完全一致で確定し、不一致でも候補コード・参考URLを親切に提示"""
    clean_title = re.sub(r'\(.*?\)|（.*?）', '', title)
    clean_title = re.sub(r'[\!\?\'"\:\(\)\[\]\/\-]', ' ', clean_title).strip()
    
    main_artist = re.sub(r'\(.*?\)|（.*?）', '', artist)
    main_artist = re.split(r'[,&/]|feat', main_artist, flags=re.IGNORECASE)[0].strip()
    main_artist_low = main_artist.lower()

    # ★一段目のLucene検索クエリ（work:"曲名"）をWebダイレクトURLにも完全連動使用
    encoded_mb_title = urllib.parse.quote(f'work:"{clean_title}"')
    mb_web_search_url = f"https://musicbrainz.org/search?query={encoded_mb_title}&type=work"

    query = f'work:"{escape_lucene(clean_title)}"'
    url = "https://musicbrainz.org/ws/2/work/"
    headers = {"User-Agent": "ViralSongRightsBot/2.5 (https://github.com/example/viral-song-rights-db)"}

    print(f"  [DEBUG - MusicBrainz API Request] Query: '{query}' (limit=50)")
    
    for attempt in range(2):
        time.sleep(1.2)
        try:
            res = requests.get(url, params={"query": query, "fmt": "json", "limit": 50}, headers=headers, timeout=30)
            
            if res.status_code == 200:
                works = res.json().get("works", [])
                if not works:
                    print("    -> [MusicBrainz Fact] 該当ワーク未登録")
                    return None, "MusicBrainz", mb_web_search_url

                best_work = None
                candidate_iswc = None
                candidate_url = None

                for work in works:
                    work_text = json.dumps(work, ensure_ascii=False).lower()
                    
                    if not candidate_iswc and work.get("iswcs"):
                        candidate_iswc = work["iswcs"][0]
                        candidate_url = f"https://musicbrainz.org/work/{work.get('id')}"

                    if main_artist_low and len(main_artist_low) >= 2 and main_artist_low in work_text:
                        best_work = work
                        print(f"    -> [MusicBrainz Fact] ✅ 演者一致ワーク発見: ID={work.get('id')}")
                        break

                if best_work:
                    iswcs = best_work.get("iswcs", [])
                    work_id = best_work.get("id")
                    # ワークIDが判明している場合は特定ページへ直接リンク
                    src_url = f"https://musicbrainz.org/work/{work_id}" if work_id else mb_web_search_url

                    if iswcs:
                        print(f"    -> [MusicBrainz Fact] ✅ ISWCコード確定: {iswcs[0]}")
                        return f"ISWC:{iswcs[0]}", "MusicBrainz", src_url
                    else:
                        print(f"    -> [MusicBrainz Fact] ワーク確認(ID: {work_id})、ISWC未割り当て")
                        return None, "MusicBrainz", src_url

                if candidate_iswc:
                    print(f"    -> [MusicBrainz Fact] 💡 同名異曲の候補コード発見: {candidate_iswc} (要確認)")
                    return f"参考候補:{candidate_iswc}", "MusicBrainz", candidate_url or mb_web_search_url

                print("    -> [MusicBrainz Fact] タイトル一致ワークあり（コード未登録）")
                return None, "MusicBrainz", mb_web_search_url

            elif res.status_code == 503:
                print(f"    -> [MusicBrainz 503] 5.0秒待機して再試行... (Attempt {attempt+1})")
                time.sleep(5.0)
        except Exception as e:
            print(f"    -> [MusicBrainz Exception ({type(e).__name__})]: {e}")
            time.sleep(3.0)

    return None, "MusicBrainz", mb_web_search_url

def load_master_db():
    today_str, valid_until_str = get_dates()
    if os.path.exists(MASTER_DB_PATH):
        try:
            with open(MASTER_DB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"[DEBUG - DB Load] 既存のマスターDBを読み込みました (全 {len(data)} 件)")
                for entry in data:
                    entry.pop("season_tag", None)
                    t, a = entry.get('jasrac_search_title', entry.get('title','')), entry.get('jasrac_search_artist', entry.get('artist',''))
                    entry.setdefault("last_metrics", {"views": 0, "likes": 0, "comments": 0, "engagement_rate": 0.0, "daily_views": 0})
                    entry.setdefault("source_name", "MusicBrainz")
                    entry.setdefault("source_url", "https://musicbrainz.org")
                    entry.setdefault("verified_at", entry.get("added_date", today_str))
                    entry.setdefault("valid_until", valid_until_str)
                    entry.setdefault("jasrac_search_title", t)
                    entry.setdefault("jasrac_search_artist", a)
                    
                    encoded_mb = urllib.parse.quote(f'work:"{t}"')
                    entry.setdefault("mb_search_url", f"https://musicbrainz.org/search?query={encoded_mb}&type=work")
                    
                    encoded_jasrac = urllib.parse.quote(f"JASRAC 検索 {t} {a}")
                    entry.setdefault("jasrac_search_url", f"https://www.google.com/search?q={encoded_jasrac}")
                    
                    encoded_karaoke = urllib.parse.quote(f"{a} {t} カラオケ 歌枠用")
                    entry.setdefault("karaoke_search_url", f"https://www.youtube.com/results?search_query={encoded_karaoke}")
                return data
        except Exception as e: print(f"[DEBUG - DB Load Error]: {e}")
    print("[DEBUG - DB Load] マスターDBが存在しないため、新規空DB作成モードで開始します。")
    return []

def auto_enrich_and_get_rights(raw_title, raw_artist, pub_date, metrics, master_db, ai_info=None):
    """【客観ファクト記録】検索ワード・取得コード・注意タグおよびダイレクト検索URLを記録"""
    today_str, valid_until_str = get_dates()
    
    if not ai_info:
        fallback_title, fallback_artist = clean_song_and_artist_advanced(raw_title, raw_artist)
        ai_info = {"official_title": fallback_title, "official_artist": fallback_artist, "risk_reason": ""}

    clean_title = ai_info.get("official_title") or raw_title
    clean_artist = ai_info.get("official_artist") or raw_artist
    risk_reason = ai_info.get("risk_reason", "")

    # iTunes APIによる公式表記補正
    final_title, final_artist = get_official_info_itunes(clean_title, clean_artist)

    encoded_mb_title = urllib.parse.quote(f'work:"{final_title}"')
    mb_search_url = f"https://musicbrainz.org/search?query={encoded_mb_title}&type=work"

    encoded_jasrac_query = urllib.parse.quote(f"JASRAC 検索 {final_title} {final_artist}")
    jasrac_search_url = f"https://www.google.com/search?q={encoded_jasrac_query}"

    encoded_karaoke = urllib.parse.quote(f"{final_artist} {final_title} カラオケ 歌枠用")
    karaoke_url = f"https://www.youtube.com/results?search_query={encoded_karaoke}"

    # 既存DB照合
    t_low = final_title.lower()
    for entry in master_db:
        e_title = entry.get("jasrac_search_title", entry.get("title", "")).lower()
        if e_title in t_low or t_low in e_title:
            entry.update({
                "last_metrics": metrics, 
                "verified_at": today_str, 
                "valid_until": valid_until_str, 
                "source_name": "MusicBrainz",
                "mb_search_url": mb_search_url,
                "jasrac_search_url": jasrac_search_url,
                "karaoke_search_url": karaoke_url
            })
            print(f"[DEBUG - Match Existing] 既存楽曲ヒット: '{final_title}' (メトリクス更新)")
            return entry, master_db, False

    # 新曲検知 & MusicBrainz ISWC取得
    print(f"\n★ [DEBUG - New Song Fact Record] 新曲検知: 生タイトル '{raw_title}' ➔ 照合用表記: '{final_title}' ({final_artist})")
    iswc_code, src_name, src_url = get_iswc_musicbrainz(final_title, final_artist)

    is_risk = any(kw in (final_title + final_artist).lower() for kw in ["disney", "ディズニー", "nintendo", "任天堂", "hoyofair", "remix"]) or bool(risk_reason)

    if iswc_code:
        code_val = iswc_code
        status_val = "ISWCコード確認済み"
    else:
        code_val = "コード未取得"
        status_val = "手動検索を推奨 (JASRAC/NexTone等)"

    if is_risk:
        status_val += f" [注意: {risk_reason or '原盤・商標等確認推奨'}]"

    new_entry = {
        "title": raw_title,
        "artist": raw_artist,
        "jasrac_search_title": final_title,
        "jasrac_search_artist": final_artist,
        "jasrac_code": code_val,
        "status": status_val,
        "pub_date": pub_date,
        "source_name": "MusicBrainz",
        "source_url": src_url,
        "mb_search_url": mb_search_url,
        "jasrac_search_url": jasrac_search_url,
        "karaoke_search_url": karaoke_url,
        "verified_at": today_str,
        "valid_until": valid_until_str,
        "last_metrics": metrics,
        "added_date": today_str
    }
    master_db.append(new_entry)
    print(f"[DEBUG - Fact Recorded] ステータス: {status_val} | コード: {code_val}")
    return new_entry, master_db, True

def export_master_to_csv(master_db):
    """【全6カラム統合構成】README仕様書通りのカラム順でCSV出力"""
    os.makedirs('public/downloads', exist_ok=True)
    with open(CSV_OUTPUT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([
            'トレンド動画タイトル', 
            '再生数 / 反応率', 
            '権利コード / 許諾ステータス', 
            'JASRAC/NexTone 検索用キーワード', 
            '情報源 / 期限', 
            '原盤権対策 (音源)'
        ])
        for r in master_db:
            m = r.get('last_metrics', {})
            
            # 1. トレンド動画タイトル
            c1_title = f"{r.get('title')} (チャンネル: {r.get('artist')})"
            
            # 2. 再生数 / 反応率
            c2_metrics = f"再生数: {m.get('views', 0):,}回 | 反応率: {m.get('engagement_rate', 0.0)}% | 日速: {m.get('daily_views', 0):,}回"
            
            # 3. 権利コード / 許諾ステータス
            c3_rights = f"コード: {r.get('jasrac_code')} | ステータス: {r.get('status')}"
            
            # 4. JASRAC/NexTone 検索用キーワード
            c4_jasrac = f"曲名: {r.get('jasrac_search_title')} / 歌手: {r.get('jasrac_search_artist')} (照合URL: {r.get('jasrac_search_url')})"
            
            # 5. 情報源 / 期限
            mb_link = r.get('mb_search_url', '')
            c5_source = f"MusicBrainz: {mb_link} (確認日: {r.get('verified_at')} / 期限: {r.get('valid_until')})"
            
            # 6. 原盤権対策 (音源)
            c6_karaoke = r.get('karaoke_search_url', '')
            
            writer.writerow([c1_title, c2_metrics, c3_rights, c4_jasrac, c5_source, c6_karaoke])

def generate_llms_txt(songs, today_str):
    content = f"# Trend Song Rights & Verified Analytics Database\n\n> 最終更新日時: {today_str}\n> 本ファイルはAI検索エンジン向けの構造化ガイドです。\n\n> MusicBrainzについて: MetaBrainz Foundationが運営する国際音楽データベースであり、ISWCの照合において信頼性を備えています。\n\n## 直近のトレンド楽曲・許諾状況\n"
    for s in songs:
        m = s.get('metrics', {})
        content += f"- **{s['title']}** ({s['artist']}) | JASRAC検索名: {s.get('jasrac_search_title')} | 識別コード: {s['jasrac_code']} | ステータス: {s['rights_status']} | 情報源(MusicBrainz曲名検索): {s.get('mb_search_url')} | JASRAC検索: {s.get('jasrac_search_url')} | 歌枠用カラオケ: {s.get('karaoke_search_url')} | 確認日: {s['verified_at']} | 有効期限: {s['valid_until']} | 再生数: {m.get('views', 0):,}回 | エンゲージメント率: {m.get('engagement_rate', 0)}%\n"
    content += "\n## エンドポイント\n- JSON全データ: /api/v1/songs.json\n"
    os.makedirs('public', exist_ok=True)
    with open('public/llms.txt', 'w', encoding='utf-8') as f: f.write(content)

def get_real_youtube_trending_songs(master_db):
    print("\n[DEBUG - YouTube API] ===== 日本地域・音楽急上昇ランキングの取得を開始 =====")
    if not YOUTUBE_API_KEY:
        print("[DEBUG - YouTube API Error] ❌ YOUTUBE_API_KEYが設定されていません。")
        return master_db, False, []

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"part": "snippet,statistics", "chart": "mostPopular", "regionCode": "JP", "videoCategoryId": "10", "maxResults": 15, "key": YOUTUBE_API_KEY}

    try:
        res = requests.get(url, params=params, timeout=10)
        print(f"[DEBUG - YouTube API Response] HTTP Status: {res.status_code}")
        if res.status_code != 200:
            return master_db, False, []
        data = res.json()
    except Exception as e:
        print(f"[DEBUG - YouTube API Exception]: {e}")
        return master_db, False, []

    items = data.get("items", [])
    print(f"[DEBUG - YouTube API Success] ✅ {len(items)} 件の急上昇動画データを取得しました。")

    song_requests = []
    prepared_items = []
    for idx, item in enumerate(items, 1):
        snippet, stats = item["snippet"], item.get("statistics", {})
        raw_title = snippet.get("title", "")
        raw_artist = snippet.get("channelTitle", "").replace("Official", "").strip()
        views, likes, comments = int(stats.get("viewCount", 0)), int(stats.get("likeCount", 0)), int(stats.get("commentCount", 0))
        
        pub_date, pub_dt = parse_pub_date(snippet.get("publishedAt", ""))
        days = max(1, (datetime.datetime.now(datetime.timezone.utc) - pub_dt).days)
        metrics = {
            "views": views, "likes": likes, "comments": comments, 
            "engagement_rate": round(((likes + comments) / views * 100), 2) if views > 0 else 0.0, 
            "daily_views": int(views / days) if views > 0 else 0
        }

        song_requests.append({"id": str(idx), "raw_title": raw_title, "raw_artist": raw_artist})
        prepared_items.append({"raw_title": raw_title, "raw_artist": raw_artist, "pub_date": pub_date, "metrics": metrics, "req_id": str(idx)})

    gemini_batch_results = analyze_songs_batch_with_gemini(song_requests)

    db_updated, trending_songs = False, []
    for p_item in prepared_items:
        req_id = p_item["req_id"]
        ai_info = gemini_batch_results.get(req_id, {})
        
        entry, master_db, was_added = auto_enrich_and_get_rights(
            p_item["raw_title"], p_item["raw_artist"], p_item["pub_date"], p_item["metrics"], master_db, ai_info
        )
        if was_added: db_updated = True

        trending_songs.append({
            "title": entry["title"], "artist": entry["artist"],
            "jasrac_search_title": entry["jasrac_search_title"], "jasrac_search_artist": entry["jasrac_search_artist"],
            "jasrac_code": entry["jasrac_code"], "rights_status": entry["status"],
            "pub_date": entry["pub_date"], "source_name": entry["source_name"], "source_url": entry["source_url"],
            "mb_search_url": entry["mb_search_url"],
            "jasrac_search_url": entry["jasrac_search_url"],
            "karaoke_search_url": entry["karaoke_search_url"],
            "verified_at": entry["verified_at"], "valid_until": entry["valid_until"],
            "trend_score": min(99, max(50, 50 + int(p_item["metrics"]["views"] / 1000000))), "metrics": p_item["metrics"]
        })

    return master_db, db_updated, trending_songs

def main():
    print("==================================================")
    print("全自動マスターDB自己増殖＆検証エビデンスパイプラインを起動します")
    print("==================================================")
    today_str = get_dates()[0]
    master_db, db_updated, trending_songs = get_real_youtube_trending_songs(load_master_db())
    
    if db_updated:
        save_json(MASTER_DB_PATH, master_db)
        print(f"\n[DEBUG - DB Save] ★マスターDB更新完了! 総楽曲数: {len(master_db)}件")
    else:
        print("\n[DEBUG - DB Save] マスターDBに新規楽曲の追加はありませんでした。")
    
    export_master_to_csv(master_db)
    save_json('src/data/songs.json', trending_songs)
    generate_llms_txt(trending_songs, today_str)
    print("\n全自動パイプラインが正常終了しました。")

if __name__ == "__main__":
    main()