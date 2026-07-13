# 导轨生成器前端

这是一个面向本地 Python 生成器的 React/Vite 前端。界面遵循 Stitch 导出的工业设计系统，但业务规则仅通过 `src.web_api` 调用现有 Python 模块，不在前端重复工艺计算。

## 本地启动

在项目根目录安装 Python 依赖并启动 API：

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn src.web_api:app --reload
```

另开一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。

当前 Web 任务适配层已接入单导轨机台的显式双规格输入；双导轨生成需要复用现有 `DualGuideTemplateEngine` 后再开放任务入口。
