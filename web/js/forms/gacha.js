/* 形式六：扭蛋机。转旋钮 → 玻璃球舱抖动 → 扭蛋掉落弹跳 → 摇晃两下 →
   壳盖旋飞、奖品 spring 弹出。 */

import { sleep } from "../easing.js";

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="gacha-box">
      <div class="gacha-machine">
        <div class="gacha-dome">
          <span class="g-ball" style="left:8%;top:12%;background:var(--accent)"></span>
          <span class="g-ball" style="left:34%;top:6%;background:var(--gold,var(--accent))"></span>
          <span class="g-ball" style="left:62%;top:14%;background:var(--accent-2,var(--accent))"></span>
          <span class="g-ball" style="left:20%;top:42%;background:var(--accent-2,var(--accent))"></span>
          <span class="g-ball" style="left:50%;top:38%;background:var(--accent)"></span>
          <span class="g-ball" style="left:74%;top:44%;background:var(--gold,var(--accent))"></span>
          <span class="g-ball" style="left:8%;top:68%;background:var(--gold,var(--accent))"></span>
          <span class="g-ball" style="left:64%;top:70%;background:var(--accent)"></span>
        </div>
        <div class="gacha-chute"></div>
        <button class="gacha-knob" type="button">转一转</button>
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
  const knob = stage.querySelector(".gacha-knob");
  const egg = stage.querySelector(".gacha-egg");
  const prizeSlot = egg.querySelector(".egg-prize");
  let running = false;

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

    // 1. 旋钮转动 + 球舱抖动 + 哒哒声
    if (!ctx.reduced) {
      machine.classList.add("is-cranking");
      knob.animate(
        [{ transform: "rotate(0)" }, { transform: "rotate(360deg)" }],
        { duration: 900, easing: "cubic-bezier(.3,.9,.4,1)" }
      );
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
      await egg.getAnimations().at(-1).finished.catch(() => {});
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
    if (choice === "again") setTimeout(() => knob.click(), 200);
  }

  knob.addEventListener("click", crank);

  return {
    destroy() {},
  };
}
