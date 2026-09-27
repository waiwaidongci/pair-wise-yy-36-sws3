# 企业排污许可与超标处置

汇总监测和工况，判断排放超标并跟踪复测、整改、执法与复查。

## 模块结构

- `app.py`：参数解析、依赖组装和HTTP服务启动。
- `src/domain.py`：数据结构、错误、状态和基础校验。
- `src/rules.py`：状态机、角色矩阵、优先级、期限和关闭不变量。
- `src/repository.py`：SQLite建表、事务、版本控制和审计链。
- `src/service.py`：权限检查、用例编排、并发控制和审计。
- `src/http_api.py`：JSON路由和统一错误响应。
- `src/audit.py`：UTC时间和SHA-256审计事件。
- `static/index.html`：最小演示页。
- `tests/`：完整流程、规则和失败测试。

## 初始化与启动

```bash
python3 app.py --db ./data.db --port 8313
```

默认端口为`8313`，首次启动自动建库。使用`X-Actor`和`X-Role`请求头传递身份。

## 主要接口

- `GET /health`
- `GET /api/items`
- `POST /api/items`
- `GET /api/items/{id}`
- `POST /api/items/{id}/records`
- `POST /api/items/{id}/transition`，必须提交`expected_version`
- `GET /api/items/{id}/inspections`
- `POST /api/items/{id}/inspections`，复查状态登记检查日期、承办人和现场结论
- `POST /api/items/{id}/inspections/{iid}/complete`，对待办检查登记复检结论
- `GET /api/audit`

允许角色：operator, compliance_officer, director, viewer。按浓度与许可限值计算超标倍数，异常读数先进入评估；关闭前必须没有未完成整改项。

## 复查检查交接

- 事件进入`inspection`后，合规员（compliance_officer）登记检查日期、承办人和现场结论（`passed`/`deferred`/`exceeded`）。
- 结论为`deferred`（暂缓）时必须填写复检日期与原因，检查单保持`pending`；同一事件只保留一笔待办检查，须复检完成后才能再登记。
- 结论为`exceeded`（发现新的超标问题）时事件自动退回`remediation`，并按最新浓度重算优先级和期限。
- 主任（director）只有在最近检查完成且问题全部关闭后才能归档，事件详情的`closure_blockers`会列出阻塞项。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
