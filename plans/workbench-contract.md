# Backend / frontend contract

Existing synchronous generate API remains compatible. New endpoints require the existing local identity dependency.

- `POST /api/designs/validate` keeps its fields and adds `scene: DrawingScene`, `parsed` (named backend-derived finished/preform values if available), derived `relief_diameter`, `relief_radius`, `center_transition_radius`, `center_transition_count`, and `opening_max`. Never compute these process values in TypeScript.
- `POST /api/designs/jobs` body `{design: DesignInput}` returns HTTP 202 `{task_id: string}` after input validation and persistent task initialization. Inputs copied; task ID exactly the history ID. Worker runs the existing generator with its existing validation/promotion gates. One background generation worker; queued jobs report queued, never invented progress.
- `GET /api/tasks/{task_id}/progress` returns `GenerationProgress` below, including absolute-normalizable result file URLs. No frontend timer advances stages. Retry polling after 600 ms while running; connection failure is a reconnect state, never proof generation failed. Polling may be stopped by draft navigation, but must not cancel the actual task or mix results into another input snapshot.

```ts
interface DrawingScene {
  source: 'parametric_preview' | 'debug_dxf' | 'release_dxf';
  units: 'mm';
  coordinate_system: 'svg_y_down';
  views: DrawingView[];
}
interface DrawingView {
  id: string; label: string;
  bounds: [number, number, number, number]; // minX,minY,maxX,maxY; finite, nonzero
  primitives: DrawingPrimitive[];
}
type DrawingPrimitive = {
  id: string;
  group: 'outline' | 'cavity' | 'dimensions' | 'center';
  color: string;
  dash?: boolean;
} & ({kind: 'polyline'; points: [number,number][]} |
     {kind: 'text'; position: [number,number]; text: string; height: number; rotation?:number});
type GenerationStage = 'queued'|'preparing'|'outline'|'cavity'|'dimensions'|'candidate'|'preview'|'validation'|'promotion'|'complete';
interface ProgressEvent { stage: GenerationStage; status: 'running'|'completed'|'failed'; at: string; message: string; }
interface GenerationProgress {
 task_id: string;
 status: 'running'|'passed'|'failed';
 stage: GenerationStage;
 events: ProgressEvent[];
 message: string;
 error: string|null;
 scene: DrawingScene|null;
 result: GenerationResult|null;
}
```

Scenes derive from the same Python CAD writers/current DXF entities, never frontend approximations. A pre-generation scene must say parameter preview; only final successful gate may label source release_dxf. Final scene must be read from the actual promoted release. Include actual six-arc section and side views (single section or dual section1/section2/assembly) when available. Exclude debug/reference/control/formula layers. Flatten arcs accurately with ezdxf. Emit scene groups only after corresponding source geometry exists. Fast stages may be skipped visually; don't delay generation to replay them. Every progress write atomic, persisted in the task directory, bounded events. Keep file/path authorization. Actual failures retain the failing stage, don't label all failures promotion. Interrupted jobs after server restart must not remain falsely running forever. No secret/global-env cross-task state.
