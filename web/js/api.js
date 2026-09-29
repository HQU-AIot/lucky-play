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
};
