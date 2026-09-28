/* 形式三：盲盒 v3（亮底 → 开始打乱 → 选盒开奖）。
   待选阶段 8 只盒子亮出奖品标签（奖品固定可见），点"开始打乱"的一瞬标签全部
   翻面成"?"——打乱全程不显示内容，8 只盲盒两两换位 14 次（90→240ms 先密后疏、
   弧线甩动轨迹）纯粹烘气氛；停下后盒子呼吸脉动邀请选盒，玩家任选一只的那一刻
   才 ctx.draw() 起播音乐：上浮金环锁定 → 渐强摇晃 → 末段剧烈抖动 → 4.35s 开盖
   迸彩带 → 5s"停"整弹窗出场（RESULT_AT 兜底对齐）。弹窗关闭后其余盒按
   /api/sample 真实采样翻开，展示"如果选它们"的分布。 */

import { sleep, lerp } from "../easing.js";
import { RESULT_AT } from "../music.js?v=10";
import { api } from "../api.js?v=10";

/* 选中后悬念段时间轴：0 上浮锁定 → 300 渐强摇晃 → 3600 末段抖动 → 4050 定拍
   → 4350 开盖 → 5000 弹窗（RESULT_AT 兜底对齐，恰逢歌里喊"停"） */
const LIFT_MS = 300;       // 选中盒上浮 + 金环锁定
const SHAKE_MS = 3300;     // 渐强摇晃（伴随加速 tick 声，悬念主段）
const RATTLE_MS = 450;     // 末段剧烈抖动
const SETTLE_MS = 300;     // 开盖前定拍（屏息一拍）
const POP_AT = LIFT_MS + SHAKE_MS + RATTLE_MS + SETTLE_MS; // ≈4350ms 开盖
const LID_MS = 640;        // 盖子顶飞翻滚时长（纯视觉，与展示期重叠）
const FLIP_MS = 250;       // 开始打乱时标签翻面成"?"的时长

/* 打乱阶段：8 只全动，14 次两两交换，间隔 90→240ms 先密后疏；
   移动走弧线（中点垂直偏移 + 轻旋），时长压在间隔以内 */
const SWAPS = 14;
const GAP_MIN = 90;
const GAP_MAX = 240;
const MOVE_FACTOR = 0.9;   // 单次移动时长 = 间隔 × 0.9，连环交换才不跳变

const REDUCED_SHUFFLE_MS = 300; // 减动效：象征性换位停顿
const REDUCED_OPEN_MS = 400;    // 减动效：选中后短暂停顿即开盒
const REVEAL_STEP_MS = 90;      // 弹窗关闭后揭底的错峰间隔

/* 布局：3×3 网格（窄屏 2 列），盒子绝对定位、left/top 由 JS 按格位计算——
   换位 = 改坐标 + WAAPI 补间，比 FLIP 记录还原更简单可靠 */
const GRID_GAP = 16;
const BOX_RATIO = 0.88;

