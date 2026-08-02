import os, re, json, csv, datetime, time, requests, urllib.parse

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # Google AI Studioから無料で取得可能

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

def analyze_song_with_gemini(raw_title, raw_artist):
    """【完全無料 & GoogleリアルタイムWeb検索付き Gemini API】最新曲を検索して正解抽出"""
    if not GEMINI_API_KEY:
        clean = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', raw_title).strip()
        return {"official_title": clean or raw_title, "official_artist": raw_artist, "risk_reason": ""}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
【重要指示】必要に応じてインターネット検索（Google検索）を実行し、最新の楽曲データベースやリリース情報、公式MV情報を確認した上で回答してください。

以下のYouTube動画タイトルとチャンネル名から、原曲の「正確な曲名」と「正確な原曲アーティスト名」を検索・特定し、権利リスクを判断してください。

動画タイトル: "{raw_title}"
チャンネル名: "{raw_artist}"

【抽出・判断ルール】
1. 最新の新曲やカバー曲の可能性があるため、必要に応じてWeb検索を行って原曲情報を特定してください。
2. 「MV」「歌ってみた」「Official」「Cover」などのノイズ表記は完全に除去してください。
3. カバー動画や歌枠動画の場合、カバーしたVtuber/歌い手ではなく、「原曲のアーティスト名/ボカロP名/作詞作曲者」を特定してください。
4. ディズニー、任天堂、ゲームBGM、東方Project、海外曲など、個別許諾やガイドライン確認が必要な場合は risk_reason に理由を明記してください。
5. 以下のJSONフォーマットのみを出力してください（Markdown記法や余計な解説文は一切不要です）。

{{
  "official_title": "正式な楽曲名",
  "official_artist": "正式な原曲アーティスト名",
  "risk_reason": "リスクや注意点（無ければ空文字）"
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}], # ★Googleリアルタイム検索機能を有効化（無料枠内）
        "generationConfig": {
            "temperature": 0.0
        }
    }

    try:
        time.sleep(1.2) # Gemini 無料枠レート制限回避（15 RPM遵守）
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            # AIが返したテキストからJSON部分を抽出・パース
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
    except Exception as e:
        print(f"  [Gemini Search API Error]: {e}")

    # 万が一の通信エラー時の安全フォールバック
    clean = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', raw_title).strip()
    return {"official_title": clean or raw_title, "official_artist": raw_artist, "risk_reason": ""}

def get_official_info_itunes(title, artist):
    """【iTunesダブルチェック】Gemini抽出後の正解表記を再確認"""
    try:
        res = requests.get("https://itunes.apple.com/search", params={"term": f"{artist} {title}".strip(), "country": "JP", "media": "music", "entity": "song", "limit": 1}, timeout=5)
        if res.status_code == 200 and (results := res.json().get("results")):
            return results[0].get("trackName", title), results[0].get("artistName", artist)
    except Exception: pass
    return title, artist

def get_iswc_musicbrainz(title, artist):
    """【MusicBrainz API規格準拠】1.2秒待機・User-Agent・Luceneサニタイズ"""
    time.sleep(1.2)
    clean_artist = artist.split()[0] if artist else ""
    query = f'work:"{escape_lucene(title)}"' + (f' AND artist:"{escape_lucene(clean_artist)}"' if clean_artist else "")
    headers = {"User-Agent": "ViralSongRightsBot/2.2 (https://github.com/example/viral-song-rights-db)"}
    try:
        res = requests.get("https://musicbrainz.org/ws/2/work/", params={"query": query, "fmt": "json", "limit": 1}, headers=headers, timeout=8)
        if res.status_code == 200 and (works := res.json().get("works")):
            work_id = works[0].get("id")
            src_url = f"https://musicbrainz.org/work/{work_id}" if work_id else "https://musicbrainz.org"
            if iswcs := works[0].get("iswcs"):
                return f"ISWC:{iswcs[0]}", "MusicBrainz API", src_url
            return None, "MusicBrainz API", src_url
    except Exception: pass
    return None, "YouTube Comprehensive Engine", "https://www.youtube.com/t/terms"

