/* 形式三：盲盒。三只盒子点选其一 → 长蓄力摇晃（振幅渐增，陪唱满 2.6s）→
   盖子弹飞 + 原地迸彩带 → 奖品 spring 弹出。4s 卡准歌里的"停"。 */

import { sleep, rand } from "../easing.js";
import { RESULT_AT } from "../music.js?v=6";

const SHAKE_MS = 2600; // 摇晃蓄力 = RESULT_AT − 开盖后展示时长

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="blindbox-box">
      <div class="box-row"></div>
      <p class="blindbox-cta">点一只盒子，拆开你的运气</p>
    </div>`;
  const row = stage.querySelector(".box-row");
  let running = false;

  function render() {
    row.innerHTML = "";
    for (let i = 0; i < 3; i++) {
      const box = document.createElement("button");
      box.className = "box";
      box.type = "button";
      box.setAttribute("aria-label", `盲盒 ${i + 1}`);
      box.innerHTML = `
        <span class="box-lid"></span>
        <span class="box-body"></span>
        <span class="box-q">?</span>
        <span class="box-prize"></span>`;
      box.addEventListener("click", () => open(i));
      row.appendChild(box);
    }
  }

  function fillPrize(box, result) {
    const slot = box.querySelector(".box-prize");
    if (result.result === "prize") {
      slot.innerHTML = `<span class="p-emoji">${result.prize.emoji}</span><span class="p-name">${result.prize.name}</span>`;
    } else {
      slot.innerHTML = `<span class="p-emoji">🙏</span><span class="p-name">谢谢参与</span>`;
    }
  }

  async function shake(box) {
    if (ctx.reduced) return;
    const frames = [];
    const steps = 22;
    for (let i = 0; i <= steps; i++) {
      const p = i / steps;
      const amp = 2 + 12 * p; // 振幅渐增
      const tilt = Math.sin(p * Math.PI * 16) * amp;
      frames.push({
        transform: `translateX(${tilt}px) rotate(${tilt * 0.35}deg)`,
        offset: p,
        easing: "ease-in-out",
      });
    }
    await box.animate(frames, { duration: SHAKE_MS }).finished.catch(() => {});
  }

  async function open(index) {
    if (running) return;
    ctx.fx.sound.click();
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    const boxes = [...row.children];
    boxes.forEach((b) => (b.disabled = true));
    const box = boxes[index];

    await shake(box);

    fillPrize(box, result);
    box.classList.add("is-open");
    boxes.forEach((b, i) => {
      if (i !== index) b.classList.add("is-dim");
    });
    ctx.fx.sound.pop();
    if (!ctx.reduced) {
      const rect = box.getBoundingClientRect();
      ctx.fx.confetti.burstAt(rect.left + rect.width / 2, rect.top + rect.height * 0.35);
    }
    // 开盖后展示到 4s 整：歌里的"停"响起时奖品恰好完全亮相
    await sleep(ctx.reduced ? 150 : RESULT_AT * 1000 - SHAKE_MS);

    const choice = await ctx.reveal(result);
    ctx.refresh();
    running = false;
    render();
    if (choice === "again") setTimeout(() => row.children[1]?.click(), 200);
  }

  const onTheme = () => render();
  window.addEventListener("lucky:theme", onTheme);
  render();

  return {
    destroy() {
      window.removeEventListener("lucky:theme", onTheme);
    },
  };
}
