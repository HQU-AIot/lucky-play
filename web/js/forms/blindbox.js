/* 形式三：盲盒（8 盒亮底 + 疯狂乱序）。开局 8 只盒子全部亮出奖品标签（奖品固定可见），
   玩家点选一只后：全部标签迅速翻面成"?"——服务器结果此刻已定，翻面是为了藏起
   "结果与盒子"的对应关系，制造记忆挑战——随后其余 7 只疯狂两两换位（先密后疏），
   选中盒原地剧烈摇晃，盖子顶飞迸彩带。总时长卡 RESULT_AT=5s 出弹窗，恰逢歌里喊"停"。
   弹窗关闭后其余盒子按 /api/sample 真实采样翻开，展示"如果选它们"的分布。 */

import { sleep, lerp } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";
import { api } from "../api.js?v=10";

/* 时间轴：0 翻面 → 250 换位 → 2650 摇晃 → 3450 开盖 → 5000 弹窗（RESULT_AT 兜底对齐） */
const FLIP_MS = 250;       // 标签翻面成"?"的时长
const SHUFFLE_MS = 2400;   // 换位阶段总预算（含戛然而止后的定拍）
const SHUFFLE_COUNT = 8;   // 两两交换次数（设计区间 7-9 次，取中）
const SWAP_GAP_MIN = 140;  // 换位间隔下限（先密）
const SWAP_GAP_MAX = 380;  // 换位间隔上限（后疏）
const SWAP_MOVE_MAX = 320; // 单次换位移动时长上限（须小于间隔，连环交换才不跳变）
const SHAKE_MS = 800;      // 选中盒剧烈摇晃
const LID_MS = 640;        // 盖子被顶飞翻滚落地的时长（纯视觉，与展示期重叠）
const POP_AT = FLIP_MS + SHUFFLE_MS + SHAKE_MS; // 开盖时刻 ≈3450ms
const REDUCED_OPEN_MS = 400; // 减动效路径：翻面后短暂停顿即开盒
const REVEAL_STEP_MS = 90;   // 弹窗关闭后揭底的错峰间隔

/* 布局：4×2 网格（窄屏 2 列），盒子绝对定位、left/top 由 JS 按格位计算——
   换位 = 改坐标 + WAAPI 补间，比 FLIP 记录还原更简单可靠 */
