import { Component } from "react";

// Keeps a rendering error on one page from blanking the whole app.
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(prev) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="banner banner-danger" role="alert">
        <strong>This page hit an error: {this.state.error.message}</strong>
        <p className="small">
          If you recently updated the code, the backend may be out of date. Rebuild and restart it
          (<code>docker compose up --build</code>), then reload.
        </p>
      </div>
    );
  }
}
