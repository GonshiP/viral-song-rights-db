import json, os, sys

def test_history_index():
    assert os.path.exists('src/data/history_index.json'), 'history_index.json が存在しない'
    with open('src/data/history_index.json', 'r', encoding='utf-8') as f:
        idx = json.load(f)
    assert len(idx) >= 2, f'履歴が2日分以上必要: {len(idx)}日分'
    print(f'[PASS] history_index.json OK: {len(idx)} 日分')

def test_snapshots():
    for date in ['2026-08-02', '2026-08-03']:
        snap = f'src/data/history/{date}.json'
        assert os.path.exists(snap), f'{snap} が存在しない'
        with open(snap, 'r', encoding='utf-8') as f:
            d = json.load(f)
        assert len(d) > 0, f'{snap} が空'
        print(f'[PASS] history/{date}.json OK: {len(d)} 件')

def test_metrics_history():
    with open('src/data/history/2026-08-03.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    for song in d[:3]:
        title = song.get('title', 'unknown')
        assert 'metrics_history' in song, f'metrics_history なし: {title}'
        assert isinstance(song['metrics_history'], list), 'metrics_history はlist型であること'
    print('[PASS] metrics_history フィールド確認 OK')

def test_master_db():
    with open('src/data/rights_master.json', 'r', encoding='utf-8') as f:
        master = json.load(f)
    has_hist = [e for e in master if 'metrics_history' in e]
    print(f'[PASS] rights_master.json: {len(has_hist)}/{len(master)} 件に metrics_history あり')

def test_songs_json():
    with open('src/data/songs.json', 'r', encoding='utf-8') as f:
        songs = json.load(f)
    assert len(songs) > 0, 'songs.json が空'
    has_raw = [s for s in songs if s.get('raw_youtube')]
    print(f'[PASS] songs.json: {len(songs)} 件, うち {len(has_raw)} 件に raw_youtube あり')

def test_fetch_data_syntax():
    import ast
    with open('scripts/fetch_data.py', 'r', encoding='utf-8') as f:
        src = f.read()
    try:
        ast.parse(src)
        print('[PASS] fetch_data.py: Python AST構文 OK')
    except SyntaxError as e:
        print(f'[FAIL] SyntaxError: {e}')
        sys.exit(1)

if __name__ == '__main__':
    print('=== パイプライン整合性テスト開始 ===')
    tests = [
        test_fetch_data_syntax,
        test_history_index,
        test_snapshots,
        test_metrics_history,
        test_master_db,
        test_songs_json,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f'[FAIL] {t.__name__}: {e}')
            failed += 1
    print()
    if failed == 0:
        print('=== 全テスト完了 ✅ ===')
    else:
        print(f'=== {failed} 件のテスト失敗 ===')
        sys.exit(1)
