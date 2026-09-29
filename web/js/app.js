/* 总调度：主题/玩法切换、抽奖锁、余量与战绩、活动信息。 */

import { api } from "./api.js?v=10";
import { fx } from "./fx.js?v=10";
import { music } from "./music.js?v=10";
import { FORMS } from "./forms/index.js?v=10";

const THEMES = [
  { id: "festive", name: "红金福运", desc: "中式礼堂红灯笼下的鎏金转盘", swatches: ["#6D1420", "#E8434E", "#F5C451", "#FFF6E5"] },
  { id: "national", name: "国庆盛典", desc: "旗帜红金星漫天，烟花夜幕压轴", swatches: ["#C8102E", "#FFDE00", "#FFB800", "#FFF8E7"], badge: "9·30 前夜" },
  { id: "neon", name: "星空霓虹", desc: "深夜电玩城的霓虹抽奖机", swatches: ["#0A0F22", "#FF3D8A", "#22D3EE", "#A78BFA"] },
  { id: "macaron", name: "云朵马卡龙", desc: "甜品柜上的软萌抽奖，圆润无棱角", swatches: ["#FFA6C1", "#A8D8EA", "#FFE7A3", "#B8E0C2"] },
  { id: "tech", name: "未来科技", desc: "舱内概率终端，一切皆读数", swatches: ["#04121F", "#00E5FF", "#1976FF", "#FFC857"] },
  { id: "pixel", name: "像素街机", desc: "PICO-8 街机机位，插币开闸出票", swatches: ["#1A1C2C", "#FF004D", "#FFEC27", "#29ADFF"] },
];

const THANKS_ITEM = { id: "thanks", name: "谢谢参与", emoji: "🙏", remaining: Infinity };

const state = {
  theme: localStorage.getItem("lucky.theme") || "festive",
  form: localStorage.getItem("lucky.form") || "wheel",
  prizes: [],
  meta: {},
  busy: false,
};

const $ = (sel) => document.querySelector(sel);

/* ---------- 数据 ---------- */

async function loadMeta() {
  try {
    state.meta = await api.meta();
    $("#event-name").textContent = state.meta.event_name || "幸运抽奖";
    document.title = state.meta.event_name || "幸运抽奖";
    music.setWinStopAt(state.meta.win_stop_at);
  } catch {
    /* 首屏元信息失败不阻塞，用默认文案 */
  }
}

async function loadPrizes() {
  try {
    const data = await api.prizes();
    state.prizes = data.prizes;
  } catch {
    /* 数据未就绪时形式模块会在 lucky:prizes 到达后重绘 */
  } finally {
    window.dispatchEvent(new CustomEvent("lucky:prizes"));
  }
}

/* ---------- 抽奖上下文（交给各形式使用） ---------- */

// 超级大奖 = 有限库存最少的奖品（老虎机的机器演出用同一判定；后台改库存即时跟随）
function jackpotPrizeId() {
  const stockOf = (p) => (p.total ?? p.total_stock ?? 0);
  const finite = state.prizes.filter((p) => stockOf(p) > 0);
  if (!finite.length) return null;
  return finite.reduce((a, b) => (stockOf(b) < stockOf(a) ? b : a)).id;
}

const ctx = {
  reduced: fx.reducedMotion(),
  fx,
  items() {
    return [...state.prizes.map((p) => ({ ...p })), THANKS_ITEM];
  },
  async draw() {
    if (state.busy) return null;
    state.busy = true;
    try {
      const result = await api.draw();
      // 结果到手即起播：动画与音乐同一起跑线，5s 处歌喊"停"时各玩法恰好出结果
      music.startRound();
      return result;
    } catch {
      fx.toast("网络开小差了，再试一次");
      state.busy = false;
      return null;
    }
  },
  async reveal(result) {
    loadPrizes();
    const win = result.result === "prize";
    const musicRound = music.isPlaying();
    // 中奖且音乐在场：歌播到后台配置的收刀点，收刀回调里响琶音——
    // 琶音只此一处触发（fx 不再自行定时，避免双响叠加）；超级大奖换更华丽的琶音
    const fanfareByMusic = win && musicRound;
    const isJackpot = win && result.prize?.id === jackpotPrizeId();
    if (fanfareByMusic) music.winStop(() => (isJackpot ? fx.sound.jackpot() : fx.sound.win()));
    const choice = await fx.showResult(result, { musicRound, fanfareByMusic });
    state.busy = false;
    return choice;
  },
  refresh() {
    loadPrizes();
  },
};

/* ---------- 主题 / 玩法 ---------- */

let currentForm = null;

function applyTheme(id, announce = true) {
  if (state.busy) {
    fx.toast("这一轮转完再换风格～");
    return;
  }
  if (!THEMES.some((t) => t.id === id)) id = "festive"; // localStorage 残值兜底
  state.theme = id;
  document.body.dataset.theme = id;
  localStorage.setItem("lucky.theme", id);
  fx.setTheme(id);
  document.querySelectorAll("#theme-grid .theme-card").forEach((c) =>
    c.classList.toggle("is-active", c.dataset.id === id)
  );
  if (announce) window.dispatchEvent(new CustomEvent("lucky:theme"));
}

