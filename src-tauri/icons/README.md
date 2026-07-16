# Application icon

The committed PNG/ICO/ICNS files are deterministic derivatives of
`frontend/public/favicon.svg`. Regenerate them with:

```bash
cd frontend
npx tauri icon public/favicon.svg -o ../src-tauri/icons
```

Replace the SVG with an approved company asset before a branded public release.
