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
  // 双钻自选确认：失败以 {error: 中文原因, status} 返回，便于选择框就地重试。
  // fetch 网络层失败（断网/服务不可达）也一并兜住，不让 reject 漏给调用方
  choose: async (token, prizeId) => {
    try {
      const res = await fetch("/api/slot/choose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, prize_id: prizeId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { error: data.detail || `HTTP ${res.status}`, status: res.status };
      return data;
    } catch {
      return { error: "网络开小差了，再试一次", status: 0 };
    }
  },
};
