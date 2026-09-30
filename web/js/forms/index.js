/* 形式注册表：id ↔ 名称/图标/描述 + 挂载器 */

import * as wheel from "./wheel.js?v=10";
import * as slot from "./slot.js?v=12";

export const FORMS = {
  wheel: {
    id: "wheel", icon: "🎡", name: "大转盘", desc: "经典转盘，蓄力冲刺仪式感拉满",
    mount: wheel.mount,
  },
  slot: {
    id: "slot", icon: "🎰", name: "老虎机", desc: "三滚轮错峰停定，灯亮开奖",
    mount: slot.mount,
  },
};
