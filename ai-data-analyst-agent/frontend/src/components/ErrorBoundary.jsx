import { Component } from 'react';
import { ErrorState } from './ui/index.js';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // After an update, an open tab may ask for page code that no longer exists. Reload once to get the new version.
    const stale = /dynamically imported module|Importing a module script failed|Failed to fetch|ChunkLoadError/i.test(String(error?.message || error));
    try {
      if (stale && !sessionStorage.getItem('reloaded-for-update')) {
        sessionStorage.setItem('reloaded-for-update', '1');
        window.location.reload();
        return;
      }
      sessionStorage.removeItem('reloaded-for-update');
    } catch { /* storage blocked: show the message below */ }
    // Logged for developers; the user sees a friendly message only.
    console.error('UI error', error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32 }}>
          <ErrorState
            title={this.props.title || 'This part of the page failed to load'}
            message="Try again. If it keeps happening, reload the page."
            onRetry={() => window.location.reload()}
          />
        </div>
      );
    }
    return this.props.children;
  }
}