function applyForm(id) {
  if (state.busy) {
    fx.toast("这一轮转完再换玩法～");
    return;
  }
  if (!FORMS[id]) id = "wheel";
  state.form = id;
  localStorage.setItem("lucky.form", id);
  if (currentForm?.destroy) currentForm.destroy();
  const stage = $("#stage");
  stage.innerHTML = "";
  currentForm = FORMS[id].mount(stage, ctx) || null;
  document.querySelectorAll("#form-grid .form-card").forEach((c) =>
    c.classList.toggle("is-active", c.dataset.id === id)
  );
}

function buildThemeGrid() {
  const grid = $("#theme-grid");
  grid.innerHTML = "";
  for (const t of THEMES) {
    const btn = document.createElement("button");
    btn.className = "theme-card";
    btn.type = "button";
    btn.dataset.id = t.id;
    btn.innerHTML = `
      <span class="t-name">${t.name}
        ${t.badge ? `<span class="badge-now">${t.badge}</span>` : ""}
      </span>
      <span class="t-swatches">${t.swatches.map((c) => `<i style="background:${c}"></i>`).join("")}</span>
      <span class="t-desc">${t.desc}</span>`;
    btn.addEventListener("click", () => {
      fx.sound.click();
      applyTheme(t.id);
      closeOverlays();
    });
    grid.appendChild(btn);
  }
}

function buildFormGrid() {
  const grid = $("#form-grid");
  grid.innerHTML = "";
  for (const f of Object.values(FORMS)) {
    const btn = document.createElement("button");
    btn.className = "form-card";
    btn.type = "button";
    btn.dataset.id = f.id;
    btn.innerHTML = `<span class="f-icon">${f.icon}</span><span class="f-name">${f.name}</span><span class="f-desc">${f.desc}</span>`;
    btn.addEventListener("click", () => {
      fx.sound.click();
      applyForm(f.id);
      closeOverlays();
    });
    grid.appendChild(btn);
  }
}

function closeOverlays() {
  $("#overlay-theme").hidden = true;
  $("#overlay-form").hidden = true;
}

/* ---------- 启动 ---------- */

function init() {
  fx.init();
  buildThemeGrid();
  buildFormGrid();

  $("#btn-theme").addEventListener("click", () => {
    $("#overlay-form").hidden = true;
    $("#overlay-theme").hidden = false;
  });
  $("#btn-form").addEventListener("click", () => {
    $("#overlay-theme").hidden = true;
    $("#overlay-form").hidden = false;
  });
  document.querySelectorAll(".overlay").forEach((ov) => {
    ov.addEventListener("click", (e) => {
      if (e.target === ov || e.target.closest("[data-close]")) closeOverlays();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeOverlays();
    // 空格键抽奖：弹窗开着 = 再抽一次，否则 = 当前玩法的开始键；连按空格即可连续抽
    if (e.code !== "Space" || e.repeat || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.defaultPrevented) return; // 拉杆等自带空格处理的部件已在 target 阶段接手，别叠加触发
    if (!$("#overlay-theme").hidden || !$("#overlay-form").hidden) return; // 浮层打开时不抢空格
    const mask = $("#reveal");
    if (mask && !mask.hidden) {
      e.preventDefault();
      $("#reveal-again").click();
      return;
    }
    const el = document.activeElement;
    // 输入类不拦截；按钮聚焦时交给原生空格点击，避免双触发
    if (el && ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(el.tagName)) return;
    const start = [...$("#stage").querySelectorAll("button")].find(
      (b) => !b.disabled && b.offsetParent !== null &&
        ["wheel-hub", "slot-btn"].some((c) => b.classList.contains(c))
    );
    if (start) {
      e.preventDefault();
      start.click();
    }
  });

  const soundBtn = $("#btn-sound");
  const paintSound = () => {
    soundBtn.textContent = fx.sound.enabled ? "🔊" : "🔇";
    soundBtn.setAttribute("aria-pressed", String(fx.sound.enabled));
  };
  soundBtn.addEventListener("click", () => {
    fx.sound.toggle();
    paintSound();
    fx.sound.click();
  });
  paintSound();

  music.preload();
  const musicBtn = $("#btn-music");
  const paintMusic = () => {
    musicBtn.textContent = "🎵"; // 关闭态由 .is-off（降透明度）与 title 表达
    musicBtn.classList.toggle("is-off", !music.enabled);
    musicBtn.setAttribute("aria-pressed", String(music.enabled));
    musicBtn.title = music.enabled ? "音乐开关（点击关闭）" : "音乐已关（点击开启）";
  };
  musicBtn.addEventListener("click", () => {
    music.toggle();
    paintMusic();
    fx.sound.click();
  });
  paintMusic();

  applyTheme(state.theme, false);
  applyForm(state.form);
  loadMeta();
  loadPrizes();
}

init();