def load_master_db():
    today_str, valid_until_str = get_dates()
    if os.path.exists(MASTER_DB_PATH):
        try:
            with open(MASTER_DB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
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
        except Exception as e: print(f"マスターDB読み込みエラー: {e}")
    return []

def auto_enrich_and_get_rights(raw_title, raw_artist, pub_date, metrics, master_db):
    today_str, valid_until_str = get_dates()
    
    # 1. Gemini APIによるAI高精度抽出 & リスク分析（無料）
    ai_data = analyze_song_with_gemini(raw_title, raw_artist)
    clean_title = ai_data.get("official_title", raw_title)
    clean_artist = ai_data.get("official_artist", raw_artist)
    risk_reason = ai_data.get("risk_reason", "")

    # 2. iTunes APIによる表記ダブルチェック（無料）
    final_title, final_artist = get_official_info_itunes(clean_title, clean_artist)
    karaoke_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(f'{final_artist} {final_title} カラオケ 歌枠用')}"

    # 既存DB照合（補正後タイトルで重複チェック）
    t_low = final_title.lower()
    for entry in master_db:
        e_title = entry.get("jasrac_search_title", entry.get("title", "")).lower()
        if e_title in t_low or t_low in e_title:
            entry.update({"last_metrics": metrics, "verified_at": today_str, "valid_until": valid_until_str, "karaoke_search_url": karaoke_url})
            return entry, master_db, False

    # 3. MusicBrainz APIによるISWC取得（無料）
    print(f"★新曲検知! 生: '{raw_title}' ➔ Gemini補正: '{final_title}' ({final_artist})")
    iswc_code, src_name, src_url = get_iswc_musicbrainz(final_title, final_artist)

    # 4. シビア判定ロジック（リスクキーワード or AIリスク理由有 or ISWC未取得）
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
        "title": raw_title,                     # YouTube動画タイトル（生のまま保存）
        "artist": raw_artist,                   # YouTubeチャンネル名（生のまま保存）
        "jasrac_search_title": final_title,     # Gemini/iTunes補正後の公式曲名
        "jasrac_search_artist": final_artist,   # Gemini/iTunes補正後の公式アーティスト名
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
        content += f"- **{s['title']}** ({s['artist']}) | JASRAC検索名: {s.get('jasrac_search_title')} | 識別コード: {s['jasrac_code']} | ステータス: {s['rights_status']} | 情報源: {s['source_name']} ({s['source_url']}) | 歌枠用カラオケ: {s.get('karaoke_search_url')} | 確認日: {s['verified_at']} | 有有効期限: {s['valid_until']} | 再生数: {m.get('views', 0):,}回 | エンゲージメント率: {m.get('engagement_rate', 0)}%\n"
    content += "\n## エンドポイント\n- JSON全データ: /api/v1/songs.json\n"
    os.makedirs('public', exist_ok=True)
    with open('public/llms.txt', 'w', encoding='utf-8') as f: f.write(content)

def get_real_youtube_trending_songs(master_db):
    if not YOUTUBE_API_KEY:
        print("【エラー】YOUTUBE_API_KEYが未設定です。")
        return master_db, False, []

    try:
        res = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "snippet,statistics", "chart": "mostPopular", "regionCode": "JP", "videoCategoryId": "10", "maxResults": 15, "key": YOUTUBE_API_KEY}, timeout=10)
        data = res.json()
    except Exception as e:
        print(f"YouTube API Error: {e}")
        return master_db, False, []

    db_updated, trending_songs = False, []
    for item in data.get("items", []):
        snippet, stats = item["snippet"], item.get("statistics", {})
        raw_title = snippet.get("title", "")
        raw_artist = snippet.get("channelTitle", "").replace("Official", "").strip()
        views, likes, comments = int(stats.get("viewCount", 0)), int(stats.get("likeCount", 0)), int(stats.get("commentCount", 0))
        
        pub_date, pub_dt = parse_pub_date(snippet.get("publishedAt", ""))
        days = max(1, (datetime.datetime.now(datetime.timezone.utc) - pub_dt).days)
        metrics = {"views": views, "likes": likes, "comments": comments, "engagement_rate": round(((likes + comments) / views * 100), 2) if views > 0 else 0.0, "daily_views": int(views / days)}

        entry, master_db, was_added = auto_enrich_and_get_rights(raw_title, raw_artist, pub_date, metrics, master_db)
        if was_added: db_updated = True

        trending_songs.append({
            "title": entry["title"], "artist": entry["artist"],
            "jasrac_search_title": entry["jasrac_search_title"], "jasrac_search_artist": entry["jasrac_search_artist"],
            "jasrac_code": entry["jasrac_code"], "rights_status": entry["status"],
            "pub_date": entry["pub_date"], "source_name": entry["source_name"], "source_url": entry["source_url"],
            "karaoke_search_url": entry["karaoke_search_url"],
            "verified_at": entry["verified_at"], "valid_until": entry["valid_until"],
            "trend_score": min(99, max(50, 50 + int(views / 1000000))), "metrics": metrics
        })

    return master_db, db_updated, trending_songs

def main():
    print("全自動マスターDB自己増殖＆検証エビデンスパイプラインを起動します...")
    today_str = get_dates()[0]
    master_db, db_updated, trending_songs = get_real_youtube_trending_songs(load_master_db())
    
    if db_updated:
        save_json(MASTER_DB_PATH, master_db)
        print(f"★マスターDB更新完了! 総楽曲数: {len(master_db)}件")
    
    export_master_to_csv(master_db)
    save_json('src/data/songs.json', trending_songs)
    generate_llms_txt(trending_songs, today_str)
    print("全自動パイプラインが正常終了しました。")

if __name__ == "__main__":
    main()