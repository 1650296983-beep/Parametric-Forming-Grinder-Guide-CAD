import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DrawingPrimitive, DrawingScene } from "./types";

const finite = (values: number[]) => values.every(Number.isFinite);
function Primitive({ primitive }: { primitive: DrawingPrimitive }) {
  const color = {
    outline: "#eef5fa",
    cavity: "#40ce85",
    dimensions: "#51e0e8",
    center: "#f14b53",
  }[primitive.group];
  if (primitive.kind === "polyline") {
    if (!primitive.points.length || !primitive.points.every(finite))
      return null;
    return (
      <polyline
        points={primitive.points.map((point) => point.join(",")).join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.1"
        vectorEffect="non-scaling-stroke"
        strokeDasharray={primitive.dash ? "7 4" : undefined}
      />
    );
  }
  if (
    !finite([...primitive.position, primitive.height, primitive.rotation || 0])
  )
    return null;
  return (
    <text
      x={primitive.position[0]}
      y={primitive.position[1]}
      fill={color}
      fontSize={primitive.height}
      transform={
        primitive.rotation
          ? `rotate(${primitive.rotation} ${primitive.position[0]} ${primitive.position[1]})`
          : undefined
      }
    >
      {primitive.text}
    </text>
  );
}

export function DrawingCanvas({
  scene,
  taskId,
}: {
  scene: DrawingScene | null;
  taskId?: string | null;
}) {
  const [viewId, setViewId] = useState("");
  const [camera, setCamera] = useState({ zoom: 1, x: 0, y: 0 });
  const cameraRef = useRef(camera);
  const [announcement, setAnnouncement] = useState("");
  const [showDimensions, setShowDimensions] = useState(true);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: number; x: number; y: number } | null>(null);
  const view =
    scene?.views.find((item) => item.id === viewId) ?? scene?.views[0];
  const viewKey = view?.id ?? "";
  useEffect(() => {
    const next = { zoom: 1, x: 0, y: 0 };
    cameraRef.current = next;
    setCamera(next);
    setShowDimensions(true);
  }, [viewKey, taskId]);
  const box = useMemo(() => {
    const b = view?.bounds;
    if (!b || !finite(b) || b[2] <= b[0] || b[3] <= b[1])
      return [0, 0, 100, 80];
    const padding = Math.max(b[2] - b[0], b[3] - b[1]) * 0.07;
    return [
      b[0] - padding,
      b[1] - padding,
      b[2] - b[0] + padding * 2,
      b[3] - b[1] + padding * 2,
    ];
  }, [view]);
  const visible = [
    box[0] + box[2] / 2 - box[2] / camera.zoom / 2 + camera.x,
    box[1] + box[3] / 2 - box[3] / camera.zoom / 2 + camera.y,
    box[2] / camera.zoom,
    box[3] / camera.zoom,
  ];
  const zoom = useCallback((factor: number) => {
    const previous = cameraRef.current;
    const next = {
      ...previous,
      zoom: Math.max(0.25, Math.min(12, previous.zoom * factor)),
    };
    cameraRef.current = next;
    setCamera(next);
    setAnnouncement(`缩放 ${Math.round(next.zoom * 100)}%`);
  }, []);
  const fit = () => {
    const next = { zoom: 1, x: 0, y: 0 };
    cameraRef.current = next;
    setCamera(next);
    setShowDimensions(true);
    setAnnouncement("已适应画布，显示全部尺寸");
  };
  const fitCavity = () => {
    // Fit the existing CAD points; no product dimensions are calculated here.
    const cavity =
      view?.primitives.filter(
        (primitive) =>
          primitive.group === "cavity" && primitive.kind === "polyline",
      ) ?? [];
    const curved = cavity.filter(
      (primitive) =>
        primitive.kind === "polyline" && primitive.points.length > 2,
    );
    const points = (curved.length ? curved : cavity)
      .flatMap((primitive) =>
        primitive.kind === "polyline" ? primitive.points : [],
      )
      .filter(finite);
    if (!points.length) return;
    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => point[1]);
    const left = Math.min(...xs),
      right = Math.max(...xs),
      top = Math.min(...ys),
      bottom = Math.max(...ys);
    const padding = Math.max(right - left, bottom - top, 0.01) * 0.3;
    const next = {
      zoom: Math.max(
        0.25,
        Math.min(
          12,
          box[2] / (right - left + padding * 2),
          box[3] / (bottom - top + padding * 2),
        ),
      ),
      x: (left + right - box[2]) / 2 - box[0],
      y: (top + bottom - box[3]) / 2 - box[1],
    };
    cameraRef.current = next;
    setCamera(next);
    setShowDimensions(false);
    setAnnouncement("已放大实际型腔与避空，尺寸标注已隐藏，可从图例恢复");
  };
  useEffect(() => {
    const node = svg.current;
    if (!node) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      zoom(event.deltaY < 0 ? 1.12 : 1 / 1.12);
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, [viewKey, zoom]);
  const groups = ["outline", "cavity", "dimensions", "center"] as const;
  return (
    <section className="cad-panel" aria-label="实际导轨几何预览">
      <div className="cad-toolbar">
        <div className="view-tabs" role="group" aria-label="图纸视图">
          {scene?.views.map((item) => (
            <button
              key={item.id}
              aria-pressed={view?.id === item.id}
              onClick={() => {
                setViewId(item.id);
                fit();
              }}
            >
              {item.label}
            </button>
          )) ?? <span>截面图</span>}
        </div>
        <div className="zoom-controls">
          {view?.id.startsWith("section_") && (
            <button
              aria-label="放大型腔细节"
              title="放大型腔细节"
              onClick={fitCavity}
            >
              <svg
                width="17"
                height="17"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <circle
                  cx="10"
                  cy="10"
                  r="5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                />
                <path
                  d="M10 1v5m0 8v5M1 10h5m8 0h5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                />
              </svg>
            </button>
          )}
          <button
            aria-label="缩小"
            disabled={!view}
            onClick={() => zoom(1 / 1.25)}
          >
            −
          </button>
          <output aria-label="当前缩放">
            {Math.round(camera.zoom * 100)}%
          </output>
          <button aria-label="放大" disabled={!view} onClick={() => zoom(1.25)}>
            ＋
          </button>
          <button
            className="fit-button"
            disabled={!view}
            onClick={fit}
            aria-label="适应画布"
          >
            ⛶ <span>适应画布</span>
          </button>
        </div>
      </div>
      <div className="cad-surface">
        <div className="cad-source">
          {scene
            ? {
                parametric_preview: "参数预览 · 尚未生成正式图纸",
                debug_dxf: "候选图纸 · 正在校验",
                release_dxf: "正式图纸 · 校验通过",
              }[scene.source]
            : "等待当前输入计算"}
          {taskId && <small>任务 {taskId}</small>}
        </div>
        {view ? (
          <svg
            ref={svg}
            viewBox={visible.join(" ")}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label={`${view.label}，单位毫米，可拖动平移和滚轮缩放`}
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "+" || event.key === "=") {
                event.preventDefault();
                zoom(1.25);
              } else if (event.key === "-") {
                event.preventDefault();
                zoom(1 / 1.25);
              } else if (event.key === "0") {
                event.preventDefault();
                fit();
              }
            }}
            onPointerDown={(event) => {
              if (drag.current || event.button !== 0) return;
              drag.current = {
                id: event.pointerId,
                x: event.clientX,
                y: event.clientY,
              };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              const d = drag.current;
              if (!d || d.id !== event.pointerId) return;
              const node = svg.current;
              if (!node) return;
              const matrix = node.getScreenCTM();
              if (!matrix) return;
              const inverse = matrix.inverse();
              const before = new DOMPoint(d.x, d.y).matrixTransform(inverse);
              const after = new DOMPoint(
                event.clientX,
                event.clientY,
              ).matrixTransform(inverse);
              const previous = cameraRef.current;
              const next = {
                ...previous,
                x: previous.x + before.x - after.x,
                y: previous.y + before.y - after.y,
              };
              cameraRef.current = next;
              setCamera(next);
              d.x = event.clientX;
              d.y = event.clientY;
            }}
            onPointerUp={(event) => {
              if (drag.current?.id === event.pointerId) {
                drag.current = null;
                if (event.currentTarget.hasPointerCapture(event.pointerId))
                  event.currentTarget.releasePointerCapture(event.pointerId);
              }
            }}
            onPointerCancel={(event) => {
              if (drag.current?.id === event.pointerId) {
                drag.current = null;
                if (event.currentTarget.hasPointerCapture(event.pointerId))
                  event.currentTarget.releasePointerCapture(event.pointerId);
              }
            }}
            onLostPointerCapture={() => {
              drag.current = null;
            }}
          >
            {groups.map((group) => {
              if (group === "dimensions" && !showDimensions) return null;
              const primitives = view.primitives.filter(
                (p) => p.group === group,
              );
              // Reveal already-built groups briefly; final release never waits for a replay.
              const delay =
                scene?.source === "debug_dxf"
                  ? { outline: 0, center: 0, cavity: 40, dimensions: 80 }[group]
                  : 0;
              return primitives.length ? (
                <g
                  key={`${taskId ?? "review"}-${scene?.source}-${view.id}-${group}`}
                  className={
                    scene?.source === "release_dxf"
                      ? undefined
                      : "cad-geometry-group"
                  }
                  style={
                    scene?.source === "release_dxf"
                      ? undefined
                      : { animationDelay: `${delay}ms` }
                  }
                >
                  {primitives.map((primitive) => (
                    <Primitive key={primitive.id} primitive={primitive} />
                  ))}
                </g>
              ) : null;
            })}
          </svg>
        ) : (
          <div className="cad-empty">
            <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden="true">
              <path
                d="M7 12h38v28H7zM18 12v12q0 8 8 8t8-8V12M26 5v42"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.3"
              />
            </svg>
            <h3>先确认当前规格</h3>
            <p>计算后将在这里显示真实比例的导轨型腔与避空。</p>
            <small>几何由本地 CAD 引擎生成</small>
          </div>
        )}
      </div>
      <footer className="cad-legend">
        <span>
          <i className="outline" />
          轮廓
        </span>
        <button
          className="legend-toggle"
          aria-label={showDimensions ? "隐藏尺寸标注" : "显示尺寸标注"}
          aria-pressed={showDimensions}
          onClick={() => setShowDimensions((value) => !value)}
        >
          <i className="dimensions" />
          尺寸
        </button>
        <span>
          <i className="center" />
          中心线
        </span>
        <small>拖动平移 · 滚轮缩放</small>
      </footer>
      <span className="sr-only" role="status">
        {announcement}
      </span>
    </section>
  );
}
