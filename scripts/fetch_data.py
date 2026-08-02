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

def analyze_trending_songs_batch_with_gemini(raw_songs_list):
    """【Gemini API】超高速＆429エラー回避版 1リクエスト一括AI分析"""
    print(f"\n[DEBUG - Gemini API] ===== 1リクエスト一括AI分析を開始 ({len(raw_songs_list)}曲) =====")
    
    if not GEMINI_API_KEY or not raw_songs_list:
        print("  [DEBUG - Gemini API] ⚠️ GEMINI_API_KEY未設定のため、簡易正規表現フォールバック適用")
        return [{"official_title": re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', s["raw_title"]).strip() or s["raw_title"],
                 "official_artist": s["raw_artist"], "risk_reason": ""} for s in raw_songs_list]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    songs_text = "\n".join([f"{i+1}. タイトル: \"{s['raw_title']}\" / チャンネル: \"{s['raw_artist']}\"" for i, s in enumerate(raw_songs_list)])

    prompt = f"""
以下のYouTube動画リスト（全{len(raw_songs_list)}件）から、それぞれの原曲の「正確な原曲タイトル」と「正確な原曲アーティスト名（またはボカロP/作詞作曲者名）」を分析・抽出してください。

【対象動画リスト】
{songs_text}

【抽出ルール】
1. 「MV」「歌ってみた」「Official」「Cover」「Live」「特報」などのノイズ表記は完全に除去してください。
2. カバー動画や歌枠、ダンス動画等の場合、出演配信者ではなく「原曲のアーティスト名/ボカロP名」を抽出してください。
3. 任天堂・ディズニー・ゲームBGM・東方Project等、個別許諾が必要な場合は risk_reason に明記してください。
4. 必ず入力されたリストと同じ順番のJSON配列（リスト）のみを出力してください（解説文不要）。

【出力形式】
[
  {{
    "index": 1,
    "official_title": "正式な楽曲名",
    "official_artist": "正式な原曲アーティスト名",
    "risk_reason": "リスクや注意点（無ければ空文字）"
  }}
]
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        # ★429回避のため googleSearch ツールを外し、Gemini高精度テキスト抽出に専念
        "generationConfig": {"temperature": 0.0}
    }

    for attempt in range(3):
        try:
            start_time = time.time()
            res = requests.post(url, json=payload, timeout=12)
            elapsed = round(time.time() - start_time, 2)
            print(f"  [DEBUG - Gemini API Response] HTTP Status: {res.status_code} (応答時間: {elapsed}秒)")
            
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                json_match = re.search(r'\[.*\]', text, re.DOTALL)
                if json_match:
                    parsed_data = json.loads(json_match.group(0))
                    print(f"  [DEBUG - Gemini API Success] ✅ {len(parsed_data)}件の正解情報を抽出しました。")
                    for item in parsed_data[:3]:
                        print(f"    - Preview: '{item.get('official_title')}' ({item.get('official_artist')}) [Risk: '{item.get('risk_reason', 'なし')}']")
                    return parsed_data
            elif res.status_code == 429:
                wait_time = (attempt + 1) * 3
                print(f"  [DEBUG - Gemini API 429] レート制限検知。{wait_time}秒待機後にリトライ ({attempt + 1}/3)...")
                time.sleep(wait_time)
            else:
                print(f"  [DEBUG - Gemini API Error]: {res.text[:200]}")
        except Exception as e:
            print(f"  [DEBUG - Gemini API Exception]: {e}")
            time.sleep(2)

    return [{"official_title": re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', s["raw_title"]).strip() or s["raw_title"],
             "official_artist": s["raw_artist"], "risk_reason": ""} for s in raw_songs_list]

def get_official_info_itunes(title, artist):
    """【iTunes API】誤爆防止フィルタ付き照合"""
    query = f"{artist} {title}".strip()
    url = "https://itunes.apple.com/search"
    params = {"term": query, "country": "JP", "media": "music", "entity": "song", "limit": 1}
    
    print(f"  [DEBUG - iTunes API Request] Query: '{query}'")
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200 and (results := res.json().get("results")):
            t_name = results[0].get("trackName", title)
            a_name = results[0].get("artistName", artist)
            
            # ★誤爆防止フィルタ：iTunesが全く関係ない曲を返した場合は不採用にする
            # 検索クエリの単語が全くヒットに含まれない場合はスキップ
            t_low, q_low = t_name.lower(), title.lower()
            if any(part in t_low for part in q_low.split() if len(part) > 1) or any(part in q_low for part in t_low.split() if len(part) > 1):
                print(f"    -> [iTunes Hit] 公式表記確定: '{t_name}' ({a_name})")
                return t_name, a_name
            else:
                print(f"    -> [iTunes Filtered] 誤判定リスク回避（不採用）: '{t_name}' ➔ 元のタイトル保持: '{title}'")
    except Exception as e:
        print(f"    -> [iTunes Exception]: {e}")
    return title, artist

def get_iswc_musicbrainz(title, artist):
    """【MusicBrainz API】503リトライ付き ISWC 照合"""
    clean_artist = artist.split()[0] if artist else ""
    query = f'work:"{escape_lucene(title)}"' + (f' AND artist:"{escape_lucene(clean_artist)}"' if clean_artist else "")
    url = "https://musicbrainz.org/ws/2/work/"
    headers = {"User-Agent": "ViralSongRightsBot/2.2 (https://github.com/example/viral-song-rights-db)"}
    
    print(f"  [DEBUG - MusicBrainz API Request] Query: '{query}'")
    for attempt in range(2): # 503エラー時最大2回リトライ
        time.sleep(1.2) # Rate Limit 遵守
        try:
            res = requests.get(url, params={"query": query, "fmt": "json", "limit": 1}, headers=headers, timeout=8)
            print(f"  [DEBUG - MusicBrainz API Response] Status: {res.status_code}")
            if res.status_code == 200:
                works = res.json().get("works", [])
                if works:
                    work_id = works[0].get("id")
                    src_url = f"https://musicbrainz.org/work/{work_id}" if work_id else "https://musicbrainz.org"
                    iswcs = works[0].get("iswcs", [])
                    if iswcs:
                        print(f"    -> [MusicBrainz Hit] ✅ ISWC取得成功: {iswcs[0]}")
                        return f"ISWC:{iswcs[0]}", "MusicBrainz API", src_url
                    print(f"    -> [MusicBrainz Work Found] ワーク発見(ID: {work_id})、しかしISWCコード未登録")
                    return None, "MusicBrainz API", src_url
                print("    -> [MusicBrainz Miss] 該当ワークなし")
                return None, "YouTube Comprehensive Engine", "https://www.youtube.com/t/terms"
            elif res.status_code == 503:
                print("    -> [MusicBrainz 503] 一時的サーバー負荷。1.5秒後にリトライします...")
                time.sleep(1.5)
        except Exception as e:
            print(f"    -> [MusicBrainz Exception]: {e}")
            
    return None, "YouTube Comprehensive Engine", "https://www.youtube.com/t/terms"

def load_master_db():
    today_str, valid_until_str = get_dates()
    if os.path.exists(MASTER_DB_PATH):
        try:
            with open(MASTER_DB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"[DEBUG - DB Load] 既存のマスターDBを読み込みました (全 {len(data)} 件)")
                for entry in data:
                    entry.pop("season_tag", None)
                    entry.setdefault("last_metrics", {"views": 0, "likes": 0, "comments": 0, "engagement_rate": 0.0, "daily_views": 0})
                    entry.setdefault("source_name", "YouTube / MusicBrainz API")
                    entry.setdefault("source_url", "https://musicbrainz.org")
                    entry.setdefault("verified_at", entry.get("added_date", today_str))
                    entry.setdefault("valid_until", valid_until_str)
                    entry.setdefault("jasrac_search_title", entry.get("title"))
                    entry.setdefault("jasrac_search_artist", entry.get("artist"))
                    entry.setdefault("karaoke_search_url", f"https://www.youtube.com/results?search_query={urllib.parse.quote(entry.get('artist','') + ' ' + entry.get('title','') + ' カラオケ 歌枠用')}")
                return data
        except Exception as e: print(f"[DEBUG - DB Load Error]: {e}")
    print("[DEBUG - DB Load] マスターDBが存在しないため、新規空DB作成モードで開始します。")
    return []

def auto_enrich_and_get_rights(raw_title, raw_artist, ai_info, pub_date, metrics, master_db):
    today_str, valid_until_str = get_dates()
    
    clean_title = ai_info.get("official_title", raw_title)
    clean_artist = ai_info.get("official_artist", raw_artist)
    risk_reason = ai_info.get("risk_reason", "")

    # iTunes ダブルチェック & 誤爆フィルタ
    final_title, final_artist = get_official_info_itunes(clean_title, clean_artist)
    karaoke_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(f'{final_artist} {final_title} カラオケ 歌枠用')}"

    # 既存DB照合
    t_low = final_title.lower()
    for entry in master_db:
        e_title = entry.get("jasrac_search_title", entry.get("title", "")).lower()
        if e_title in t_low or t_low in e_title:
            entry.update({"last_metrics": metrics, "verified_at": today_str, "valid_until": valid_until_str, "karaoke_search_url": karaoke_url})
            print(f"[DEBUG - Match Existing] 既存楽曲ヒット: '{final_title}' (メトリクス更新)")
            return entry, master_db, False

    # 新曲検知 & MusicBrainz 検索
    print(f"\n★ [DEBUG - New Song Detect] 新曲検知: 生タイトル '{raw_title}' ➔ Gemini補正: '{final_title}' ({final_artist})")
    iswc_code, src_name, src_url = get_iswc_musicbrainz(final_title, final_artist)

    # シビア判定
    is_ng = any(kw in (final_title + final_artist).lower() for kw in ["disney", "ディズニー", "nintendo", "任天堂", "hoyofair", "remix"]) or bool(risk_reason)

    if is_ng:
        code = "権利注意 (要権利者個別確認)"
        status = f"NG / 要個別確認 ({risk_reason or 'ディズニー・任天堂・ゲーム音源等リスク'})"
    elif iswc_code:
        code = iswc_code
        status = "OK (ISWC照合完了 / YouTube包括対象)"
    else:
        code = "JASRAC/NexToneポータル要検索"
        status = "要個別確認 (自動照合未完了 / 手動検索を推奨)"

    new_entry = {
        "title": raw_title,
        "artist": raw_artist,
        "jasrac_search_title": final_title,
        "jasrac_search_artist": final_artist,
        "jasrac_code": code,
        "status": status,
        "pub_date": pub_date,
        "source_name": src_name,
        "source_url": src_url,
        "karaoke_search_url": karaoke_url,
        "verified_at": today_str,
        "valid_until": valid_until_str,
        "last_metrics": metrics,
        "added_date": today_str
    }
    master_db.append(new_entry)
    print(f"[DEBUG - Rights Final Status] 判定結果: {status} | Code: {code}")
    return new_entry, master_db, True

def export_master_to_csv(master_db):
    os.makedirs('public/downloads', exist_ok=True)
    with open(CSV_OUTPUT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['曲名(YouTube生表示)', 'アーティスト(チャンネル名)', 'JASRAC検索用曲名', 'JASRAC検索用アーティスト', '権利識別コード', '配信許諾ステータス', 'リリース日', '季節タグ', '情報源', '一次ソースURL', 'カラオケ音源(原盤)検索URL', '権利確認日', '推奨有効期限', '総再生数', '高評価数', 'コメント数', 'エンゲージメント率(%)', '日速再生数', 'DB登録日'])
        for r in master_db:
            m, p = r.get('last_metrics', {}), r.get('pub_date', '')
            writer.writerow([r.get('title'), r.get('artist'), r.get('jasrac_search_title'), r.get('jasrac_search_artist'), r.get('jasrac_code'), r.get('status'), p, get_season_tag(p), r.get('source_name'), r.get('source_url'), r.get('karaoke_search_url'), r.get('verified_at'), r.get('valid_until'), m.get('views', 0), m.get('likes', 0), m.get('comments', 0), m.get('engagement_rate', 0.0), m.get('daily_views', 0), r.get('added_date')])

def generate_llms_txt(songs, today_str):
    content = f"# Trend Song Rights & Verified Analytics Database\n\n> 最終更新日時: {today_str}\n> 本ファイルはAI検索エンジン向けの構造化ガイドです。\n\n> MusicBrainzについて: MetaBrainz Foundationが運営する国際音楽データベースであり、ISWCの照合において信頼性を備えています。\n\n## 直近のトレンド楽曲・許諾状況\n"
    for s in songs:
        m = s.get('metrics', {})
        content += f"- **{s['title']}** ({s['artist']}) | JASRAC検索名: {s.get('jasrac_search_title')} | 識別コード: {s['jasrac_code']} | ステータス: {s['rights_status']} | 情報源: {s['source_name']} ({s['source_url']}) | 歌枠用カラオケ: {s.get('karaoke_search_url')} | 確認日: {s['verified_at']} | 有効期限: {s['valid_until']} | 再生数: {m.get('views', 0):,}回 | エンゲージメント率: {m.get('engagement_rate', 0)}%\n"
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

    raw_songs_list = []
    for item in items:
        snippet, stats = item["snippet"], item.get("statistics", {})
        raw_title = snippet.get("title", "")
        raw_artist = snippet.get("channelTitle", "").replace("Official", "").strip()
        views, likes, comments = int(stats.get("viewCount", 0)), int(stats.get("likeCount", 0)), int(stats.get("commentCount", 0))
        
        pub_date, pub_dt = parse_pub_date(snippet.get("publishedAt", ""))
        days = max(1, (datetime.datetime.now(datetime.timezone.utc) - pub_dt).days)
        metrics = {"views": views, "likes": likes, "comments": comments, "engagement_rate": round(((likes + comments) / views * 100), 2) if views > 0 else 0.0, "daily_views": int(views / days)}

        raw_songs_list.append({"raw_title": raw_title, "raw_artist": raw_artist, "pub_date": pub_date, "metrics": metrics})

    # Gemini 1リクエスト一括AI分析
    ai_batch_results = analyze_trending_songs_batch_with_gemini(raw_songs_list)

    print("\n[DEBUG - Pipeline Core] ===== 各楽曲の照合 & DB更新を開始 =====")
    db_updated, trending_songs = False, []
    for i, item in enumerate(raw_songs_list):
        ai_info = ai_batch_results[i] if i < len(ai_batch_results) else {}
        
        entry, master_db, was_added = auto_enrich_and_get_rights(
            item["raw_title"], item["raw_artist"], ai_info, item["pub_date"], item["metrics"], master_db
        )
        if was_added: db_updated = True

        trending_songs.append({
            "title": entry["title"], "artist": entry["artist"],
            "jasrac_search_title": entry["jasrac_search_title"], "jasrac_search_artist": entry["jasrac_search_artist"],
            "jasrac_code": entry["jasrac_code"], "rights_status": entry["status"],
            "pub_date": entry["pub_date"], "source_name": entry["source_name"], "source_url": entry["source_url"],
            "karaoke_search_url": entry["karaoke_search_url"],
            "verified_at": entry["verified_at"], "valid_until": entry["valid_until"],
            "trend_score": min(99, max(50, 50 + int(item["metrics"]["views"] / 1000000))), "metrics": item["metrics"]
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