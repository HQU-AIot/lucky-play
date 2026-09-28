/* 形式注册表：id ↔ 名称/图标/描述 + 挂载器 */

import * as wheel from "./wheel.js?v=10";
import * as grid from "./grid.js?v=10";
import * as blindbox from "./blindbox.js?v=10";
import * as slot from "./slot.js?v=10";

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
    id: "blindbox", icon: "🎁", name: "盲盒", desc: "点开始疯狂打乱，凭记忆选盒开惊喜",
    mount: blindbox.mount,
  },
  slot: {
    id: "slot", icon: "🎰", name: "老虎机", desc: "三滚轮错峰停定，灯亮开奖",
    mount: slot.mount,
  },
};
