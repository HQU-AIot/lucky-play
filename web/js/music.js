/* 背景音乐：《中奖概率倍儿高》（碎碎冰，8.04s 整曲，web/assets/lucky-song.mp3）。
   全部玩法共用一条时间轴：
   - 点击开抽 → api.draw 返回后起播，动画同时开跑；
   - RESULT_AT = 4.0s（实测响度尖峰，歌里喊"停"）→ 所有玩法此刻落定结果；
   - 没中 → 让歌唱完：~5s "没中"、7.2s 起哭声，直到 8s 收尾；
   - 中奖 → 让"停"喊完整后快速收歌，不播"没中"。
   音效开关（fx.sound）独立于本开关；prefers-reduced-motion 时不播音乐。 */

export const RESULT_AT = 4.0; // 歌中"停"的时刻 = 各玩法统一出结果时刻（秒）
export const SONG_END = 8.04; // 整曲时长（秒），仅作语义参考

const SRC = "../assets/lucky-song.mp3?v=6";
const VOLUME = 0.85;
const FADE_STEP = 0.12; // 每帧衰减量，30ms 间隔：0.85/0.12 ≈ 7 拍 ≈ 0.21s 淡出

let audio = null;
let fadeTimer = 0;
let fadeDelay = 0;
let roundActive = false;

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function stopFade() {
  if (fadeDelay) {
    clearTimeout(fadeDelay);
    fadeDelay = 0;
  }
  if (fadeTimer) {
    clearInterval(fadeTimer);
    fadeTimer = 0;
  }
}

export const music = {
  enabled: localStorage.getItem("lucky.music") !== "0",

  /** 页面初始化时预加载，首次点击起播零延迟。 */
  preload() {
    if (audio) return;
    audio = new Audio(SRC);
    audio.preload = "auto";
    audio.volume = VOLUME;
    audio.addEventListener("ended", () => { roundActive = false; });
    audio.load();
  },

  /** 每轮开始时调用（须处于点击引发的调用链内，浏览器才放行播放）。
      reduced 实时读取：系统偏好中途变更无需刷新页面即生效。 */
  startRound() {
    stopFade();
    roundActive = false;
    if (!audio || !this.enabled || reducedMotion()) return;
    try {
      audio.currentTime = 0;
      audio.volume = VOLUME;
      const p = audio.play();
      // 仅在真正开始播放后才算"音乐轮次"，被自动播放策略拒绝时
      // 动画照常走自有时钟，且默认谢谢音效不会被误跳过
      if (p?.then) p.then(() => { roundActive = true; }).catch(() => {});
      else roundActive = true;
    } catch {
      roundActive = false;
    }
  },

  isPlaying() {
    return roundActive;
  },

  /** 中奖：让 4.0s 的"停"完整喊出来（延 0.3s），再在 4.9s"没中"之前淡出。 */
  winFade() {
    if (!audio || !roundActive) return;
    roundActive = false;
    stopFade();
    const a = audio;
    fadeDelay = setTimeout(() => {
      fadeDelay = 0;
      let v = a.volume;
      fadeTimer = setInterval(() => {
        v -= FADE_STEP;
        if (v <= 0.03) {
          stopFade();
          a.pause();
          a.volume = VOLUME; // 复位，下一轮从正常音量起播
        } else {
          a.volume = v;
        }
      }, 30);
    }, 300);
  },

  /** 调试/测试用：底层 audio 元素只读访问。 */
  get element() {
    return audio;
  },

  toggle() {
    this.enabled = !this.enabled;
    localStorage.setItem("lucky.music", this.enabled ? "1" : "0");
    if (!this.enabled) {
      stopFade();
      roundActive = false;
      if (audio) audio.pause();
    }
    return this.enabled;
  },
};
