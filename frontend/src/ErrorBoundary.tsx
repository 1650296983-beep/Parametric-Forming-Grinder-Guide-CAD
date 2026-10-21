import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI render failed", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="crash-screen">
        <span className="crash-icon" aria-hidden="true">
          <AlertTriangle size={28} />
        </span>
        <h1>界面渲染失败</h1>
        <p>本地 CAD 引擎和已生成的图纸不受影响。重新加载界面即可继续。</p>
        <pre>{this.state.error.message}</pre>
        <button
          className="button primary"
          onClick={() => window.location.reload()}
        >
          <RefreshCw size={16} aria-hidden="true" />
          重新加载界面
        </button>
      </main>
    );
  }
}
