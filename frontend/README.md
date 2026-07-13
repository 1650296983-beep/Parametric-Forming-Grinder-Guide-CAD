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

当前 Web 任务适配层已接入单导轨机台的显式双规格输入；双导轨生成需要复用现有 `DualGuideTemplateEngine` 后再开放任务入口。

正式 DXF 下载名称统一为 `成品规格（磨前规格）机台类型.dxf`，且不包含规格
中的公差。为兼容常见文件系统，规格内的 `*` 会显示为 `×`。
