# Lucky Play 抽奖系统 · 设计方案

> 2026-09-26 起建。用户外出期间自主完成，产出**多种方案**供回来后挑选最终风格。
> 本文档即"方向稿"存档：每套主题含配色 token、字体、一句话概念、signature element。

## 0. 需求清单

| 需求 | 落地 |
| --- | --- |
| 随机抽奖 + 转盘两种形式 | 4 种形式：转盘 / 九宫格 / 盲盒 / 翻牌 |
| UI 多种选择、多生成 | 6 套主题皮肤（含国庆），任一形式 × 任一主题自由组合（24 种组合） |
| 查询剩余奖品接口 | `GET /api/prizes`（公开，无需鉴权） |
| 后台概率设置 | `/admin` 后台：各奖品权重、谢谢参与权重、动态转移开关与模式 |
| 谢谢参与概率可调 + 动态自调 | 权重随时可改；奖品被抽走时其概率按所选模式转移给谢谢参与 |
| 动画不突然 | 见 §3 动画规范：结果先行 + 蓄力→爆发→长减速→回弹，4-7 秒 |
| 国庆风格（9-30 国庆前一天抽奖） | `national` 主题 + 活动日期徽标/倒计时 |

奖品清单（来自 `docs/spec/奖品清单.jpg`）：

| 奖品 | 数量 | 视觉 |
| --- | --- | --- |
| 不二家棒棒糖 | 53 | 🍭 |
| 奶龙手办 | 36 | 🐲 |
| 口袋笔记本 | 18 | 📓 |
| 油画书签 | 8 | 🎨 |
| 鲨鱼匕首 | 6 | 🦈 |
| 电子爬宠 | 4 | 🦎 |
| 盖世小鸡手柄 | 1 | 🎮 |

另有"谢谢参与"（不限量）。转盘/九宫格展示 = 7 奖品 + 谢谢参与 = 8 格，天然契合。

## 1. 形式（4 种）

1. **wheel 转盘**：Canvas 绘制 8 扇区，指针在 12 点方向，扇区边界经过时指针弹性摆动 + tick 声。
2. **grid 九宫格**：3×3，周围 8 格为奖品/谢谢参与，中央"开始"按钮；高亮圈逐格跳动。
3. **blindbox 盲盒**：3 只盒子先出现，点选其一，盒子蓄力摇晃后爆开，奖品弹出。
4. **flip 翻牌**：8 张背面朝上的卡牌，选一张 3D 翻开即结果，其余保持牌面仅压暗（不翻出内容，避免"满屏谢谢参与"的观感）。

所有形式共用同一套结果流：**先请求 `/api/draw` 拿到结果 → 动画精确滑向该结果 → 结果弹窗**。

## 2. 主题（6 套，方向稿）

### A. `festive` 红金福运（推荐默认）
- 概念：中式喜庆礼堂——深红灯笼下的一台鎏金大转盘。
- Token：`--bg:#6D1420` `--surface:#8C1F28` `--ink:#FFF6E5` `--gold:#F5C451` `--accent:#E8434E` `--deep:#4A0D16`
- 字体：标题衬线（Noto Serif SC / 思源宋体系），正文系统黑体。
- Signature：鎏金描边转盘 + 两串灯笼垂帘 + 金箔粒子微闪。

### B. `national` 国庆盛典（本次 9-30 专用）
- 概念：国庆前夕的广场夜幕，旗帜红打底、金星漫天、天安门剪影压轴。
- Token：`--bg:#A00E24` `--surface:#C8102E` `--ink:#FFF8E7` `--star:#FFDE00` `--accent:#FFB800` `--deep:#7A0C1D`
- 字体：同 festive（庄重衬线标题）。
- Signature：五角星指针 + 背景烟花 canvas + "距 9·30 开奖"倒计时徽标；彩带用红金配色。

### C. `neon` 星空霓虹
- 概念：深夜电玩城的霓虹抽奖机。
- Token：`--bg:#070B18` `--surface:#0E1630` `--ink:#EAF2FF` `--neon:#FF3D8A` `--cyan:#22D3EE` `--violet:#A78BFA`
- 字体：无衬线 + 宽字距发光标题。
- Signature：霓虹描边发光转盘 + 透视网格地平线 + 星空粒子。

### D. `macaron` 云朵马卡龙
- 概念：甜品店柜台上的软萌抽奖，圆润到没有一根直线。
- Token：`--bg:#FDF3F7` `--surface:#FFFFFF` `--ink:#4A4458` `--blossom:#FFB7C5` `--sky:#A8D8EA` `--butter:#FFE7A3` `--mint:#B8E0C2`
- 字体：圆体优先（ui-rounded / 圆体系），正文系统黑体。
- Signature：软糖质感按钮（按下果冻 Q 弹）+ 飘云背景 + 糖果色彩带。