const GRID_GAP = 16;
const BOX_RATIO = 0.88; // 盒高/盒宽：8 盒比旧 3 盒扁一些
const NARROW_PX = 560;  // 窄屏阈值：以下改 2 列

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="bb-wrap">
      <div class="bb-grid"></div>
      <p class="stage-hint">亮出的奖品会疯狂换位——盯住它，选中哪只开哪只</p>
    </div>`;
  const grid = stage.querySelector(".bb-grid");
  let running = false;
  let dead = false;
  let geometry = null;
  const timers = [];

  function render() {
    const all = ctx.items();
    const items = all.slice(0, 8);
    grid.innerHTML = "";
    items.forEach((item, i) => {
      const box = document.createElement("button");
      box.className = "box bb-box is-floating";
      box.type = "button";
      box.style.setProperty("--i", i); // idle 浮动错拍
      box.setAttribute("aria-label", `盲盒 ${i + 1}`);
      box.innerHTML = `
        <span class="box-lid"></span>
        <span class="box-body"></span>
        <span class="bb-face"><span class="bb-emoji">${item.emoji}</span><span class="bb-name">${item.name}</span></span>
        <span class="box-q">?</span>
        <span class="box-prize"></span>`;
      box.addEventListener("click", () => open(i));
      grid.appendChild(box);
    });
    // 奖品超过 7+谢谢参与时盒面放不下：明示"看得到的只有前 8 项，但抽奖池是全量"
    if (all.length > 8) {
      stage.querySelector(".stage-hint").textContent =
        `奖品共 ${all.length} 项，盒面仅展示前 8 项——其余项仍可能被抽中`;
    }
    layout();
  }

  /* 计算格位几何并落位：容器高度由 JS 依据列数设定 */
  function layout() {
    const n = grid.children.length;
    if (!n) return;
    const cols = window.innerWidth < NARROW_PX ? 2 : 4;
    const bw = (grid.clientWidth - (cols - 1) * GRID_GAP) / cols;
    const bh = bw * BOX_RATIO;
    const rows = Math.ceil(n / cols);
    grid.style.height = `${rows * bh + (rows - 1) * GRID_GAP}px`;
    geometry = { cols, bw, bh };
    [...grid.children].forEach((box, i) => {
      if (box._slot === undefined) box._slot = i;
      box.style.width = `${bw}px`;
      box.style.height = `${bh}px`;
      placeAt(box, box._slot);
    });
  }

  function slotXY(slot) {
    const { cols, bw, bh } = geometry;
    return { x: (slot % cols) * (bw + GRID_GAP), y: ((slot / cols) | 0) * (bh + GRID_GAP) };
  }

  function placeAt(box, slot) {
    const { x, y } = slotXY(slot);
    box.style.left = `${x}px`;
    box.style.top = `${y}px`;
  }

  function setLabel(box, emoji, name) {
    box.querySelector(".bb-emoji").textContent = emoji;
    box.querySelector(".bb-name").textContent = name;
  }

  function fillPrize(box, result) {
    const slot = box.querySelector(".box-prize");
    if (result.result === "prize") {
      slot.innerHTML = `<span class="p-emoji">${result.prize.emoji}</span><span class="p-name">${result.prize.name}</span>`;
    } else {
      slot.innerHTML = `<span class="p-emoji">🙏</span><span class="p-name">谢谢参与</span>`;
    }
  }

  /* 其余盒子的"如果选它们"面：按当前概率真实采样（无副作用），不足则补谢谢参与 */
  function buildFaces(sampled, count) {
    const faces = (sampled.samples || []).slice(0, count).map((s) => ({ emoji: s.emoji, name: s.name }));
    while (faces.length < count) faces.push({ emoji: "🙏", name: "谢谢参与" });
    return faces;
  }

  async function shake(box) {
    // 剧烈摇晃：比旧 3 盒版振幅更大、频率更高，0.8s 内推到蓄力顶点
    const frames = [];
    const steps = 18;
    for (let i = 0; i <= steps; i++) {
      const p = i / steps;
      const amp = 3 + 15 * p;
      const tilt = Math.sin(p * Math.PI * 14) * amp;
      frames.push({
        transform: `translateX(${tilt}px) rotate(${tilt * 0.4}deg)`,
        offset: p,
        easing: "ease-in-out",
      });
    }
    await box.animate(frames, { duration: SHAKE_MS }).finished.catch(() => {});
  }

  /* 两只盒子互换格位：WAAPI translate 补间过去，动画落定后同步逻辑槽位，
     后续连环交换才从正确的视觉位置起步（不走样、不跳变） */
  function swap(a, b, dur) {
    const from = slotXY(a._slot);
    const to = slotXY(b._slot);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const opts = { duration: dur, easing: "cubic-bezier(.3,.7,.35,1)" };
    const animA = a.animate(
      [{ transform: "translate(0,0)" }, { transform: `translate(${dx}px, ${dy}px)` }], opts);
    const animB = b.animate(
      [{ transform: "translate(0,0)" }, { transform: `translate(${-dx}px, ${-dy}px)` }], opts);
    // finished 必须接 catch：换位中途切玩法时 DOM 已移除，拒绝不能变成 unhandled rejection
    animA.finished.catch(() => {});
    animB.finished.catch(() => {});
    return Promise.all([animA.finished, animB.finished]).catch(() => {}).then(() => {
      [a._slot, b._slot] = [b._slot, a._slot];
      placeAt(a, a._slot);
      placeAt(b, b._slot);
    });
  }

  /* 疯狂换位：两两交换 SHUFFLE_COUNT 次，间隔 140→380ms 先密后疏；
     移动时长压在间隔以内，每步耗时即间隔，节奏稳定推进 */
  async function shuffle(movers) {
    for (let i = 0; i < SHUFFLE_COUNT; i++) {
      const p = i / (SHUFFLE_COUNT - 1);
      const gap = lerp(SWAP_GAP_MIN, SWAP_GAP_MAX, p);
      const a = movers[(Math.random() * movers.length) | 0];
      let b = a;
      while (b === a) b = movers[(Math.random() * movers.length) | 0];
      if (i > 1) ctx.fx.sound.tick(0.25 + p * 0.4); // 换位哒哒声随节奏渐强
      await Promise.all([swap(a, b, Math.min(gap * 0.85, SWAP_MOVE_MAX)), sleep(gap)]);
    }
  }

  /* 开盖三连：填奖品 → 盖子顶飞翻滚落地 → 彩带迸在盒心 */
  function pop(box, result) {
    fillPrize(box, result);
    box.classList.add("is-open");
    ctx.fx.sound.pop();
    if (!ctx.reduced) {
      // 盖子被顶飞：抛起翻滚，落在盒旁不再凭空消失（fill:forwards 定格）
      const lid = box.querySelector(".box-lid");
      lid.animate(
        [
          { transform: "translate(0,0) rotate(0deg)", opacity: 1 },
          { transform: "translate(24px,-76px) rotate(-44deg)", opacity: 1, offset: 0.38 },
          { transform: "translate(56px,-8px) rotate(-98deg)", opacity: 1, offset: 0.72 },
          { transform: "translate(64px,22px) rotate(-124deg)", opacity: 1 },
        ],
        { duration: LID_MS, easing: "cubic-bezier(.32,.6,.5,1)", fill: "forwards" }
      ).finished.catch(() => {});
      const rect = box.getBoundingClientRect();
      ctx.fx.confetti.burstAt(rect.left + rect.width / 2, rect.top + rect.height * 0.35);
    }
  }

  async function open(index) {
    if (running || dead) return;
    ctx.fx.sound.click();
    // 真实抽奖（扣库存、起播音乐）与旁位采样（无副作用）并行——动画时钟从此刻起跑
    const [result, sampled] = await Promise.all([
      ctx.draw(),
      api.sample(7).catch(() => ({ samples: [] })),
    ]);
    if (!result || dead) return;
    running = true;
    const t0 = performance.now(); // = 音乐起播点，各阶段终点用 phaseEnd 兜底对齐
    const phaseEnd = (ms) => sleep(Math.max(0, ms - (performance.now() - t0)));

    const boxes = [...grid.children];
    boxes.forEach((b) => {
      b.disabled = true;
      b.classList.remove("is-floating"); // 停 idle 浮动，避免与换位/摇晃的 transform 互相覆盖
    });
    const box = boxes[index];
    const others = boxes.filter((_, i) => i !== index);

    // ① 全部标签翻面成"?"：迅速藏起"你刚才盯住的奖品"与盒子的对应关系
    boxes.forEach((b) => b.classList.add("is-q"));

    if (ctx.reduced) {
      // 减动效：跳过换位与摇晃，短暂停顿直接开盒
      await sleep(REDUCED_OPEN_MS);
      pop(box, result);
      await sleep(150);
    } else {
      // ② 选中盒上浮 + 金色描边锁定，其余 7 只疯狂换位（选中盒原地不动）
      box.classList.add("is-picked");
      grid.classList.add("is-shuffling");
      await phaseEnd(FLIP_MS);
      if (others.length >= 2) await shuffle(others);
      grid.classList.remove("is-shuffling");
      await phaseEnd(FLIP_MS + SHUFFLE_MS);
      // ③ 选中盒剧烈摇晃蓄力
      await shake(box);
      await phaseEnd(POP_AT);
      // ④ 开盖：盖子顶飞 + 彩带 + 奖品 spring 弹出
      pop(box, result);
      // ⑤ 卡准 RESULT_AT：歌里的"停"喊出的一瞬弹窗（各阶段常量拼出，此处兜底对齐）
      await phaseEnd(RESULT_AT * 1000);
    }

    const choice = await ctx.reveal(result);
    if (dead) return;

    // ⑥ 弹窗关闭后揭底：其余 7 盒按真实采样翻开，展示"如果选它们"的分布
    const faces = buildFaces(sampled, others.length);
    others.forEach((b, k) => {
      timers.push(setTimeout(() => {
        if (dead) return;
        setLabel(b, faces[k].emoji, faces[k].name);
        b.classList.remove("is-q");
        b.classList.add("is-dim");
      }, k * REVEAL_STEP_MS));
    });
    await sleep(others.length * REVEAL_STEP_MS + 900);
    if (dead) return;

    ctx.refresh();
    running = false;
    render();
    if (choice === "again") {
      // 再抽一次：重建后重开同一只盒子（模仿 flip.js 的 index % 8 做法）
      timers.push(setTimeout(() => grid.children[index % (grid.children.length || 1)]?.click(), 200));
    }
  }

  const onPrizes = () => { if (!running && !dead) render(); };
  window.addEventListener("lucky:prizes", onPrizes);
  const ro = new ResizeObserver(() => { if (!running && !dead) layout(); });
  ro.observe(grid);
  render();

  return {
    destroy() {
      dead = true;
      timers.forEach(clearTimeout);
      window.removeEventListener("lucky:prizes", onPrizes);
      ro.disconnect();
      // 切玩法时 stage.innerHTML="" 已移除 DOM；取消仍在跑的 WAAPI 动画让其立刻收尾
      // （所有 finished 都已接 catch，不会产生 unhandled rejection）
      if (grid.getAnimations) grid.getAnimations({ subtree: true }).forEach((a) => a.cancel());
    },
  };
}
