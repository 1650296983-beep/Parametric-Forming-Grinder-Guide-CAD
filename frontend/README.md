# 导轨生成器前端

这是一个面向本地 Python 生成器的 React/Vite 前端。界面遵循 Stitch 导出的工业设计系统，但业务规则仅通过 `src.web_api` 调用现有 Python 模块，不在前端重复工艺计算。

## 本地启动

首次使用时，在项目根目录准备依赖：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cd frontend && npm ci
```

以后从项目根目录一键启动 API 和前端：

```bash
./scripts/start_web.sh
```

浏览器打开 `http://127.0.0.1:5173`；在启动终端按 `Ctrl+C` 可停止本次启动的服务。

启动前需要在项目根目录将 `.env.example` 复制为 `.env`，填写管理员用户名、密码和
`CAD_SESSION_SECRET`。管理员账号可配置为 `sz2026`；普通用户通过
`CAD_OPERATOR_ACCOUNTS_JSON` 配置。普通用户只能下载通过校验的 release DXF；
管理员还可下载 debug DXF、截面预览、尺寸定义点审计和校验报告。

当前 Web 任务适配层已接入单导轨及三头机双导轨（下上上、上上上）的显式双规格输入。
双导轨任务复用 `DualGuideTemplateEngine`，两段导轨必须同步更新，并通过尺寸定义点审计后才会提供正式图纸。

正式 DXF 下载名称统一为 `成品规格（磨前规格）机台类型.dxf`，且不包含规格
中的公差。为兼容常见文件系统，规格内的 `*` 会显示为 `×`。

生成结果的 PNG 为带关键尺寸标注的导轨截面预览，不包含导轨侧视图。
