/* 特效层：合成音效 / 彩带 / 背景氛围 / 结果弹窗 / 轻提示。
   无任何外部素材：音效由 WebAudio 合成，画面由 canvas 绘制，离线可用。 */

import { rand } from "./easing.js";

const reducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* HTML 转义：奖品名/emoji 可由后台或外部库存写入，拼 innerHTML 前必须过一遍 */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function cssVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

function confettiPalette() {
  return cssVar("--confetti").split(",").map((c) => c.trim()).filter(Boolean);
}

/* ============ 音效（WebAudio 合成） ============ */

const sound = {
  ctx: null,
  enabled: localStorage.getItem("lucky.sound") !== "0",

  ensure() {
    if (!this.enabled) return null;
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC();
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },

  blip(freq, dur = 0.05, type = "square", gain = 0.05, delay = 0) {
    const ctx = this.ensure();
    if (!ctx) return;
    const t0 = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(gain, t0 + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  },

  tick(intensity = 0.5) {
    const g = 0.02 + 0.06 * Math.min(1, intensity);
    this.blip(1400 + rand(-60, 60) + 500 * intensity, 0.035, "square", g);
  },

  click() {
    this.blip(880, 0.06, "sine", 0.05);
  },

  pop() {
    this.blip(520, 0.09, "triangle", 0.08);
    this.blip(780, 0.07, "triangle", 0.05, 0.05);
  },

  win() {
    const notes = [523.25, 659.25, 783.99, 1046.5];
    notes.forEach((f, i) => this.blip(f, 0.22, "triangle", 0.075, i * 0.095));
    this.blip(1318.5, 0.4, "triangle", 0.06, notes.length * 0.095);
  },

  /* 超级大奖琶音：比 win() 更华丽——C5-E5-G5-C6-E6 快速上行 + 高八度回声强调
     + 结尾 C6 长音和弦 + 高频 shimmer 碎音。供主线程在大奖轮的音乐收刀回调里
     替换 sound.win() 使用；slot 演出层自身不调用（避免与收刀琶音撞车，
     音乐未开启的大奖轮保持纯视觉静音——取舍已与主线程约定）。 */
  jackpot() {
    const notes = [523.25, 659.25, 783.99, 1046.5, 1318.5];
    notes.forEach((f, i) => this.blip(f, 0.16, "triangle", 0.07, i * 0.08));
    // 高八度回声强调
    notes.forEach((f, i) => this.blip(f * 2, 0.12, "sine", 0.04, 0.42 + i * 0.06));
    // 结尾长音：C6 主音 + E6/G6 叠出和弦感
    this.blip(1046.5, 0.9, "triangle", 0.07, 0.78);
    this.blip(1318.5, 0.9, "sine", 0.045, 0.78);
    this.blip(1567.98, 0.9, "sine", 0.035, 0.78);
    // 高频 shimmer：玻璃质感碎音收尾
    for (let i = 0; i < 6; i++) {
      this.blip(2093 + i * 173, 0.1, "sine", 0.02, 0.95 + i * 0.07);
    }
  },

  thanks() {
    this.blip(329.63, 0.28, "sine", 0.05);
    this.blip(261.63, 0.42, "sine", 0.045, 0.16);
  },

  toggle() {
    this.enabled = !this.enabled;
    localStorage.setItem("lucky.sound", this.enabled ? "1" : "0");
    return this.enabled;
  },
};

/* ============ 彩带（canvas 物理粒子） ============ */

const confetti = {
  canvas: null,
  ctx: null,
  parts: [],
  raf: 0,

  init() {
    this.canvas = document.getElementById("confetti");
    this.ctx = this.canvas.getContext("2d");
    const resize = () => {
      this.canvas.width = innerWidth * devicePixelRatio;
      this.canvas.height = innerHeight * devicePixelRatio;
      this.ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    };
    resize();
    addEventListener("resize", resize);
  },

  spawn(n, origin, angle, spread, power) {
    const palette = confettiPalette();
    const colors = palette.length ? palette : ["#F5C451", "#E8434E", "#FFF6E5"];
    for (let i = 0; i < n; i++) {
      const a = angle + rand(-spread / 2, spread / 2);
      const v = power * rand(0.55, 1.15);
      this.parts.push({
        x: origin.x, y: origin.y,
        vx: Math.cos(a) * v, vy: Math.sin(a) * v,
        g: rand(0.16, 0.24), drag: rand(0.985, 0.995),
        rot: rand(0, Math.PI * 2), vr: rand(-0.22, 0.22),
        w: rand(6, 12), h: rand(4, 8),
        color: colors[(Math.random() * colors.length) | 0],
        circle: Math.random() < 0.25,
        wob: rand(0, Math.PI * 2), wobV: rand(0.15, 0.32),
        ttl: rand(2.2, 3.6), age: 0,
      });
    }
    if (!this.raf) this.loop();
  },

  cannons() {
    const w = innerWidth, h = innerHeight;
    this.spawn(70, { x: w * 0.08, y: h + 12 }, -Math.PI / 2.35, 0.5, rand(15, 20));
    this.spawn(70, { x: w * 0.92, y: h + 12 }, -Math.PI + Math.PI / 2.35, 0.5, rand(15, 20));
  },

  burstAt(x, y) {
    this.spawn(42, { x, y }, rand(0, Math.PI * 2), Math.PI * 2, rand(6, 10));
  },

  loop() {
    this.raf = requestAnimationFrame(() => this.loop());
    const { ctx } = this;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    this.parts = this.parts.filter((p) => p.age < p.ttl && p.y < innerHeight + 40);
    if (!this.parts.length) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
      return;
    }
    for (const p of this.parts) {
      p.age += 1 / 60;
      p.vy += p.g;
      p.vx *= p.drag;
      p.vy *= p.drag;
      p.x += p.vx + Math.sin(p.wob) * 0.6;
      p.y += p.vy;
      p.rot += p.vr;
      p.wob += p.wobV;
      const alpha = Math.max(0, Math.min(1, (p.ttl - p.age) / 0.5));
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.scale(1, 0.35 + 0.65 * Math.abs(Math.cos(p.wob)));
      ctx.fillStyle = p.color;
      if (p.circle) {
        ctx.beginPath();
        ctx.arc(0, 0, p.w / 2.4, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      }
      ctx.restore();
    }
  },
};

/* ============ 背景氛围（每主题一套轻量粒子） ============ */

const bgfx = {
  canvas: null, ctx: null, raf: 0, theme: "festive", stars: [], motes: [], clouds: [], sparks: [], nextFw: 0,

  init() {
    this.canvas = document.getElementById("bg-canvas");
    this.ctx = this.canvas.getContext("2d");
    const resize = () => {
      this.canvas.width = innerWidth * devicePixelRatio;
      this.canvas.height = innerHeight * devicePixelRatio;
      this.ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      this.seed();
    };
    resize();
    addEventListener("resize", resize);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.stop();
      else this.start();
    });
  },

  setTheme(theme) {
    this.theme = theme;
    this.seed();
    this.start();
  },

  seed() {
    const w = innerWidth, h = innerHeight;
    this.stars = Array.from({ length: 90 }, () => ({
      x: rand(0, w), y: rand(0, h * 0.9), r: rand(0.5, 1.8), tw: rand(0, Math.PI * 2), tv: rand(0.02, 0.07),
    }));
    this.motes = Array.from({ length: 44 }, () => ({
      x: rand(0, w), y: rand(0, h), r: rand(1, 2.6), vy: rand(-0.35, -0.1), vx: rand(-0.12, 0.12), tw: rand(0, Math.PI * 2),
    }));
    this.clouds = Array.from({ length: 5 }, (_, i) => ({
      x: rand(0, w), y: rand(h * 0.08, h * 0.6), s: rand(0.6, 1.4), v: rand(0.08, 0.22) * (i % 2 ? 1 : -1),
    }));
    this.sparks = [];
  },

  start() {
    if (reducedMotion() || document.hidden) return;
    if (!this.raf) this.raf = requestAnimationFrame(() => this.loop(performance.now()));
  },

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  },

  loop(now) {
    this.raf = requestAnimationFrame((t) => this.loop(t));
    const { ctx } = this;
    const w = innerWidth, h = innerHeight;
    ctx.clearRect(0, 0, w, h);
    const t = now / 1000;

    if (this.theme === "neon" || this.theme === "pixel") {
      const color = this.theme === "neon" ? "rgba(180,214,255," : "rgba(255,236,39,";
      for (const s of this.stars) {
        s.tw += s.tv;
        const a = 0.25 + 0.5 * (0.5 + 0.5 * Math.sin(s.tw));
        ctx.fillStyle = color + a + ")";
        if (this.theme === "pixel") ctx.fillRect(s.x, s.y, 3, 3);
        else { ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill(); }
      }
    } else if (this.theme === "festive" || this.theme === "national") {
      const gold = this.theme === "festive" ? "rgba(245,196,81," : "rgba(255,222,0,";
      for (const m of this.motes) {
        m.x += m.vx; m.y += m.vy; m.tw += 0.03;
        if (m.y < -6) { m.y = h + 6; m.x = rand(0, w); }
        const a = 0.18 + 0.4 * (0.5 + 0.5 * Math.sin(m.tw));
        ctx.fillStyle = gold + a + ")";
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
        ctx.fill();
      }
      if (this.theme === "national") this.fireworks(ctx, w, h, now);
    } else if (this.theme === "macaron") {
      ctx.fillStyle = "rgba(255,255,255,.85)";
      for (const c of this.clouds) {
        c.x += c.v;
        if (c.x < -260) c.x = w + 260;
        if (c.x > w + 260) c.x = -260;
        for (const [dx, dy, r] of [[0, 0, 46], [40, 10, 34], [-42, 12, 30], [12, -16, 30]]) {
          ctx.beginPath();
          ctx.arc(c.x + dx * c.s, c.y + dy * c.s, r * c.s, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    } else if (this.theme === "tech") {
      const y = ((now / 9) % (h + 220)) - 110;
      const grad = ctx.createLinearGradient(0, y - 90, 0, y + 90);
      grad.addColorStop(0, "rgba(0,229,255,0)");
      grad.addColorStop(0.5, "rgba(0,229,255,.05)");
      grad.addColorStop(1, "rgba(0,229,255,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, y - 90, w, 180);
      for (const m of this.motes) {
        m.y += m.vy * 0.4;
        if (m.y < -4) { m.y = h + 4; m.x = rand(0, w); }
        ctx.fillStyle = "rgba(0,229,255,.28)";
        ctx.fillRect(m.x, m.y, 2, 2);
      }
    }
  },

  fireworks(ctx, w, h, now) {
    if (now > this.nextFw) {
      this.nextFw = now + rand(1400, 2800);
      const cx = rand(w * 0.15, w * 0.85);
      const cy = rand(h * 0.12, h * 0.42);
      const hue = ["255,222,0", "255,90,95", "255,184,0"][(Math.random() * 3) | 0];
      for (let i = 0; i < 42; i++) {
        const a = (Math.PI * 2 * i) / 42 + rand(-0.06, 0.06);
        const v = rand(1.6, 3.4);
        this.sparks.push({ x: cx, y: cy, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 1, hue });
      }
    }
    this.sparks = this.sparks.filter((p) => p.life > 0);
    for (const p of this.sparks) {
      p.x += p.vx; p.y += p.vy;
      p.vy += 0.03; p.vx *= 0.985; p.vy *= 0.985;
      p.life -= 0.014;
      ctx.fillStyle = `rgba(${p.hue},${p.life * 0.85})`;
      ctx.fillRect(p.x, p.y, 2.4, 2.4);
    }
  },
};

/* ============ 结果弹窗 ============ */

const reveal = {
  mask: null,

  init() {
    this.mask = document.getElementById("reveal");
    document.getElementById("reveal-close").addEventListener("click", () => this.close("close"));
    document.getElementById("reveal-again").addEventListener("click", () => this.close("again"));
    this.mask.addEventListener("click", (e) => {
      if (e.target === this.mask) this.close("close");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.mask.hidden) this.close("close");
    });
  },

  show(result, opts = {}) {
    const win = result.result === "prize";
    const card = document.getElementById("reveal-card");
    card.classList.toggle("is-thanks", !win);
    // 多奖品结果（老虎机对对碰）：prizes 数组 → 同类合并 ×n；三钻=超级大奖
    const prizes = Array.isArray(result.prizes) && result.prizes.length
      ? result.prizes
      : result.prize ? [result.prize] : [];
    const parts = [];
    for (const p of prizes) {
      const e = parts.find((x) => x.id === p.id);
      if (e) e.n += 1;
      else parts.push({ ...p, n: 1 });
    }
    // 单一奖品多件（三同×2）也要在弹窗里带 ×n——现场按弹窗发奖，漏显示件数会少发
    const soloLabel = parts.length === 1 && parts[0].n > 1
      ? `${parts[0].name} ×${parts[0].n}` : null;
    const label = parts.map((p) => (p.n > 1 ? `${p.name} ×${p.n}` : p.name)).join("、");
    const isJackpot =
      result.game === "slot" &&
      Array.isArray(result.symbols) &&
      result.symbols.length === 3 &&
      result.symbols.every((s) => s === "diamond") &&
      prizes.length > 0;
    document.getElementById("reveal-kicker").textContent =
      win ? (isJackpot ? "💎 超级大奖" : parts.length > 1 ? "🎉 多重中奖" : "🎉 恭喜中奖") : "谢谢参与";
    document.getElementById("reveal-emoji").textContent = win ? (isJackpot ? "💎" : parts[0].emoji) : "🙏";
    document.getElementById("reveal-name").textContent = win
      ? (isJackpot ? "全是你的！" : parts.length > 1 ? label : soloLabel || parts[0].name)
      : "下次一定";
    // 多奖品/多件（超级大奖、三同大奖、三同×2）：方格排列奖品，与双钻自选框同款视觉。
    // 奖品名/emoji 可能来自后台 CRUD 或外部库存，拼 innerHTML 前必须转义（存储型 XSS）
    const gridEl = document.getElementById("reveal-grid");
    if (gridEl) {
      if (win && (parts.length > 1 || (parts[0] && parts[0].n > 1))) {
        gridEl.hidden = false;
        gridEl.innerHTML = parts
          .map((p) => `<span class="rg-chip"><span class="rg-emoji">${esc(p.emoji)}</span><span class="rg-name">${esc(p.name)}${p.n > 1 ? ` ×${p.n}` : ""}</span></span>`)
          .join("");
      } else {
        gridEl.hidden = true;
        gridEl.innerHTML = "";
      }
    }
    document.getElementById("reveal-note").textContent = win
      ? (isJackpot
        ? "这些奖品全部归你，找管理员一次性领取～"
        : parts.length > 1
          ? `${label} 已收入囊中，记得找管理员领取～`
          : `好运直达！「${soloLabel || parts[0].name}」已收入囊中，记得找管理员领取～`)
      : "差一点点而已——好运气正在打包，下一发就到。";
    this.mask.hidden = false;
    document.getElementById("reveal-close").focus();
    if (win) {
      if (!reducedMotion()) confetti.cannons();
      // 音乐在场时琶音由 music 收刀回调触发（fanfareByMusic），此处不响避免双音
      if (!opts.fanfareByMusic) sound.win();
    } else if (!opts.musicRound) {
      // 音乐在场时，"没中"+哭声就是判词，不再叠加默认谢谢音效
      sound.thanks();
    }
    return new Promise((resolve) => { this._resolve = resolve; });
  },

  close(choice) {
    if (this.mask.hidden) return;
    this.mask.hidden = true;
    if (this._resolve) this._resolve(choice);
    this._resolve = null;
  },
};

/* ============ 轻提示 ============ */

function toast(msg) {
  let el = document.getElementById("lucky-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "lucky-toast";
    el.style.cssText =
      "position:fixed;left:50%;bottom:34px;transform:translateX(-50%);z-index:99;" +
      "padding:10px 20px;border-radius:999px;background:rgba(0,0,0,.78);color:#fff;" +
      "font-size:14px;pointer-events:none;transition:opacity .3s ease;opacity:0;";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.opacity = "1";
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.opacity = "0"; }, 2200);
}

export const fx = {
  sound, confetti, toast, reducedMotion, esc,
  init() {
    confetti.init();
    bgfx.init();
    reveal.init();
  },
  setTheme(theme) {
    bgfx.setTheme(theme);
  },
  async showResult(result, opts = {}) {
    return reveal.show(result, opts);
  },
};