### E. `tech` 未来科技 HUD
- 概念：飞船舱内的概率抽取终端，一切皆读数。
- Token：`--bg:#04121F` `--surface:#07203A` `--ink:#D8F3FF` `--cyan:#00E5FF` `--blue:#1976FF` `--warn:#FFC857`
- 字体：等宽字体做标签读数 + 无衬线正文。
- Signature：HUD 刻度环 + 扫描线 + 抽奖时终端式"PROBABILITY COMPUTING"读数。

### F. `pixel` 像素街机
- 概念：PICO-8 调色板的街机厅老虎机位，插币、开闸、出票。
- Token：`--bg:#1A1C2C` `--surface:#29366F` `--ink:#F4F4F4` `--red:#FF004D` `--orange:#FFA300` `--yellow:#FFEC27` `--green:#00E436` `--blue:#29ADFF`
- 字体：等宽粗体 + 硬阴影（模拟像素字）。
- Signature：CRT 扫描线覆盖层 + 像素硬边框（box-shadow 阶梯）+ 8-bit 音效 tick。

## 3. 动画规范（调研结论落地）

来源：MDN cubic-bezier / GSAP Eases / Ant Design motion / easings.net（原理性结论，无时效问题）。

1. **结果先行**：服务端先出结果，动画只负责"精确到达"——杜绝"转过了再修正"的突兀。
2. **转盘**（5.5-7s，rAF 驱动）：蓄力回拉（-18°，0.45s ease-in）→ 爆发加速 → 长减速（easeOutQuint/Quart 混合，3.5s+）→ 过冲回摆（+2° 回弹）。全程 transform:rotate（GPU）。
3. **指针仪式感**：每经过一条扇区边界，指针弹性下压回弹（CSS transform 弹簧）+ WebAudio 合成 tick 声（无需音频素材）；减速期 tick 间隔自然拉长，这是"越来越紧张"的来源。
4. **九宫格**：步进间隔按 easeOutQuart 拉长（快→慢），≥3 圈后精准停在结果格，停格时格子脉冲放大 + 中奖格持续呼吸灯。
5. **盲盒**：盒子摇晃振幅渐增（0.9s）→ 盖子弹飞 + 纸屑迸发 → 奖品 spring 弹出（easeOutBack 过冲）。
6. **翻牌**：rotateY 3D 翻转（perspective 1200px），先快速翻 2 张"虚晃"再停在选中张（stagger 80ms），选中卡金色描边亮起。
7. **结果弹窗**：spring 缩放进场 cubic-bezier(0.34,1.56,0.64,1)；中奖 → 全屏彩带（canvas 物理粒子：重力/阻力/旋转）+ 胜利琶音；谢谢参与 → 灰白纸屑小概率飘落 + 温柔双音，不嘲讽。
8. **可访问性**：`prefers-reduced-motion` 时全部动画压缩为 ≤400ms 淡入淡出；动画期间禁止重复点击。

## 4. 概率模型（谢谢参与动态转移）

每个奖品：基础权重 `W_i`（后台可改）、总库存 `S_i`、剩余 `R_i`；谢谢参与基础权重 `W_0`。

| dynamic 模式 | 奖品有效权重 | 谢谢参与有效权重 |
| --- | --- | --- |
| `off` 关闭 | `W_i`（`R_i>0`），否则 0 | `W_0` |
| `per_win` 每抽一件渐移（默认，字面语义） | `W_i × R_i / S_i` | `W_0 + Σ W_i × (1 - R_i/S_i)` |
| `depleted` 抽空才整移 | `W_i`（`R_i>0`），否则 0 | `W_0 + Σ_{R_i=0} W_i` |

- `per_win`：每抽走一件奖品，该奖品"一份"的概率即时让给谢谢参与，库存抽空时恰好整体转移完。总概率质量恒定，只做再分配。
- 后台改动基础权重/补货即时生效；补货会让已转移概率自动"回流"（公式由库存推导，无漂移）。

默认权重（后台可改）：棒棒糖 30 / 奶龙 20 / 笔记本 15 / 书签 10 / 鲨鱼匕首 8 / 电子爬宠 6 / 手柄 2 / 谢谢参与 9（合计 100）。

## 5. 接口

公开：
- `GET /api/prizes` —— **剩余奖品查询接口**：`{event, prizes:[{id,name,emoji,remaining,total}], total_remaining}`
- `POST /api/draw` —— 抽奖：`{result:"prize"|"thanks", prize:{...}|null}`
- `GET /api/meta` —— 活动名 / 日期 / 主题无关信息

后台（请求头 `X-Admin-Token`，token 见 README）：
- `GET /api/admin/state` —— 权重/库存/配置/有效概率/统计
- `PUT /api/admin/weights` —— 批量改权重 + 谢谢参与权重
- `PUT /api/admin/stock` —— 补货/改库存
- `PUT /api/admin/dynamic` —— 动态转移开关 + 模式
- `PUT /api/admin/event` —— 活动名/日期
- `GET /api/admin/history?limit=` / `POST /api/admin/history/reset`

## 6. 技术栈

后端 Python 3.11+ / FastAPI / SQLite（uv 管理）；前端零构建原生 ES Modules + Canvas + CSS 变量主题系统（离线可用，无 CDN）。
