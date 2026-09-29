/* 极薄 API 封装：统一错误处理 */

async function toJson(res) {
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export const api = {
  meta: () => fetch("/api/meta").then(toJson),
  prizes: () => fetch("/api/prizes").then(toJson),
  draw: (game = "wheel") =>
    fetch("/api/draw", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game }),
    }).then(toJson),
  // 双钻自选确认：永不 reject——失败以 {error: 中文原因, status} 返回，便于选择框就地重试
  choose: async (token, prizeId) => {
    const res = await fetch("/api/slot/choose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, prize_id: prizeId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { error: data.detail || `HTTP ${res.status}`, status: res.status };
    return data;
  },
};
