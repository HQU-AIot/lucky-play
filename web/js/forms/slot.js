/* 形式五：老虎机。右侧拉杆启动（点拉杆或按钮），三列滚轮错峰独立减速、
   高速模糊、逐格 tick；每列停定回弹，全部停齐时机身震动 + 顶灯跑马。
   结果先行——落点格（index 0）内容提前替换为中奖奖品。
   时长对齐音乐：末轮停定回弹后在 RESULT_AT=5s"停"齐开奖。
   超级大奖：命中当前有限库存最少的奖品时，顶灯切"超级大奖"金字狂闪 +
   机身金环脉冲 + 三钻连线落点格 + 加码彩带；纯视觉，琶音交给 app.js 收刀回调。 */

import { easeOutCubic, rand, sleep } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";

const CELLS = 24;
const CELL_FALLBACK_H = 150;
const LAST_DELAY = 520;   // 末轮启动延迟 ms
const LAST_SPIN = 3900;   // 末轮滚动时长 ms（名义值，±50 抖动）
const BOUNCE_MS = 240;    // 停定回弹 ms
const MARQUEE_DEFAULT = "★ 幸运老虎机 ★";
const MARQUEE_JACKPOT = "★ 超级大奖 ★";

/* 超级大奖判定：有限库存（total>0 且有限）中最小库存的奖品，排除谢谢参与。
   每次 spin 重新计算——后台改库存后下一轮自动跟随。
   注：公开 /api/prizes 下发的库存字段是 total（管理端叫 total_stock），两者同义。 */
function findJackpotPrize(items) {
  let best = null;
  let bestTotal = Infinity;
  for (const it of items) {
    if (it.id === "thanks") continue;
    const total = Number(it.total ?? it.total_stock);
    if (!Number.isFinite(total) || total <= 0) continue;
    if (total < bestTotal) {
      best = it;
      bestTotal = total;
    }
  }
  return best;
}

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
  const marqueeSpan = stage.querySelector(".slot-marquee span");
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
    // 超级大奖判定：本轮命中的恰是"当前有限库存最少"的奖品（每轮重算）
    const jackpotPrize = findJackpotPrize(items);
    const isJackpot = Boolean(jackpotPrize) && winner.id === jackpotPrize.id;
    // 三列首格（落点窗口）都放中奖奖品；大奖轮改"三钻连线"——图案统一替换为 💎、
    // 奖品名保留，弹窗关闭后 buildReels() 重建滚轮即自动复原
    reels.forEach((reel) => {
      const first = reel.firstElementChild;
      const emoji = isJackpot ? "💎" : winner.emoji;
      first.innerHTML = `<span class="sc-emoji${isJackpot ? " sc-jackpot-gem" : ""}">${emoji}</span><span class="sc-name">${winner.name}</span>`;
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

    const delays = ctx.reduced ? [0, 60, 120] : [140, 330, LAST_DELAY];
    const lapsBase = ctx.reduced ? 1 : 4;
    const durations = [0, 1, 2].map((col) =>
      ctx.reduced ? 420 + col * 80 : 2400 + col * 750 + rand(-50, 50)
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
              { duration: BOUNCE_MS, easing: "ease-in-out" }
            ).finished.catch(() => {});
          }
        })()
      )
    );
    // 补齐到 RESULT_AT：三灯停齐的瞬间正是歌里的"停"
    if (!ctx.reduced) {
      await sleep(RESULT_AT * 1000 - (LAST_DELAY + LAST_SPIN + BOUNCE_MS));
    }

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
    if (isJackpot) {
      // 超级大奖演出：顶灯切"超级大奖"金字狂闪 + 机身金环脉冲（样式见 base.css）。
      // 此处刻意不响琶音——中奖轮的胜利琶音由 app.js 在音乐收刀回调里统一触发
      // （fanfareByMusic 机制），slot 层再响会撞音；音乐未开启的大奖轮保持纯视觉
      // 静音（一致性取舍已与主线程约定，华丽版琶音 sound.jackpot() 留给主线程替换用）。
      marqueeSpan.textContent = MARQUEE_JACKPOT;
      machineEl.classList.add("is-jackpot");
    }
    btn.disabled = false;
    lever.style.pointerEvents = "";

    // 弹窗出场前的最后一步：超级大奖加码彩带——全屏双炮 + 机身中心环形爆。
    // ctx.reveal 弹窗在下一拍打开，此处同步触发，不改变 RESULT_AT=5s 的对齐时序；
    // 弹窗对所有中奖还会再放一波双炮——大奖轮合计三波，刻意的"超级"密度，非重复触发
    if (isJackpot && !ctx.reduced) {
      const box = machineEl.getBoundingClientRect();
      ctx.fx.confetti.cannons();
      ctx.fx.confetti.burstAt(box.left + box.width / 2, box.top + box.height / 2);
    }
  }

  async function start() {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    try {
      await spin(result);
      // 弹窗在此出场（reveal 内部时机不变，RESULT_AT 对齐不受影响）；
      // 演出视觉（is-party/is-jackpot/落点格）保留整个弹窗期间，
      // 待弹窗关闭后（或异常中断时）由 finally 统一复原
      const choice = await ctx.reveal(result);
      ctx.refresh();
      if (choice === "again") setTimeout(() => btn.click(), 200);
    } finally {
      // 任何异常下都恢复交互，避免拉杆/按钮永久禁用
      btn.disabled = false;
      lever.style.pointerEvents = "";
      // 复原演出：marquee 文字、庆祝/大奖类、落点格（滚轮重建恢复常规图案）。
      // 不能在 spin 返回时就清理——那时弹窗尚未出现，狂闪/跑马会被提前掐掉
      windows.forEach((w) => w.classList.remove("is-set"));
      machineEl.classList.remove("is-party", "is-jackpot");
      marqueeSpan.textContent = MARQUEE_DEFAULT;
      buildReels();
      running = false;
    }
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