export function mount(stage, ctx) {
  stage.innerHTML = `
    <div class="bb-wrap">
      <div class="bb-grid"></div>
      <button type="button" class="btn-primary bb-start">开始打乱</button>
      <p class="stage-hint">点开始打乱，停下后凭记忆选一只盒子</p>
    </div>`;
  const grid = stage.querySelector(".bb-grid");
  const startBtn = stage.querySelector(".bb-start");
  let phase = "attract"; // attract → shuffle → pick → reveal → attract
  let dead = false;
  let geometry = null;
  const timers = [];

  function render() {
    const all = ctx.items();
    const items = all.slice(0, 9);
    phase = "attract";
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
      box.addEventListener("click", () => pick(i));
      grid.appendChild(box);
    });
    startBtn.disabled = false;
    startBtn.textContent = "开始打乱";
    // 奖品超过 8+谢谢参与时盒面放不下：明示"看得到的只有前 9 项，但抽奖池是全量"
    if (all.length > 9) {
      stage.querySelector(".stage-hint").textContent =
        `奖品共 ${all.length} 项，盒面仅展示前 9 项——其余项仍可能被抽中`;
    }
    layout();
  }

  /* 计算格位几何并落位：容器高度由 JS 依据列数设定。
     列数恒为 3（3×3 九盒）：窄屏若改 2 列会变成 5 行，溢出锁定一屏的舞台
     （overflow:hidden 且 body 不可滚），手机上"开始打乱"按钮将不可达 */
  function layout() {
    const n = grid.children.length;
    if (!n) return;
    const cols = 3;
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

  /* 弧线换位：中点带垂直偏移 + 轻旋，比直线更像"甩"；动画落定后同步逻辑槽位，
     后续连环交换才从正确的视觉位置起步（不走样、不跳变） */
  function swapArc(a, b, dur) {
    const from = slotXY(a._slot);
    const to = slotXY(b._slot);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    const px = -dy / len, py = dx / len; // 垂直于连线方向
    const lift = (Math.random() < 0.5 ? -1 : 1) * Math.min(34, len * 0.18);
    const midAx = dx / 2 + px * lift;
    const midAy = dy / 2 + py * lift;
    const tilt = lift > 0 ? 5 : -5;
    const opts = { duration: dur, easing: "cubic-bezier(.3,.7,.35,1)" };
    const animA = a.animate(
      [
        { transform: "translate(0,0) rotate(0)" },
        { transform: `translate(${midAx}px, ${midAy}px) rotate(${tilt}deg)`, offset: 0.5 },
        { transform: `translate(${dx}px, ${dy}px) rotate(0)` },
      ],
      opts
    );
    const animB = b.animate(
      [
        { transform: "translate(0,0) rotate(0)" },
        { transform: `translate(${-midAx}px, ${-midAy}px) rotate(${-tilt}deg)`, offset: 0.5 },
        { transform: `translate(${-dx}px, ${-dy}px) rotate(0)` },
      ],
      opts
    );
    // finished 必须接 catch：换位中途切玩法时 DOM 已移除，拒绝不能变成 unhandled rejection
    animA.finished.catch(() => {});
    animB.finished.catch(() => {});
    return Promise.all([animA.finished, animB.finished]).catch(() => {}).then(() => {
      [a._slot, b._slot] = [b._slot, a._slot];
      placeAt(a, a._slot);
      placeAt(b, b._slot);
    });
  }

  /* 疯狂打乱：8 只全部参与，14 次两两交换（随机配对、可连续动同一只），
     间隔 90→240ms 先密后疏，哒哒声随节奏渐强——内容全程隐藏，纯盲选仪式感 */
  async function shuffle(boxes) {
    for (let i = 0; i < SWAPS; i++) {
      if (dead) return; // 打乱中切玩法：立刻收声，别在新玩法上继续响
      const p = i / (SWAPS - 1);
      const gap = lerp(GAP_MIN, GAP_MAX, p);
      const a = boxes[(Math.random() * boxes.length) | 0];
      let b = a;
      while (b === a) b = boxes[(Math.random() * boxes.length) | 0];
      ctx.fx.sound.tick(0.35 + p * 0.55);
      await Promise.all([swapArc(a, b, gap * MOVE_FACTOR), sleep(gap)]);
    }
  }

  /* 选中后悬念主段：振幅 2→18 的渐强摇晃，配 10 记间隔 330ms 的加速 tick */
  async function shakeRamp(box) {
    const tickLoop = (async () => {
      for (let t = 0; t < 10; t++) {
        ctx.fx.sound.tick(0.4 + t * 0.06);
        await sleep(330);
      }
    })();
    const frames = [];
    const steps = 26;
    for (let i = 0; i <= steps; i++) {
      const p = i / steps;
      const amp = 2 + 16 * p;
      const tilt = Math.sin(p * Math.PI * 12) * amp;
      frames.push({
        transform: `translateX(${tilt}px) rotate(${tilt * 0.35}deg)`,
        offset: p,
        easing: "ease-in-out",
      });
    }
    await Promise.all([
      box.animate(frames, { duration: SHAKE_MS }).finished.catch(() => {}),
      tickLoop,
    ]);
  }

  /* 末段剧烈抖动：开盖前最后一记"憋不住了" */
  async function rattle(box) {
    const frames = [];
    const steps = 12;
    for (let i = 0; i <= steps; i++) {
      const p = i / steps;
      const tilt = Math.sin(p * Math.PI * 18) * 18 * (1 - p * 0.3);
      frames.push({
        transform: `translateX(${tilt}px) rotate(${tilt * 0.5}deg)`,
        offset: p,
        easing: "ease-in-out",
      });
    }
    await box.animate(frames, { duration: RATTLE_MS }).finished.catch(() => {});
  }

  /* 开盖三连：填奖品 → 盖子顶飞翻滚落地 → 彩带迸在盒心 */
  function pop(box, result) {
    fillPrize(box, result);
    box.classList.add("is-open");
    ctx.fx.sound.pop();
    if (!ctx.reduced) {
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

  /* 第一步：开始打乱（不产生结果、不起播音乐——打乱只是选盒游戏） */
  async function startShuffle() {
    if (phase !== "attract" || dead) return;
    const boxes = [...grid.children];
    // 奖品清单未就绪时 mount 可能只渲染出"谢谢参与"1 盒（首屏 mount 先于 loadPrizes、
    // 或弱网加载失败）——此时换位循环会在"随机找另一只"上死循环，拒绝开始
    if (boxes.length < 2) {
      ctx.fx.toast("奖品清单还没加载好，稍等一下再点开始");
      return;
    }
    phase = "shuffle";
    ctx.fx.sound.click();
    startBtn.disabled = true;
    startBtn.textContent = "打乱中…";
    boxes.forEach((b) => {
      b.disabled = true;
      b.classList.remove("is-floating"); // 停 idle 浮动，避免与换位 transform 互相覆盖
    });
    grid.classList.add("is-shuffling");
    // 点开始的一瞬全部翻面成"?"：打乱全程不显示内容（盲选到底）
    boxes.forEach((b) => b.classList.add("is-q"));
    if (ctx.reduced) {
      await sleep(REDUCED_SHUFFLE_MS);
    } else {
      await sleep(FLIP_MS);
      await shuffle(boxes);
    }
    if (dead) return; // 打乱中切了玩法：别在已销毁的实例上继续收尾发声
    grid.classList.remove("is-shuffling");
    ctx.fx.sound.pop(); // 打乱收拍
    phase = "pick";
    startBtn.textContent = "凭记忆选一只盒子";
    boxes.forEach((b) => {
      b.disabled = false;
      b.classList.add("is-invite"); // 呼吸脉动邀请选盒
    });
  }

  /* 第二步：选盒（此刻才真实抽奖 + 起播音乐），悬念走满 RESULT_AT 开盒 */
  async function pick(index) {
    if (phase !== "pick" || dead) return;
    phase = "reveal";
    ctx.fx.sound.click();
    const [result, sampled] = await Promise.all([
      ctx.draw(),
      api.sample(8).catch(() => ({ samples: [] })), // 9 盒选 1，其余 8 盒的揭底分布
    ]);
    if (!result || dead) {
      phase = "pick";
      return;
    }
    const t0 = performance.now(); // = 音乐起播点，各阶段终点用 phaseEnd 兜底对齐
    const phaseEnd = (ms) => sleep(Math.max(0, ms - (performance.now() - t0)));

    const boxes = [...grid.children];
    boxes.forEach((b) => {
      b.disabled = true;
      b.classList.remove("is-invite");
    });
    const box = boxes[index];
    const others = boxes.filter((_, i) => i !== index);
    box.classList.add("is-picked");

    if (ctx.reduced) {
      await sleep(REDUCED_OPEN_MS);
      pop(box, result);
      await sleep(150);
    } else {
      await phaseEnd(LIFT_MS);
      await shakeRamp(box);
      await rattle(box);
      await phaseEnd(POP_AT);
      pop(box, result);
      await phaseEnd(RESULT_AT * 1000);
    }

    const choice = await ctx.reveal(result);
    if (dead) return;

    // 弹窗关闭后揭底：其余 7 盒按真实采样翻开，展示"如果选它们"的分布
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
    render(); // 回到待选态
    if (choice === "again") {
      // 与其他玩法一致：弹窗点"再抽一次"自动开新一轮打乱
      timers.push(setTimeout(() => startShuffle(), 200));
    }
  }

  startBtn.addEventListener("click", startShuffle);
  const onPrizes = () => { if (phase === "attract" && !dead) render(); };
  window.addEventListener("lucky:prizes", onPrizes);
  const ro = new ResizeObserver(() => { if (phase === "attract" && !dead) layout(); });
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
