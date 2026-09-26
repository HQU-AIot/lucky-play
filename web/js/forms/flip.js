/* 形式四：翻牌。8 张暗牌，翻开哪张哪张就是一次真实抽奖（服务端扣库存）；
   其余牌翻开显示按当前概率真实采样的奖品分布（/api/sample，无副作用）。
   节奏对齐音乐：虚晃三连 + 主牌蓄力 3.3s，翻面完成恰在 RESULT_AT=4s"停"。 */

import { sleep } from "../easing.js";
import { api } from "../api.js?v=6";
import { RESULT_AT } from "../music.js?v=6";

const FLIP_MS = 700; // 与 base.css .f-inner transition .7s 对齐

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="flip-box">
      <div class="card-grid"></div>
      <p class="flip-cta">凭手感选一张，翻开就是你的</p>
    </div>`;
  const grid = stage.querySelector(".card-grid");
  let running = false;

  function render() {
    grid.innerHTML = "";
    for (let i = 0; i < 8; i++) {
      const card = document.createElement("button");
      card.className = "f-card";
      card.type = "button";
      card.setAttribute("aria-label", `卡牌 ${i + 1}`);
      card.innerHTML = `
        <span class="f-inner">
          <span class="f-face f-back"><span class="f-mark">?</span></span>
          <span class="f-face f-front"></span>
        </span>`;
      card.addEventListener("click", () => pick(i));
      grid.appendChild(card);
    }
  }

  function setFace(card, emoji, name) {
    card.querySelector(".f-front").innerHTML =
      `<span class="f-emoji">${emoji}</span><span class="f-name">${name}</span>`;
  }

  async function pick(index) {
    if (running) return;
    ctx.fx.sound.click();
    // 真实抽奖（扣库存）与旁位采样（无副作用）并行
    const [result, sampled] = await Promise.all([
      ctx.draw(),
      api.sample(7).catch(() => ({ samples: [] })),
    ]);
    if (!result) return;
    running = true;
    const cards = [...grid.children];
    cards.forEach((c) => (c.disabled = true));

    if (result.result === "prize") setFace(cards[index], result.prize.emoji, result.prize.name);
    else setFace(cards[index], "🙏", "谢谢参与");

    // 其余牌面 = 按当前概率真实采样的分布
    const others = cards.map((_, i) => i).filter((i) => i !== index);
    const faces = (sampled.samples || []).slice(0, others.length);
    while (faces.length < others.length) {
      faces.push({ result: "thanks", name: "谢谢参与", emoji: "🙏" });
    }
    others.forEach((cardIndex, k) => {
      const s = faces[k];
      setFace(cards[cardIndex], s.emoji, s.name);
    });

    // 虚晃三连：未选中的牌面朝下轻抬示意，陪歌铺垫悬念（逐张等动画播完再停顿）
    if (!ctx.reduced) {
      const decoys = [...others];
      for (let d = 0; d < 3; d++) {
        const j = decoys.splice((Math.random() * decoys.length) | 0, 1)[0];
        await cards[j]
          .animate(
            [
              { transform: "translateY(0) rotate(0)" },
              { transform: "translateY(-12px) rotate(-2.5deg)", offset: 0.45 },
              { transform: "translateY(0) rotate(0)" },
            ],
            { duration: 660, easing: "ease-out" }
          )
          .finished.catch(() => {});
        ctx.fx.sound.tick(0.3 + d * 0.18);
        await sleep(220);
      }
      // 主牌蓄力呼吸：悬念推到"停"前一刻
      cards[index].animate(
        [
          { transform: "scale(1)" },
          { transform: "scale(1.05)" },
          { transform: "scale(1)" },
        ],
        { duration: 660, easing: "ease-in-out" }
      );
      ctx.fx.sound.tick(0.75);
      await sleep(660);
    }

    // 翻开主牌 = 开奖；翻面 transition .7s 完成 → 恰好 RESULT_AT"停"
    cards[index].classList.add("is-flipped");
    await sleep(ctx.reduced ? 100 : FLIP_MS);

    // 其余牌依次翻开，展示真实的"如果翻它"分布（哭声里的留影），并压暗
    others.forEach((cardIndex, k) => {
      cards[cardIndex].classList.add("is-dim");
      setTimeout(
        () => cards[cardIndex].classList.add("is-flipped"),
        ctx.reduced ? 0 : 120 + k * 90
      );
    });
    cards[index].classList.add("is-result");

    const choice = await ctx.reveal(result);
    ctx.refresh();
    running = false;
    render();
    if (choice === "again") setTimeout(() => grid.children[index % 8]?.click(), 200);
  }

  const onPrizes = () => { if (!running) render(); };
  window.addEventListener("lucky:prizes", onPrizes);
  render();

  return {
    destroy() {
      window.removeEventListener("lucky:prizes", onPrizes);
    },
  };
}
