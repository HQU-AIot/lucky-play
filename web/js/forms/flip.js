/* 形式四：翻牌。8 张暗牌选一张：先快速虚晃两张，再停在选中张；
   选中卡翻开即结果，其余卡翻到谢谢参与后淡出。 */

import { sleep } from "../easing.js";

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
    const result = await ctx.draw();
    if (!result) return;
    running = true;
    const cards = [...grid.children];
    cards.forEach((c) => (c.disabled = true));

    if (result.result === "prize") setFace(cards[index], result.prize.emoji, result.prize.name);
    else setFace(cards[index], "🙏", "谢谢参与");

    // 虚晃两张（降低"直接翻中"的突兀感）
    if (!ctx.reduced) {
      const decoys = cards.map((_, i) => i).filter((i) => i !== index);
      for (let d = 0; d < 2; d++) {
        const j = decoys.splice((Math.random() * decoys.length) | 0, 1)[0];
        setFace(cards[j], "🙏", "谢谢参与");
        cards[j].classList.add("is-flipped");
        ctx.fx.sound.tick(0.3);
        await sleep(90);
      }
      await sleep(180);
    }

    cards[index].classList.add("is-flipped");
    await sleep(ctx.reduced ? 100 : 620);

    // 其余牌全部翻到谢谢参与并压暗
    cards.forEach((c, i) => {
      if (i === index) return;
      setFace(c, "🙏", "谢谢参与");
      setTimeout(() => c.classList.add("is-flipped", "is-dim"), ctx.reduced ? 0 : i * 55);
    });
    cards[index].classList.add("is-result");
    await sleep(ctx.reduced ? 150 : 750);

    const choice = await ctx.reveal(result);
    ctx.refresh();
    running = false;
    render();
    if (choice === "again") setTimeout(() => grid.children[index % 8]?.click(), 200);
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
