# 智能爬虫采集平台

面向网页爬取、API接入、增量抓取、反爬对抗与采集质量校验的数据采集平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集目标 | `targetsite` | 目标站点 | 站点编号、站点名称、入口URL |
| 抽取规则 | `selector` | 选择器规则 | 规则编号、归属站点、列表选择器 |
| 爬虫引擎 | `crawler` | 爬虫任务 | 任务编号、任务名称、关联站点 |
| 代理池 | `proxy` | 代理节点 | 节点编号、IP地址、端口号 |
| 反爬对抗 | `antiblock` | 反爬策略 | 策略编号、策略名称、触发条件 |
| 定时调度 | `schedule` | 调度计划 | 计划编号、关联任务、Cron表达式 |
| 数据提取 | `extractor` | 提取模板 | 模板编号、模板名称、输入URL |
| 采集校验 | `validate` | 校验规则 | 规则编号、校验字段、期望格式 |
| 失败重试 | `retry` | 重试策略 | 策略编号、适用任务、最大重试 |
| 存储落地 | `storage` | 存储配置 | 配置编号、存储类型、连接信息 |
| 重复去重 | `dedup` | 去重策略 | 策略编号、业务键列、去重算法 |
| 质量报告 | `quality` | 质量指标 | 指标编号、指标名称、统计口径 |
| 运行监控 | `monitor` | 监控大盘 | 大盘编号、关联任务、采集速率 |
| 告警中心 | `alert` | 告警规则 | 规则编号、监控对象、告警条件 |
| 采集API | `apigate` | API配置 | 配置编号、端点路径、请求方法 |
| 历史归档 | `archive` | 归档策略 | 策略编号、数据来源、归档周期 |
| 模板市场 | `template` | 采集模板 | 模板编号、模板名称、适用站点 |
| 采集流程 | `flowline` | 流程编排 | 流程编号、流程名称、步骤序列 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 去重策略版本化与阈值重算

重复去重在原 CRUD 之外提供「阈值调整 → 按新口径重算 → 数据报告 → 去重版本 → 存储落地」
的完整链路，核心领域逻辑在 `backend/app/dedup_versioning.py`，原始采集批次样例在
`backend/app/dedup_seed.py`（独立内部表，不计入运营概览的 18 个业务模块）。

关键规则：

- 阈值调整后按**新阈值 + 重新判定范围**对历史记录重新判定，已归档原始批次保持只读，
  重算永远只生成新的去重版本（冻结版/最新版），不改写原始数据。
- 去重策略数据报告记录**旧阈值、新阈值、阈值区间与重新判定范围**，并保留新旧两套保留记录、
  重复证据与口径冲突明细；规则 = 判定口径（算法/业务键列）+ 阈值上限。
- 未进入重算范围的记录不标记新口径，落地清单中保留 `未进入重算范围` 的原口径标记。
- 同一业务键新旧口径保留记录不同即口径冲突，同一策略始终只有一个 `是否当前=true` 的版本。
- 报告并发写入只允许一个提交成功（409 拒绝其余）；同一幂等键重复提交只生效一次，不产生第二条记录。
- 存储落地读取**已确认**报告生成去重落地清单，落地版本必须与报告确认的策略版本一致，
  第二份落地结果一律拒绝；结果同时在 `/api/dedup/landing` 与 `/api/storage/dedup-landing` 同源可见。
- 新增接口均为 `/api/dedup` 下的增量路由，既有去重接口的字段名与 `{items,total,page,size}`、
  `{ok,message,entry}` 返回结构保持不变。

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/dedup/recompute?strategy_code=` | 按新阈值/范围重算，生成数据报告与去重版本（201） |
| GET | `/api/dedup/reports`、`/api/dedup/reports/{编号}` | 报告列表与详情（含新旧证据、冲突、范围外记录） |
| POST | `/api/dedup/reports/{编号}/confirm` | 确认报告策略版本 |
| GET | `/api/dedup/versions` | 去重版本（冻结版/最新版、当前标记） |
| POST | `/api/dedup/versions/current?strategy_code=` | 在冻结版/最新版间切换当前版本 |
| GET | `/api/dedup/trace-source` | 沿调用链定位报告数据来源 |
| POST | `/api/dedup/landing`、`/api/storage/dedup-landing` | 生成/读取去重落地清单（201，重复拒绝 409） |

后端领域规则测试：`cd backend && .venv/bin/python -m unittest tests.test_dedup_versioning`。

领域：数据工程
子方向：数据采集、爬虫与RPA
