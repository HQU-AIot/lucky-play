/* 形式五：老虎机。右侧拉杆启动（点拉杆或按钮），三列滚轮错峰独立减速、
   高速模糊、逐格 tick；每列停定回弹，全部停齐时机身震动 + 顶灯跑马。
   结果先行——落点格（index 0）内容提前替换为中奖奖品。 */

import { easeOutCubic, rand } from "../easing.js";

const CELLS = 24;
const CELL_FALLBACK_H = 150;

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="slot-box">
      <div class="slot-machine">
        <div class="slot-marquee"><span>★ 幸运老虎机 ★</span></div>
        <div class="slot-main">
          <div class="slot-windows">
            <div class="slot-window"><div class="slot-reel"></div></div>
            <div class="slot-window"><div class="slot-reel"></div></div>
            <div class="slot-window"><div class="slot-reel"></div></div>
            <div class="slot-payline"></div>
          </div>
          <div class="slot-lever" role="button" tabindex="0" aria-label="拉下拉杆开始抽奖">
            <span class="lever-slot"></span>
            <span class="lever-arm">
              <span class="lever-stick"></span>
              <span class="lever-knob"></span>
            </span>
          </div>
        </div>
        <button class="btn-primary slot-btn" type="button">开抽</button>
      </div>
      <p class="stage-hint">拉下拉杆，三灯亮好运</p>
    </div>`;

  const machineEl = stage.querySelector(".slot-machine");
  const lever = stage.querySelector(".slot-lever");
  const leverArm = stage.querySelector(".lever-arm");
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
          reel.style.transform = "translateY(0)"; // 停在 index 0 = 结果格
          reel.closest(".slot-window").classList.remove("is-spinning");
          reel.closest(".slot-window").classList.add("is-set");
          ctx.fx.sound.blip(150, 0.14, "triangle", 0.1); // 停格闷响
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
    lever.style.pointerEvents = "none";

    // 拉杆拉下回弹（与滚动并行，仪式感）
    if (!ctx.reduced) {
      leverArm.animate(
        [
          { transform: "rotate(0)" },
          { transform: "rotate(34deg)", offset: 0.42 },
          { transform: "rotate(26deg)", offset: 0.6 },
          { transform: "rotate(0)" },
        ],
        { duration: 700, easing: "cubic-bezier(.4,0,.4,1)" }
      );
    }

    const delays = ctx.reduced ? [0, 60, 120] : [180, 430, 680];
    const lapsBase = ctx.reduced ? 1 : 3;
    const durations = [0, 1, 2].map((col) =>
      ctx.reduced ? 420 + col * 80 : 2500 + col * 850 + rand(-120, 120)
    );
    await Promise.all(
      reels.map((reel, col) =>
        (async () => {
          await new Promise((r) => setTimeout(r, delays[col]));
          await spinReel(reel, lapsBase + col, durations[col], (i) => ctx.fx.sound.tick(i));
          // 停列回弹：窗口显示往下探一下再回正
          if (!ctx.reduced) {
            await reel.animate(
              [
                { transform: "translateY(0)" },
                { transform: "translateY(18px)", offset: 0.45 },
                { transform: "translateY(0)" },
              ],
              { duration: 240, easing: "ease-in-out" }
            ).finished.catch(() => {});
          }
        })()
      )
    );

    // 全部停齐：机震 + 顶灯跑马 + 开闸音
    ctx.fx.sound.pop();
    if (!ctx.reduced) {
      machineEl.animate(
        [
          { transform: "translate(0,0)" },
          { transform: "translate(-4px,2px)" },
          { transform: "translate(4px,-2px)" },
          { transform: "translate(-2px,1px)" },
          { transform: "translate(0,0)" },
        ],
        { duration: 300, easing: "ease-out" }
      );
    }
    machineEl.classList.add("is-party");
    btn.disabled = false;
    lever.style.pointerEvents = "";
  }

  async function start() {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    try {
      await spin(result);
    } finally {
      // 任何异常下都恢复交互，避免拉杆/按钮永久禁用
      windows.forEach((w) => w.classList.remove("is-set"));
      machineEl.classList.remove("is-party");
      btn.disabled = false;
      lever.style.pointerEvents = "";
    }
    const choice = await ctx.reveal(result);
    ctx.refresh();
    running = false;
    buildReels();
    if (choice === "again") setTimeout(() => btn.click(), 200);
  }

  btn.addEventListener("click", start);
  lever.addEventListener("click", start);
  lever.addEventListener("keydown", (e) => {
    if (e.repeat) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      start();
    }
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
