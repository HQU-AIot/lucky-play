/* 形式注册表：id ↔ 名称/图标/描述 + 挂载器 */

import * as wheel from "./wheel.js?v=10";
import * as grid from "./grid.js?v=10";
import * as blindbox from "./blindbox.js?v=10";
import * as flip from "./flip.js?v=10";
import * as slot from "./slot.js?v=10";
import * as gacha from "./gacha.js?v=10";

export const FORMS = {
  wheel: {
    id: "wheel", icon: "🎡", name: "大转盘", desc: "经典转盘，蓄力冲刺仪式感拉满",
    mount: wheel.mount,
  },
  grid: {
    id: "grid", icon: "🧨", name: "九宫格", desc: "灯圈三圈半，越走越慢最揪心",
    mount: grid.mount,
  },
  blindbox: {
    id: "blindbox", icon: "🎁", name: "盲盒", desc: "亲手拆盒，摇晃爆开的一瞬间",
    mount: blindbox.mount,
  },
  flip: {
    id: "flip", icon: "🃏", name: "翻牌", desc: "八张暗牌凭手感，翻开见分晓",
    mount: flip.mount,
  },
  slot: {
    id: "slot", icon: "🎰", name: "老虎机", desc: "三滚轮错峰停定，灯亮开奖",
    mount: slot.mount,
  },
  gacha: {
    id: "gacha", icon: "🥚", name: "扭蛋机", desc: "转旋钮掉蛋，砸开见惊喜",
    mount: gacha.mount,
  },
};
