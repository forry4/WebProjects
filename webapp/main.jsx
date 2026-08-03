import React from 'react'
import { createRoot } from 'react-dom/client'
import SpenderApp from '../games/spender/Spender.jsx'
// Pages caches the bundle ~10 min, so a tab can outlive its deploy. Watches for a
// newer build and offers a refresh. Outside React on purpose: the shell early-returns
// each game's component, so there is no single tree the banner could live in.
import { startUpdateNudge } from '../shared/update-nudge.js'
// Registers the service worker (prod hosts only) so the site is installable to a
// phone home screen and opens offline. Fire-and-forget, outside React, after load.
import { startPwa } from '../shared/pwa.js'

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (this.state.err) {
      return React.createElement('div', {
        style: { padding: 32, fontFamily: 'monospace', color: '#e05555', background: '#0f0e0c', minHeight: '100vh' }
      },
        React.createElement('h2', null, 'App Error'),
        React.createElement('pre', { style: { whiteSpace: 'pre-wrap', fontSize: 13 } },
          String(this.state.err)
        )
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')).render(
  React.createElement(React.StrictMode, null,
    React.createElement(ErrorBoundary, null,
      React.createElement(SpenderApp)
    )
  )
)

startUpdateNudge()
startPwa()
