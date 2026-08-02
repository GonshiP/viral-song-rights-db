import songs from '../../../../src/data/songs.json';

// 静的ビルド（SSG）として出力するための設定
export const prerender = true;

export async function GET() {
  return new Response(
    JSON.stringify({
      status: "success",
      updated_at: new Date().toISOString(),
      total_records: songs.length,
      data: songs,
    }),
    {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "s-maxage=86400, stale-while-revalidate"
      }
    }
  );
}