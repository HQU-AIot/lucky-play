/* 形式一：大转盘。Canvas 离屏渲染 + rAF 四段动画：
   蓄力回拉 → 爆发加速 → 长减速(easeOutExpo) → 过冲回摆。
   每跨过一条扇区边界，指针弹跳一次 + 合成 tick 声（密度随速度变化）。
   总时长对齐音乐：RESULT_AT=5s 歌喊"停"时指针落定。 */

import { easeInQuad, easeOutExpo, easeOutCubic, lerp, rand } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";

const TAU = Math.PI * 2;
const WINDUP = 0.40;      // 蓄力时长 s
const WINDUP_ANGLE = 0.26; // 回拉弧度 ≈ 15°
const OVERSHOOT = 0.02;    // 过冲弧度 ≈ 1.1°（2026-09-30 按需求从 2.9° 调小）
const SETTLE = 0.34;      // 过冲回摆时长 s

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="wheel-box">
      <div class="wheel-wrap">
        <div class="wheel-outer"></div>
        <canvas class="wheel-canvas"></canvas>
        <div class="wheel-pointer"><i class="ptr-knob"></i><i class="ptr-tip"></i></div>
        <button class="wheel-hub" type="button">开抽</button>
      </div>
      <p class="stage-hint">指针停在哪儿，好运就在哪儿</p>
    </div>`;

  const wrap = stage.querySelector(".wheel-wrap");
  const canvas = stage.querySelector(".wheel-canvas");
  const pointer = stage.querySelector(".wheel-pointer");
  const hub = stage.querySelector(".wheel-hub");
  const g2d = canvas.getContext("2d");

  let items = ctx.items().filter((p) => p.id !== "gamesir"); // 转盘奖池不含手柄（产品规则，服务端同步排除）
  let rotation = rand(0, TAU);
  let spinning = false;
  let offscreen = null;
  let size = 0;
  let dpr = 1;

  function palette() {
    const cs = getComputedStyle(document.body);
    const v = (n, fb) => cs.getPropertyValue(n).trim() || fb;
    return {
      c1: v("--wheel-1", "#B32733"),
      c2: v("--wheel-2", "#961D29"),
      ink: v("--wheel-ink", "#FFF6E5"),
      thanks: v("--wheel-thanks", "rgba(0,0,0,.32)"),
      border: v("--wheel-border", "rgba(255,255,255,.5)"),
      thanksInk: v("--wheel-ink", "#FFF6E5"),
    };
  }

  function resize() {
    const rect = wrap.getBoundingClientRect();
    if (rect.width < 10) return;
    dpr = Math.min(2, devicePixelRatio || 1);
    size = rect.width;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    renderStatic();
  }

  function renderOffscreen() {
    const pal = palette();
    offscreen = document.createElement("canvas");
    offscreen.width = size * dpr;
    offscreen.height = size * dpr;
    const c = offscreen.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    const r = size / 2;
    const seg = TAU / items.length;

    /* 名称带几何：中心钮外缘 → emoji 内缘，字号由最长的名字实测宽度决定
       （emoji 占宽与中心钮半径都取真实渲染尺寸——窄屏钮是固定 px，不随 15% 比例），
       全盘统一字号保证观感一致 */
    const emojiFont = Math.max(26, size * 0.075);
    const nameTexts = items.map((it) => (it.name.length > 6 ? it.name.slice(0, 6) : it.name));
    c.font = `900 100px ${getComputedStyle(document.body).fontFamily}`;
    const widestAt100 = Math.max(...nameTexts.map((n) => c.measureText(n).width));
    c.font = `${emojiFont}px sans-serif`;
    const emojiW = Math.max(...items.map((it) => c.measureText(it.emoji).width));
    const hubRect = hub.getBoundingClientRect();
    const hubR = (hubRect.width > 0 ? hubRect.width : size * 0.15) / 2;
    const bandStart = hubR + size * 0.01;                  // 中心钮外缘 + 间距
    const bandEnd = r * 0.82 - emojiW / 2 - size * 0.01;   // emoji 左缘（0.82r）- 间距
    const nameFont = Math.max(13, Math.min(size * 0.05, ((bandEnd - bandStart) * 100) / widestAt100));
    const bandMid = (bandStart + bandEnd) / 2;

    items.forEach((item, i) => {
      const a0 = i * seg;
      const isThanks = item.id === "thanks";
      c.beginPath();
      c.moveTo(r, r);
      c.arc(r, r, r - 3, a0, a0 + seg);
      c.closePath();
      c.fillStyle = isThanks ? pal.thanks : i % 2 === 0 ? pal.c1 : pal.c2;
      c.fill();
      c.strokeStyle = pal.border;
      c.lineWidth = 1.5;
      c.stroke();

      const mid = a0 + seg / 2;
      c.save();
      c.translate(r, r);
      c.rotate(mid);
      c.textAlign = "center";
      c.textBaseline = "middle";
      // emoji 挂在外圈（0.82r）
      c.font = `${emojiFont}px sans-serif`;
      c.fillText(item.emoji, r * 0.82, 0);
      // 名称沿半径排布：锚在名称带中点，宽度实测自适应，绝不压钮/emoji
      c.fillStyle = isThanks ? pal.thanksInk : pal.ink;
      c.font = `900 ${nameFont}px ${getComputedStyle(document.body).fontFamily}`;
      c.shadowColor = "rgba(0,0,0,.35)";
      c.shadowBlur = 8;
      c.fillText(nameTexts[i], bandMid, 0);
      c.restore();
    });
  }

  function draw(rotationAngle) {
    const c = g2d;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, canvas.width, canvas.height);
    if (!offscreen) return;
    const half = (size * dpr) / 2;
    c.setTransform(1, 0, 0, 1, half, half);
    c.rotate(rotationAngle);
    c.drawImage(offscreen, -half, -half, size * dpr, size * dpr);
  }

  function renderStatic() {
    renderOffscreen();
    draw(rotation);
  }

  function pointerTick(intensity) {
    pointer.classList.remove("tick");
    void pointer.offsetWidth;
    pointer.classList.add("tick");
    ctx.fx.sound.tick(intensity);
  }

  function winnerIndex(result) {
    const id = result.result === "prize" ? result.prize.id : "thanks";
    return Math.max(0, items.findIndex((it) => it.id === id));
  }

  async function spin(result) {
    const seg = TAU / items.length;
    const targetIdx = winnerIndex(result);
    const jitter = rand(-0.32, 0.32) * seg;
    // 指针在正上方（-π/2）：让目标扇区中心对准指针
    const targetMod = ((-Math.PI / 2 - (targetIdx * seg + seg / 2) + jitter) % TAU + TAU) % TAU;
    const delta = ((targetMod - rotation) % TAU + TAU) % TAU;
    const spins = ctx.reduced ? 0 : 5 + Math.floor(rand(0, 3));
    const final = rotation + delta + spins * TAU;
    const relFinal = final - rotation; // 相对起始角的净转角

    const windT = ctx.reduced ? 0 : WINDUP;
    // 主减速 = 5s − 蓄力 − 回摆（±40ms 抖动），落点卡在歌里的"停"
    const spinT = ctx.reduced ? 0.7 : RESULT_AT - WINDUP - SETTLE + rand(-0.04, 0.04);
    const settleT = ctx.reduced ? 0 : SETTLE;

    hub.disabled = true;
    spinning = true;
    let lastBoundary = Math.floor((rotation + Math.PI / 2) / seg);
    let lastR = rotation;
    let lastT = performance.now();

    await new Promise((resolve) => {
      const t0 = performance.now();
      const frame = (now) => {
        const t = (now - t0) / 1000;
        let r;
        if (t < windT) {
          r = -WINDUP_ANGLE * easeInQuad(t / windT);
        } else if (t < windT + spinT) {
          const p = (t - windT) / spinT;
          r = lerp(-WINDUP_ANGLE, relFinal + OVERSHOOT, easeOutExpo(p));
        } else if (t < windT + spinT + settleT) {
          const p = (t - windT - spinT) / settleT;
          r = lerp(relFinal + OVERSHOOT, relFinal, easeOutCubic(p));
        } else {
          r = final;
          rotation = ((final % TAU) + TAU) % TAU;
          draw(rotation);
          resolve();
          return;
        }
        const abs = rotation + r; // r 为相对起始角
        const boundary = Math.floor((abs + Math.PI / 2) / seg);
        if (boundary !== lastBoundary) {
          lastBoundary = boundary;
          const now2 = performance.now();
          const speed = Math.abs(abs - lastR) / Math.max(1, now2 - lastT) * 1000;
          lastR = abs;
          lastT = now2;
          pointerTick(Math.min(1, speed / 14));
        }
        lastR = abs;
        draw(((abs % TAU) + TAU) % TAU);
        requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    });

    spinning = false;
    hub.disabled = false;
  }

  hub.addEventListener("click", async () => {
    if (spinning) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    await spin(result);
    const choice = await ctx.reveal(result);
    ctx.refresh();
    if (choice === "again") {
      setTimeout(() => hub.click(), 200);
    }
  });

  const ro = new ResizeObserver(resize);
  ro.observe(wrap);
  ro.observe(hub); // 窄屏媒体查询切换钮的固定/比例尺寸时不经 wrap 变化，需单独触发重绘
  const onTheme = () => renderStatic();
  const onPrizes = () => {
    items = ctx.items().filter((p) => p.id !== "gamesir");
    renderStatic();
  };
  window.addEventListener("lucky:theme", onTheme);
  window.addEventListener("lucky:prizes", onPrizes);
  resize();

  return {
    destroy() {
      ro.disconnect();
      window.removeEventListener("lucky:theme", onTheme);
      window.removeEventListener("lucky:prizes", onPrizes);
    },
  };
}
