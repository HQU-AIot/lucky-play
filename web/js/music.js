/* 背景音乐：《中奖概率倍儿高》（碎碎冰，8.04s 整曲，web/assets/lucky-song.mp3）。
   全部玩法共用一条时间轴：
   - 点击开抽 → api.draw 返回后起播，动画同时开跑；
   - RESULT_AT = 5.0s（实听校准，歌里喊"停"）→ 所有玩法此刻落定结果；
   - 没中 → 歌继续唱"没中"+哭声，直到 8s 自然收尾；
   - 中奖 → 歌播到后台配置的 winStopAt 秒处快速收刀（位置由管理员试听调节，
     默认 5.5s），刀落后接胜利琶音。不做任何人声采样/叠加——干净利落一刀。
   音效开关（fx.sound）独立于本开关；prefers-reduced-motion 时不播音乐。 */

export const RESULT_AT = 5.0; // 歌中"停"的时刻 = 各玩法统一出结果时刻（秒）

const SRC = "../assets/lucky-song.mp3?v=10";
const VOLUME = 0.95;
const FADE_TICK = 25;   // 收刀淡出间隔 ms
const FADE_STEP = 0.25; // 每帧衰减量：≈0.1s 干脆收刀

let audio = null;
let fadeTimer = 0;
let roundActive = false;
let winStopAt = 5.5; // 后台可调：中奖时音乐停止位置（秒）

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function stopFade() {
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

  /** 后台 /api/meta 下发的中奖收刀位置（秒）。 */
  setWinStopAt(v) {
    const n = Number(v);
    if (Number.isFinite(n) && n >= 0.5 && n <= 8) winStopAt = n;
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

  /** 中奖：歌播到后台配置的 winStopAt 秒处快速收刀（默认 5.5s），收刀完成后回调
      onStopped（接胜利琶音，唯一触发点）。startRound/关闭音乐会取消未落的刀。 */
  winStop(onStopped) {
    if (!audio || !roundActive) {
      onStopped?.();
      return;
    }
    roundActive = false;
    stopFade();
    const a = audio;
    const waitMs = Math.max(0, (winStopAt - a.currentTime) * 1000);
    fadeTimer = setTimeout(() => {
      fadeTimer = 0;
      let v = a.volume;
      fadeTimer = setInterval(() => {
        v -= FADE_STEP;
        if (v <= 0.05) {
          stopFade();
          a.pause();
          a.volume = VOLUME; // 复位，下一轮从正常音量起播
          onStopped?.();
        } else {
          a.volume = v;
        }
      }, FADE_TICK);
    }, waitMs);
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
