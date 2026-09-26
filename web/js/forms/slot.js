/* 形式五：老虎机。三列滚轮独立减速、错峰停定；
   结果先行——停格前三格内容都换成中奖奖品，落定亮灯。 */

import { easeOutCubic, rand } from "../easing.js";

const CELLS = 24;
const CELL_FALLBACK_H = 132;

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="slot-box">
      <div class="slot-machine">
        <div class="slot-marquee"><span>★ 幸运老虎机 ★</span></div>
        <div class="slot-windows">
          <div class="slot-window"><div class="slot-reel"></div></div>
          <div class="slot-window"><div class="slot-reel"></div></div>
          <div class="slot-window"><div class="slot-reel"></div></div>
          <div class="slot-payline"></div>
        </div>
        <button class="btn-primary slot-btn" type="button">开抽</button>
      </div>
      <p class="stage-hint">三滚轮停定，灯亮开奖</p>
    </div>`;

  const btn = stage.querySelector(".slot-btn");
  const windows = [...stage.querySelectorAll(".slot-window")];
  const reels = windows.map((w) => w.querySelector(".slot-reel"));
  let running = false;

  function buildReels() {
    const items = ctx.items();
    reels.forEach((reel, col) => {
      reel.style.transform = "translateY(0)";
      reel.innerHTML = "";
      for (let i = 0; i < CELLS; i++) {
        const cell = document.createElement("div");
        cell.className = "slot-cell";
        const it = items[(i + col * 3) % items.length];
        cell.innerHTML = `<span class="sc-emoji">${it.emoji}</span><span class="sc-name">${it.name}</span>`;
        reel.appendChild(cell);
      }
    });
  }

  function spinReel(reel, laps, duration, tick) {
    return new Promise((resolve) => {
      const cellH = reel.children[0]?.getBoundingClientRect().height || CELL_FALLBACK_H;
      const loopLen = CELLS * cellH;
      const total = (laps * CELLS + CELLS) * cellH; // 逻辑滚动量；视觉位置对 loopLen 取模循环
      const t0 = performance.now();
      let lastCell = 0;
      reel.closest(".slot-window").classList.add("is-spinning");
      const frame = (now) => {
        const p = Math.min(1, (now - t0) / duration);
        const logical = total * easeOutCubic(p);
        const offset = logical % loopLen;
        reel.style.transform = `translateY(${-offset}px)`;
        const cellIndex = Math.floor(logical / cellH);
        if (cellIndex !== lastCell) {
          lastCell = cellIndex;
          tick(Math.min(1, 1.2 - p));
        }
        if (p < 1) {
          requestAnimationFrame(frame);
        } else {
          reel.style.transform = "translateY(0)"; // 恰好停在 index 0 = 结果格
          reel.closest(".slot-window").classList.remove("is-spinning");
          reel.closest(".slot-window").classList.add("is-set");
          resolve();
        }
      };
      requestAnimationFrame(frame);
    });
  }

  async function spin(result) {
    const items = ctx.items();
    const id = result.result === "prize" ? result.prize.id : "thanks";
    const winner = items.find((it) => it.id === id) || items[items.length - 1];
    // 三列首格（落点窗口）都放中奖奖品
    reels.forEach((reel) => {
      const first = reel.firstElementChild;
      first.innerHTML = `<span class="sc-emoji">${winner.emoji}</span><span class="sc-name">${winner.name}</span>`;
    });

    btn.disabled = true;
    const delays = ctx.reduced ? [0, 60, 120] : [0, 220, 440];
    const lapsBase = ctx.reduced ? 1 : 3;
    const durations = [0, 1, 2].map((col) =>
      ctx.reduced ? 420 + col * 80 : 2400 + col * 800 + rand(-120, 120)
    );
    await Promise.all(
      reels.map((reel, col) =>
        (async () => {
          await new Promise((r) => setTimeout(r, delays[col]));
          await spinReel(reel, lapsBase + col, durations[col], (i) => ctx.fx.sound.tick(i));
        })()
      )
    );
    ctx.fx.sound.pop();
    btn.disabled = false;
  }

  btn.addEventListener("click", async () => {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    await spin(result);
    const choice = await ctx.reveal(result);
    ctx.refresh();
    windows.forEach((w) => w.classList.remove("is-set"));
    running = false;
    buildReels();
    if (choice === "again") setTimeout(() => btn.click(), 200);
  });

  const onPrizes = () => { if (!running) buildReels(); };
  window.addEventListener("lucky:prizes", onPrizes);
  buildReels();

  return {
    destroy() {
      window.removeEventListener("lucky:prizes", onPrizes);
    },
  };
}
