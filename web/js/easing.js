/* 缓动函数（参考 GSAP Eases / easings.net 的标准曲线定义） */

export const lerp = (a, b, t) => a + (b - a) * t;

export const easeInQuad = (t) => t * t;
export const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);
export const easeOutExpo = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const rand = (min, max) => min + Math.random() * (max - min);
