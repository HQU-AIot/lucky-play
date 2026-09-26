/* 形式六：扭蛋机。大机身（玻璃球舱满舱彩球 + 反光、出货口、投币口、品牌牌）。
   转旋钮 → 球舱抖动彩球跳动 → 扭蛋掉落弹跳 → 摇晃蓄力 → 壳盖旋飞、奖品弹出。 */

import { sleep, rand } from "../easing.js";

// 真实扭蛋球的鲜艳塑料色，不随主题变化
const BALL_COLORS = ["#FF5A5F", "#FFD166", "#4CC9F0", "#06D6A0", "#F78CDB", "#F7F7F7"];

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

  function buildBalls() {
    dome.querySelectorAll(".g-ball").forEach((b) => b.remove());
    for (let i = 0; i < 15; i++) {
      const b = document.createElement("span");
      b.className = "g-ball";
      const size = Math.round(rand(46, 66));
      b.style.width = b.style.height = `${size}px`;
      b.style.left = `${rand(3, 76)}%`;
      b.style.top = `${rand(8, 58)}%`;
      b.style.background = `radial-gradient(circle at 32% 26%, rgba(255,255,255,.85), ${BALL_COLORS[i % BALL_COLORS.length]} 60%)`;
      dome.appendChild(b);
    }
  }

  function reset() {
    egg.hidden = true;
    egg.classList.remove("is-open", "is-landed", "is-quiver");
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

    // 1. 旋钮转动 + 球舱抖动 + 彩球跳动 + 哒哒声
    if (!ctx.reduced) {
      machine.classList.add("is-cranking");
      knob.animate(
        [
          { transform: "rotate(0)" },
          { transform: "rotate(720deg)" },
        ],
        { duration: 950, easing: "cubic-bezier(.3,.9,.3,1)" }
      );
      const balls = [...dome.querySelectorAll(".g-ball")];
      balls.forEach((b, i) => {
        b.animate(
          [
            { transform: "translateY(0)" },
            { transform: `translateY(${-6 - (i % 4) * 5}px)` },
            { transform: "translateY(0)" },
          ],
          { duration: 380, delay: (i % 5) * 90, easing: "ease-in-out", iterations: 2 }
        );
      });
      for (let i = 0; i < 5; i++) {
        ctx.fx.sound.tick(0.3 + i * 0.12);
        await sleep(170);
      }
      machine.classList.remove("is-cranking");
    }

    // 2. 扭蛋掉落弹跳
    reset();
    fillPrize(result);
    egg.hidden = false;
    ctx.fx.sound.pop();
    if (!ctx.reduced) {
      egg.classList.add("is-landed");
      await egg.getAnimations().at(-1)?.finished.catch(() => {});
    }

    // 3. 摇晃两下蓄力（先摘掉落地动画，避免其因类切换从头重播）
    if (!ctx.reduced) {
      egg.classList.remove("is-landed");
      egg.classList.add("is-quiver");
      await sleep(520);
      egg.classList.remove("is-quiver");
    }

    // 4. 开壳：上盖旋飞，奖品弹出
    egg.classList.add("is-open");
    if (!ctx.reduced) {
      const r = egg.getBoundingClientRect();
      ctx.fx.confetti.burstAt(r.left + r.width / 2, r.top + r.height * 0.4);
    }
    await sleep(ctx.reduced ? 200 : 950);

    const choice = await ctx.reveal(result);
    ctx.refresh();
    running = false;
    knob.disabled = false;
    reset();
    buildBalls();
    if (choice === "again") setTimeout(() => knob.click(), 200);
  }

  knob.addEventListener("click", crank);

  const onPrizes = () => { if (!running) buildBalls(); };
  window.addEventListener("lucky:prizes", onPrizes);
  buildBalls();

  return {
    destroy() {
      window.removeEventListener("lucky:prizes", onPrizes);
    },
  };
}
