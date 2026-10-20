# 本地工作台场景与生成进度

此版本的工作台优化用于本地开发。发布标签与腾讯 COS stable 指针不因本地前端修改而变化；发布仍走既有签名、验收和镜像流程。

## 场景数据

`POST /api/designs/validate` 继续接受 `DesignInput`。响应保留已有计算字段，并增加：

- `derived.opening_max`：当前机台原开口上限；`center_opening` 为按公共 30% 规则计算后的实际开口。
- `derived.relief_diameter`、`relief_radius`：输入四处侧部避空的直径与半径；`center_transition_radius/count` 为中心固定两处 R0.50。
- `parsed.finished/preform`：Python 解析器的命名尺寸与公差。
- `scene`：同一 CAD writer 在临时目录中生成实际 DXF 后转换出的截面与侧视图。临时文件随后删除；`source=parametric_preview`，`release_ready=false`，不代表通过正式校验。

`DrawingScene` 的单位为 mm，坐标系为 `svg_y_down`（DXF Y 坐标取反）。各 view 带有限且非零的 `[minX,minY,maxX,maxY]` 边界。图元为 polyline 或 text，按 outline/cavity/dimensions/center 分组。ARC/CIRCLE 使用 ezdxf 的 sagitta=0.002 mm 精确圆弧离散；其他曲线与多段线通过 ezdxf path 离散。原图元 handle 用作稳定 ID。虚拟尺寸、箭头和文字来自 DXF 原生尺寸块，不在前端重算制造公式。

单导轨包含 `section_1`、`side_1`；双导轨包含 `section_1`、`side_1`、`section_2`、`side_2`、`assembly`。空间过滤保留实际截面、砂轮侧视与中心线，排除模板图框、debug/reference/control/formula 图层。单导轨完整保留 writer 已归类的截面/侧视原生尺寸；双导轨按尺寸真实定义点及半径尺寸在圆面上的箭头端点确定所属视图，不能用文字、箭头总边界裁掉超出截面的槽宽、厚度、外形等尺寸。父 DIMENSION 存在不含 `<>` 的显式审计文字时，用该文字替换虚拟块的首个文本，保持公差 `±` 和原显示值；含 `<>` 的原生测量显示继续来自虚拟块。六处避空由原图元保留，不用示意轮廓替代。只在成功晋级后读取实际正式 DXF 并标记 `source=release_dxf`。

## 异步任务

`POST /api/designs/jobs` 接受 `{design: DesignInput}`。在解析并验证输入后，先保存独立输入快照和任务状态，再返回 HTTP 202 `{task_id}`。ID 为同一历史任务的 12 位 ID。旧 `POST /api/designs/generate` 同步端点仍可使用。

每个服务进程只有一个后台生成 worker，最多再排队八个任务。排队期间状态为 queued；满队列返回 503 且不创建额外任务。worker 启动失败会释放容量并把已创建任务记为失败，不遗留无限运行状态。任务导航、轮询断线或新草稿都不取消后台任务。

`GET /api/tasks/{task_id}/progress` 使用现有本地身份授权，返回：

- `status`：running/passed/failed；`stage`：真实当前阶段。
- `events`：最多 40 条，含阶段、running/completed/failed、UTC 时间和说明。
- `scene`：尚未有图元时为 null；实际 debug DXF 存在后才返回分组场景；最终场景读取晋级后的正式文件。
- `result`：完成时返回既有 GenerationResult（同一任务 ID、报告、预览、文件 URL）；失败包含错误和 `release_allowed=false`。

前端可每 600 ms 轮询运行中的任务。连接失败只表示连接状态，不等于生成失败，不应推进阶段或伪造百分比。

## 阶段与门禁

新任务顺序为 queued → preparing → outline → cavity → dimensions → candidate → preview → validation → promotion → complete。outline/cavity/dimensions 三个事件在实际 debug DXF 写出后即时记录为**已重建**的来源分组；没有添加睡眠或回放时长。短任务允许用户看不到中间帧。单导轨通过 scoped subprocess 环境变量传递进度文件；双导轨使用 ContextVar 上下文，不改请求间共享环境变量。

candidate 阶段继续使用原正式候选文件。尺寸定义点、几何、闭合、机台投影等原有校验通过才进入 promotion。任何失败保留实际失败阶段，不能把所有失败标为最后阶段。正式候选不可通过文件接口下载；运行中或失败任务的正式 DXF/DWG 不开放下载。报告与原发布门禁仍为 CAD 真值来源。

启动时及进度读取时发现没有当前 worker 归属的运行记录，会保留输入与原阶段，将任务标为服务重启中断，供用户重新生成。进度文件在该任务目录内以临时文件 + replace 原子写入。

## 验证

`tests/test_workbench_generation.py` 覆盖七机型 × 三种输入路径的实际圆弧半径/端点和六避空保留、砂轮侧视、各截面槽宽/厚度/开口/外形关键原生尺寸文字及尺寸视图唯一归属、参数预览来源；真正执行单导轨 subprocess 和双导轨 engine，校验唯一历史 ID、输入快照、完整阶段顺序、最终场景与实际 release 一致；并检查失败阶段、服务中断、有界排队、启动异常和候选路径限制。原 Web API、桌面 runtime 测试继续覆盖同步兼容行为。

## 工作台交互

输入、计算复核和生成结果保持同一参数栏、画布和底部动作区。任何输入编辑、新任务或历史复制立即使原计算失效；异步响应仅能更新同一输入快照和任务。连续点击及按键自动重复不能跨状态触发下一动作，运行期间保留禁用的主按钮位置。

进度连接中断与生成失败分开显示。恢复连接只读取原任务，拿到服务响应后才恢复在线状态；完成耗时由持久化事件时间计算，页面导航和断线等待不会重置或增加实际生成耗时。生成快的任务直接显示最终结果，不延长等待来播放动画。

画布按真实 DXF 等比例显示。支持截面、侧视及双导轨总装切换、拖动、滚轮和键盘缩放、适应画布。型腔细节按钮按已有圆弧点范围放大并暂时隐藏尺寸，尺寸图例可恢复显示；不重算几何。正式文件操作仅在任务通过且 release_allowed 为真时显示。
