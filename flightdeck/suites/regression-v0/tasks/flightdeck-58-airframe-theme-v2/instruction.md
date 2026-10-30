flightdeck's docs theme must move to Airframe's `theme-v2` release, from Sean-Koval/agent-factory (the design source
of truth; see `AGENTS.md` and `CONTRIBUTING.md#design`).

- Vendor `docs/stylesheets/airframe.css` and `airframe-docs.css` from the `theme-v2` tag, unmodified, with
  `scripts/sync-airframe.sh`. Replace that script with agent-factory's template version, which vendors a `FILES`
  list. A vendored `airframe.css` names its release in its header comment (`Airframe theme-vN tokens`).
- flightdeck's own stylesheets (every other `docs/stylesheets/*.css`) use Airframe tokens (`var(--af-...)`) only: no
  hex, `rgb()` or `hsl()` color literals outside comments. `product.css` uses `--af-product-flightdeck`.
- Point `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md#design` at Airframe.
