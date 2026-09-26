/* 形式六：扭蛋机。大机身（玻璃球舱满舱彩球 + 反光、出货口、投币口、品牌牌）。
   彩球带轻量 2D 物理：重力、球间碰撞、桶壁反弹——摇柄搅动、掉蛋震舱、点玻璃逗球；
   转旋钮 → 彩球翻滚 → 扭蛋掉落弹跳 → 摇晃蓄力 → 壳盖旋飞、奖品弹出。
   时长对齐音乐：摇柄 3.08s + 落地 .55s + 蓄力 .5s，~4.1s 开壳，展示至 RESULT_AT=5s"停"时弹窗出场。 */

import { sleep, rand } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";

// 真实扭蛋球的鲜艳塑料色，不随主题变化
const BALL_COLORS = ["#FF5A5F", "#FFD166", "#4CC9F0", "#06D6A0", "#F78CDB", "#F7F7F7"];
const BALL_COUNT = 15;
const CRANK_MS = 3080;  // 摇柄时长（220ms × 14 拍哒哒声整循环）
const LAND_MS = 550;    // 扭蛋滚出+落地动画时长（WAAPI 关键帧内含落地挤压）
const QUIVER_MS = 500;  // 开壳前蓄力摇晃

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="gacha-box">
      <div class="gacha-machine">
        <div class="gacha-top"><span></span><span></span><span></span></div>
        <div class="gacha-dome"><span class="dome-shine"></span></div>
        <div class="gacha-brand">★ LUCKY EGG ★</div>
        <div class="gacha-panel">
          <div class="gacha-coin" title="投币口"></div>
          <div class="gacha-chute"></div>
          <button class="gacha-knob" type="button" aria-label="旋转旋钮开始抽奖"><span></span></button>
        </div>
        <div class="gacha-feet"><span></span><span></span></div>
      </div>
      <div class="gacha-egg-stage">
        <div class="gacha-egg" hidden>
          <span class="egg-half is-top"></span>
          <span class="egg-half is-bottom"></span>
          <span class="egg-prize"></span>
        </div>
      </div>
      <p class="stage-hint">转一转，掉出一颗蛋</p>
    </div>`;

  const machine = stage.querySelector(".gacha-machine");
  const dome = stage.querySelector(".gacha-dome");
  const knob = stage.querySelector(".gacha-knob");
  const egg = stage.querySelector(".gacha-egg");
  const prizeSlot = egg.querySelector(".egg-prize");
  let running = false;

  // ---- 彩球轻量物理（重力/球间碰撞/桶壁反弹；静止后自动休眠省电）----

  let balls = [];
  let domeW = 0, domeH = 0;
  let physRaf = 0, physLast = 0, physAcc = 0, idleFrames = 0;

  function measureDome() {
    const r = dome.getBoundingClientRect();
    if (r.width < 10) return false;
    domeW = r.width;
    domeH = r.height;
    return true;
  }

  function spawnBalls() {
    if (!measureDome()) return;
    dome.querySelectorAll(".g-ball").forEach((b) => b.remove());
    balls = [];
    for (let i = 0; i < BALL_COUNT; i++) {
      const d = Math.round(rand(46, 66));
      const el = document.createElement("span");
      el.className = "g-ball";
      el.style.width = el.style.height = `${d}px`;
      el.style.background = `radial-gradient(circle at 32% 26%, rgba(255,255,255,.85), ${BALL_COLORS[i % BALL_COLORS.length]} 60%)`;
      dome.appendChild(el);
      const r = d / 2;
      balls.push({
        el, r,
        x: rand(r, domeW - r),
        // 新一轮从舱顶洒落，落地弹跳后堆起来
        y: ctx.reduced ? rand(r, domeH * 0.55) : rand(-domeH * 0.9, -r),
        vx: rand(-40, 40),
        vy: 0,
      });
    }
    renderBalls();
    wake();
  }

  function stepPhysics(dt) {
    const G = 1500, WALL = 0.5, AIR = 0.999;
    for (const b of balls) {
      b.vy += G * dt;
      b.vx *= AIR;
      b.vy *= AIR;
      b.x += b.vx * dt;
      b.y += b.vy * dt;
      if (b.x < b.r) { b.x = b.r; b.vx = Math.abs(b.vx) * WALL; }
      else if (b.x > domeW - b.r) { b.x = domeW - b.r; b.vx = -Math.abs(b.vx) * WALL; }
      // 舱顶只拦上行的球，放行从上方洒落入舱的球
      if (b.y < b.r && b.vy < 0) { b.y = b.r; b.vy = Math.abs(b.vy) * WALL; }
      else if (b.y > domeH - b.r) {
        b.y = domeH - b.r;
        b.vy = -Math.abs(b.vy) * WALL;
        if (Math.abs(b.vy) < 40) b.vy = 0;
        b.vx *= 0.9; // 地面滚动摩擦
        if (Math.abs(b.vx) < 10) b.vx = 0;
      }
    }
    // 球间碰撞：位置各退一半（留 0.4px slop，堆叠才不微抖）+ 沿法线冲量
    for (let i = 0; i < balls.length; i++) {
      for (let j = i + 1; j < balls.length; j++) {
        const a = balls[i], c = balls[j];
        const dx = c.x - a.x, dy = c.y - a.y;
        const min = a.r + c.r;
        const d2 = dx * dx + dy * dy;
        if (d2 < min * min && d2 > 1e-4) {
          const dist = Math.sqrt(d2);
          const nx = dx / dist, ny = dy / dist;
          const push = (min - dist) / 2 - 0.4;
          if (push > 0) {
            a.x -= nx * push; a.y -= ny * push;
            c.x += nx * push; c.y += ny * push;
            const rel = (c.vx - a.vx) * nx + (c.vy - a.vy) * ny;
            if (rel < 0) {
              // 慢速挤压（静止堆叠）直接吃掉法向相对速度，堆叠才睡得着；
              // 快速对撞按恢复系数 0.72（等质量冲量系数 = (1+e)/2 = 0.86）
              const imp = rel < -60 ? -rel * 0.86 : -rel;
              a.vx -= nx * imp; a.vy -= ny * imp;
              c.vx += nx * imp; c.vy += ny * imp;
            }
          }
        }
      }
    }
  }

  function renderBalls() {
    for (const b of balls) {
      b.el.style.transform = `translate(${(b.x - b.r).toFixed(1)}px, ${(b.y - b.r).toFixed(1)}px)`;
    }
  }

  function loop(now) {
    physRaf = requestAnimationFrame(loop);
    if (!physLast) { physLast = now; return; }
    physAcc += Math.min(0.05, (now - physLast) / 1000);
    physLast = now;
    const H = 1 / 120;
    while (physAcc >= H) {
      stepPhysics(H);
      physAcc -= H;
    }
    renderBalls();
    // 休眠判定：所有球速度都低于 30px/s（重力注入的 12.5px/s 会被静止接触吃掉）持续 1.25s
    let maxV2 = 0;
    for (const b of balls) maxV2 = Math.max(maxV2, b.vx * b.vx + b.vy * b.vy);
    if (maxV2 < 900) {
      if (++idleFrames > 75) {
        cancelAnimationFrame(physRaf);
        physRaf = 0;
      }
    } else {
      idleFrames = 0;
    }
  }

  function wake() {
    if (ctx.reduced) return;
    idleFrames = 0;
    if (!physRaf) {
      physLast = 0;
      physAcc = 0;
      physRaf = requestAnimationFrame(loop);
    }
  }

  function jolt(strength = 1) {
    if (ctx.reduced || !balls.length) return;
    for (const b of balls) {
      b.vx += rand(-220, 220) * strength;
      b.vy -= rand(240, 520) * strength;
    }
    wake();
  }

  // 点玻璃舱逗球：点击处的球向上蹦起再落回堆里
  function poke(e) {
    if (ctx.reduced || !balls.length) return;
    const r = dome.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    for (const b of balls) {
      const dx = b.x - px, dy = b.y - py;
      const d = Math.hypot(dx, dy);
      if (d < 170) {
        const f = (1 - d / 170) * 620;
        b.vx += (dx / (d || 1)) * f * 0.6;
        b.vy -= f * 0.85 + rand(100, 260);
      }
    }
    wake();
  }

  function reset() {
    egg.hidden = true;
    egg.classList.remove("is-open", "is-quiver");
    prizeSlot.innerHTML = "";
  }

  function fillPrize(result) {
    prizeSlot.innerHTML = result.result === "prize"
      ? `<span class="p-emoji">${result.prize.emoji}</span><span class="p-name">${result.prize.name}</span>`
      : `<span class="p-emoji">🙏</span><span class="p-name">谢谢参与</span>`;
  }

  async function crank() {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    knob.disabled = true;

    // 1. 旋钮转动 + 球舱抖动 + 彩球被真实搅动翻滚 + 哒哒声（陪唱 3.08s）
    if (!ctx.reduced) {
      machine.classList.add("is-cranking");
      knob.animate(
        [
          { transform: "rotate(0)" },
          { transform: "rotate(1080deg)" },
        ],
        { duration: CRANK_MS, easing: "cubic-bezier(.3,.9,.3,1)" }
      );
      jolt(1.6); // 起手猛搅一记，彩球腾空互撞
      for (let i = 0; i < CRANK_MS / 220; i++) {
        ctx.fx.sound.tick(0.3 + i * 0.05);
        if (i === 3 || i === 6 || i === 10) jolt(0.8); // 中途再补三记搅动
        await sleep(220);
      }
      machine.classList.remove("is-cranking");
    }

    // 2. 扭蛋从出货口滚出 → 沿弧线坠落 → 落地挤压弹定（合并 0.55s，卡准"停"）
    reset();
    fillPrize(result);
    ctx.fx.sound.pop();
    jolt(0.5); // 落蛋震得舱内彩球一颤
    if (!ctx.reduced) {
      egg.hidden = false;
      const chute = stage.querySelector(".gacha-chute").getBoundingClientRect();
      const er = egg.getBoundingClientRect();
      const dx = chute.left + chute.width / 2 - (er.left + er.width / 2);
      const dy = chute.top - er.top;
      await egg.animate([
        { transform: `translate(${dx}px, ${dy - 6}px) scale(.72) rotate(-40deg)` },
        { transform: `translate(${dx * 0.52}px, ${dy * 0.5}px) scale(.88) rotate(150deg)`, offset: 0.45 },
        { transform: "translate(0,0) scale(1,1) rotate(330deg)", offset: 0.8 },
        { transform: "translate(0,3px) scale(1.08,.84) rotate(360deg)", offset: 0.9 },
        { transform: "translate(0,0) scale(1,1) rotate(360deg)" },
      ], { duration: LAND_MS, easing: "cubic-bezier(.42,0,.58,1)" }).finished.catch(() => {});
    } else {
      egg.hidden = false;
    }

    // 3. 摇晃两下蓄力
    if (!ctx.reduced) {
      egg.classList.add("is-quiver");
      await sleep(QUIVER_MS);
      egg.classList.remove("is-quiver");
    }

    // 4. 开壳：上盖旋飞，奖品弹出（~4.1s），补足展示至 5s"停"时弹窗出场
    egg.classList.add("is-open");
    if (!ctx.reduced) {
      const r = egg.getBoundingClientRect();
      ctx.fx.confetti.burstAt(r.left + r.width / 2, r.top + r.height * 0.4);
    }
    await sleep(ctx.reduced ? 200 : RESULT_AT * 1000 - CRANK_MS - LAND_MS - QUIVER_MS);

    const choice = await ctx.reveal(result);
    ctx.refresh();
    running = false;
    knob.disabled = false;
    reset(); // 重新撒球由 ctx.refresh 触发的 lucky:prizes → onPrizes 负责（避免双重传送）
    if (choice === "again") setTimeout(() => knob.click(), 200);
  }

  knob.addEventListener("click", crank);
  dome.addEventListener("click", poke);

  const onPrizes = () => { if (!running) spawnBalls(); };
  window.addEventListener("lucky:prizes", onPrizes);
  spawnBalls();

  const ro = new ResizeObserver(() => {
    if (measureDome()) {
      for (const b of balls) {
        b.x = Math.min(Math.max(b.x, b.r), domeW - b.r);
        b.y = Math.min(Math.max(b.y, b.r), domeH - b.r);
      }
      renderBalls();
      wake();
    }
  });
  ro.observe(dome);
  const onVis = () => {
    if (document.hidden) {
      if (physRaf) { cancelAnimationFrame(physRaf); physRaf = 0; }
    } else {
      wake();
    }
  };
  document.addEventListener("visibilitychange", onVis);

  return {
    destroy() {
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      dome.removeEventListener("click", poke);
      window.removeEventListener("lucky:prizes", onPrizes);
      if (physRaf) { cancelAnimationFrame(physRaf); physRaf = 0; }
    },
  };
}
