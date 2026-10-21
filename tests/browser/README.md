# Browser smoke test

Run `python tools/serve_browser_test.py`, open `http://127.0.0.1:8869`, and press **Run real AudioWorklet test** in a browser. The harness loads the production card and worklet, supplies a synthetic oscillator through a MediaStream, and simulates a delayed TV connection and binary acknowledgements. It never records the actual microphone, requests microphone permission, or connects to a TV.

The visible PASS report checks real worklet capture, release before connection readiness, complete binary delivery without audio in JSON, cleanup, and live Italian/English localization. It also verifies public CSS parts across a wrapper's shadow boundary, recording-state styling, and cancellation when the wrapper is removed during pending delivery. Unit tests cover the exact autonomous 15-second byte limit at 44.1 and 48 kHz without waiting for wall-clock time.

Repeat this smoke test in supported desktop browsers and real mobile Safari/Chrome before expanding the browser compatibility claim. Automated CI covers unit/HA integration tests; this interaction-based smoke test remains an explicit manual release check.
