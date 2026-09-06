import { Button } from "@/components/Button";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Last line of defence. A render error in one screen should not leave the user with a
 * blank page and no way back to the board.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="main">
        <div className="error-panel" role="alert">
          <strong>This screen stopped working.</strong>
          <p className="muted">{error.message}</p>
          <div className="row">
            <Button variant="primary" onClick={() => this.setState({ error: null })}>
              Try again
            </Button>
            <Button onClick={() => window.location.assign("/app")}>Back to dashboard</Button>
          </div>
        </div>
      </div>
    );
  }
}
