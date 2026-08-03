import historyIndex from '../../../../src/data/history_index.json';

export const prerender = true;

export async function GET() {
  return new Response(
    JSON.stringify({
      status: "success",
      updated_at: new Date().toISOString(),
      total_days: historyIndex.length,
      history: historyIndex,
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
