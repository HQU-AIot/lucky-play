/* 形式二：九宫格。3×3 全 9 格（8 奖品 + 谢谢参与），开始按钮在网格下方；
   高亮圈沿环线（外圈 8 格 + 中心）顺时针走，步进间隔按 2.2 次幂曲线拉长（快→慢），
   走灯总时长归一化为 RESULT_AT−定格（与结果格远近无关），
   精准停在结果格，定格脉冲 + 中奖呼吸灯，5s 卡准歌里的"停"。 */

import { sleep } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";

// DOM 网格位置 0-8 的环走顺序：外圈顺时针一圈，最后走进中心格
const RING = [0, 1, 2, 5, 8, 7, 6, 3, 4];
const HOLD_MS = 750; // 定格脉冲时长，走灯 = RESULT_AT*1000 − HOLD_MS

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="grid9-box">
      <div class="grid9"></div>
      <button type="button" class="btn-primary g-start">开抽</button>
      <p class="stage-hint">灯圈越走越慢，心跳越来越快</p>
    </div>`;
  const grid = stage.querySelector(".grid9");
  const startBtn = stage.querySelector(".g-start");
  const cells = [];
  let running = false;

  function render() {
    grid.innerHTML = "";
    cells.length = 0;
    for (let pos = 0; pos < 9; pos++) {
      const cell = document.createElement("div");
      cell.className = "g-cell";
      grid.appendChild(cell);
      cells.push(cell);
    }
    paint();
  }

  function paint() {
    const items = ctx.items().slice(0, 9); // 超过 9 项只展示前 9（与盲盒口径一致）
    // 奖品数少于 9 时隐藏多余格（走灯环线同步跳过，见 activeRing）
    cells.forEach((c) => (c.hidden = false));
    for (let j = items.length; j < RING.length; j++) cells[RING[j]].hidden = true;
    items.forEach((item, j) => {
      cells[RING[j]].innerHTML = `<span class="g-emoji">${item.emoji}</span><span class="g-name">${item.name}</span>`;
    });
  }

  // 当前参与走灯的格子（按环走顺序）
  function activeRing() {
    return RING.filter((pos) => cells[pos] && !cells[pos].hidden);
  }

  async function start() {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    startBtn.disabled = true;

    const items = ctx.items();
    const ring = activeRing();
    const targetId = result.result === "prize" ? result.prize.id : "thanks";
    const target = Math.max(0, items.findIndex((it) => it.id === targetId));

    const laps = ctx.reduced ? 1 : 3;
    const steps = laps * ring.length + target;
    // 归一化：解出曲线系数，使 Σ(baseMs + curve·t^2.2) 恒等于走灯总时长
    let curveSum = 0;
    for (let k = 1; k <= steps; k++) curveSum += Math.pow(k / steps, 2.2);
    const baseMs = 40;
    const curveMs = (RESULT_AT * 1000 - HOLD_MS - baseMs * steps) / curveSum;
    let cursor = 0;

    for (let k = 1; k <= steps; k++) {
      cursor = k % ring.length;
      ring.forEach((pos) => cells[pos].classList.remove("is-lit"));
      const cell = cells[ring[cursor]];
      // 拖尾：上一格短暂保留余晖，灯圈走起来更有"电流感"
      const prev = cells[ring[(k - 1) % ring.length]];
      if (prev && prev !== cell) {
        prev.classList.add("is-trail");
        clearTimeout(prev._trailT);
        prev._trailT = setTimeout(() => prev.classList.remove("is-trail"), 240);
      }
      cell.classList.add("is-lit");
      const intensity = 1 - k / steps;
      ctx.fx.sound.tick(0.25 + intensity * 0.6);
      const t = k / steps;
      await sleep(ctx.reduced ? 30 : baseMs + curveMs * Math.pow(t, 2.2));
    }

    const winCell = cells[ring[target]];
    ring.forEach((pos) => cells[pos].classList.remove("is-trail"));
    winCell.classList.remove("is-lit");
    winCell.classList.add("is-lit", "is-winner");
    await sleep(ctx.reduced ? 100 : HOLD_MS);

    const choice = await ctx.reveal(result);
    ctx.refresh();
    winCell.classList.remove("is-winner", "is-lit");
    running = false;
    startBtn.disabled = false;
    if (choice === "again") setTimeout(() => start(), 200);
  }

  startBtn.addEventListener("click", start);
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
