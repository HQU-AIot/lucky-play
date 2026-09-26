/* 形式二：九宫格。3×3 外圈 8 格，高亮圈快→慢（步进间隔按 2.2 次幂曲线拉长），
   走灯总时长归一化为 RESULT_AT−定格 时长（与结果格远近无关），
   精准停在结果格，定格脉冲 + 中奖呼吸灯，4s 卡准歌里的"停"。 */

import { sleep } from "../easing.js";
import { RESULT_AT } from "../music.js?v=6";

// DOM 网格位置 0-8（中心为 4）中，顺时针外圈顺序
const RING = [0, 1, 2, 5, 8, 7, 6, 3];
const HOLD_MS = 750; // 中定格脉冲时长，走灯 = RESULT_AT*1000 − HOLD_MS

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="grid9-box">
      <div class="grid9"></div>
      <p class="stage-hint">灯圈越走越慢，心跳越来越快</p>
    </div>`;
  const grid = stage.querySelector(".grid9");
  const cells = [];
  let running = false;

  function render() {
    grid.innerHTML = "";
    cells.length = 0;
    for (let pos = 0; pos < 9; pos++) {
      if (pos === 4) {
        const hub = document.createElement("button");
        hub.className = "g-hub";
        hub.type = "button";
        hub.textContent = "开抽";
        hub.addEventListener("click", () => start());
        grid.appendChild(hub);
        cells.push(null);
        continue;
      }
      const cell = document.createElement("div");
      cell.className = "g-cell";
      grid.appendChild(cell);
      cells.push(cell);
    }
    paint();
  }

  function paint() {
    ctx.items().forEach((item, j) => {
      const cell = cells[RING[j]];
      cell.innerHTML = `<span class="g-emoji">${item.emoji}</span><span class="g-name">${item.name}</span>`;
    });
  }

  async function start() {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    stage.querySelector(".g-hub").disabled = true;

    const items = ctx.items();
    const targetId = result.result === "prize" ? result.prize.id : "thanks";
    const target = Math.max(0, items.findIndex((it) => it.id === targetId));

    const laps = ctx.reduced ? 1 : 3;
    const steps = laps * 8 + target;
    // 归一化：解出曲线系数，使 Σ(baseMs + curve·t^2.2) 恒等于走灯总时长
    let curveSum = 0;
    for (let k = 1; k <= steps; k++) curveSum += Math.pow(k / steps, 2.2);
    const baseMs = 40;
    const curveMs = (RESULT_AT * 1000 - HOLD_MS - baseMs * steps) / curveSum;
    let cursor = 0;

    for (let k = 1; k <= steps; k++) {
      cursor = k % 8;
      cells.forEach((c) => c && c.classList.remove("is-lit"));
      const cell = cells[RING[cursor]];
      cell.classList.add("is-lit");
      const intensity = 1 - k / steps;
      ctx.fx.sound.tick(0.25 + intensity * 0.6);
      const t = k / steps;
      await sleep(ctx.reduced ? 30 : baseMs + curveMs * Math.pow(t, 2.2));
    }

    const winCell = cells[RING[target]];
    winCell.classList.remove("is-lit");
    winCell.classList.add("is-lit", "is-winner");
    await sleep(ctx.reduced ? 100 : HOLD_MS);

    const choice = await ctx.reveal(result);
    ctx.refresh();
    winCell.classList.remove("is-winner", "is-lit");
    running = false;
    stage.querySelector(".g-hub").disabled = false;
    if (choice === "again") setTimeout(() => start(), 200);
  }

  const onTheme = () => paint();
  const onPrizes = () => paint();
  window.addEventListener("lucky:theme", onTheme);
  window.addEventListener("lucky:prizes", onPrizes);
  render();

  return {
    destroy() {
      window.removeEventListener("lucky:theme", onTheme);
      window.removeEventListener("lucky:prizes", onPrizes);
    },
  };
}
