/* 形式五：老虎机。右侧拉杆启动（点拉杆或按钮），三列滚轮错峰独立减速、
   高速模糊、逐格 tick；每列停定回弹，全部停齐时机身震动 + 顶灯跑马。
   对对碰规则（服务端定结果，前端只负责演）：
   三轴全不同 = 没抽到；两同 = 该奖品 ×1；三同 = 该奖品 ×2；
   三同手柄 = 手柄 + 任选奖品；三同钻石 💎 = 超级大奖（每类奖品各一）；
   两同钻石 = 任选一件非手柄奖品。轴面图案 = 奖品 + 💎（代替谢谢参与）。
   时长对齐音乐：末轮停定回弹后在 RESULT_AT=5s"停"齐开奖。 */

import { easeOutCubic, rand, sleep } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";

const CELLS = 24;
const CELL_FALLBACK_H = 150;
const LAST_DELAY = 520;   // 末轮启动延迟 ms
const LAST_SPIN = 3900;   // 末轮滚动时长 ms（名义值，±50 抖动）
const BOUNCE_MS = 240;    // 停定回弹 ms
const MARQUEE_DEFAULT = "★ 幸运老虎机 ★";
const MARQUEE_JACKPOT = "★ 超级大奖 ★";
const DIAMOND = { id: "diamond", emoji: "💎", name: "钻石" };

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
        </div>
        <button class="btn-primary slot-btn" type="button">开抽</button>
        <div class="slot-lever" role="button" tabindex="0" aria-label="拉下拉杆开始抽奖">
          <span class="lever-slot"></span>
          <span class="lever-arm">
            <span class="lever-stick"></span>
            <span class="lever-knob"></span>
          </span>
        </div>
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

  /* 轴面符号表：全部奖品（手柄按后台开关进出）+ 钻石（代替谢谢参与参与连线） */
  function reelSymbols() {
    const cfg = ctx.meta().slot || {};
    const prizes = ctx.items().filter(
      (p) => p.id !== "thanks" && (cfg.gamesir_enabled !== false || p.id !== "gamesir")
    );
    return [...prizes, DIAMOND];
  }

  function buildReels() {
    const symbols = reelSymbols();
    reels.forEach((reel, col) => {
      reel.style.transform = "translateY(0)";
      reel.innerHTML = "";
      for (let i = 0; i < CELLS; i++) {
        const cell = document.createElement("div");
        cell.className = "slot-cell";
        const it = symbols[(i + col * 3) % symbols.length];
        cell.dataset.sym = it.id;
        cell.innerHTML = `<span class="sc-emoji${it.id === "diamond" ? " sc-diamond" : ""}">${it.emoji}</span><span class="sc-name">${it.name}</span>`;
        reel.appendChild(cell);
      }
    });
  }

  function spinReel(reel, laps, duration, tick) {
    return new Promise((resolve) => {
      const cellH = reel.children[0]?.getBoundingClientRect().height || CELL_FALLBACK_H;
      const cells = reel.children.length;
      const loopLen = cells * cellH;
      const total = (laps * cells + cells) * cellH; // 逻辑滚动量；视觉位置对 loopLen 取模循环
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
          ctx.fx.sound.blip(150, 0.14, "triangle", 0.1); // 停格闷响
          resolve();
        }
      };
      requestAnimationFrame(frame);
    });
  }

  async function spin(result) {
    const symbols = reelSymbols();
    const byId = new Map(symbols.map((s) => [s.id, s]));
    // 三列落点 = 服务端回传的三轴符号（对对碰结果完全由服务端决定，前端只演）。
    // 未知符号（如后台中途开手柄、旧页面轴面还没有它）兜底成中性"🎁 奖品"，
    // 绝不能兜底成钻石——否则三同手柄会被误判成三钻超级大奖
    const targets = (Array.isArray(result.symbols) && result.symbols.length === 3
      ? result.symbols
      : [DIAMOND.id, DIAMOND.id, DIAMOND.id]
    ).map((id) => byId.get(id) || { id, emoji: "🎁", name: "奖品" });
    const isJackpot = targets.every((t) => t.id === DIAMOND.id) && result.result === "prize";
    // 三列首格（落点窗口）放各自的轴面符号；弹窗关闭后 buildReels() 重建复原
    reels.forEach((reel, col) => {
      const first = reel.firstElementChild;
      const t = targets[col];
      first.dataset.sym = t.id;
      first.innerHTML = `<span class="sc-emoji${t.id === DIAMOND.id ? " sc-diamond" : ""}">${t.emoji}</span><span class="sc-name">${t.name}</span>`;
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
    // 连线判定：中奖轴高亮（is-set），落单轴压暗（is-dim）；没抽到则三轴朴素停格
    const counts = {};
    targets.forEach((t) => {
      counts[t.id] = (counts[t.id] || 0) + 1;
    });
    const winSym =
      result.result === "prize"
        ? Object.keys(counts).find((k) => counts[k] >= 2)
        : null;
    windows.forEach((w, col) => {
      w.classList.toggle("is-set", Boolean(winSym) && targets[col].id === winSym);
      w.classList.toggle("is-dim", Boolean(winSym) && targets[col].id !== winSym);
    });
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
    const result = await ctx.draw("slot");
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
      windows.forEach((w) => w.classList.remove("is-set", "is-dim"));
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
