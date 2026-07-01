# App icons

`icon.png` (1024×1024) is the **source** icon and the only one committed. The platform icon
set (`.icns`, `.ico`, and the various PNG sizes) is generated from it and is gitignored.

Regenerate the full set with:

```bash
cd desktop
npm run icons          # == tauri icon src-tauri/icons/icon.png
```

Run this once after `npm install`, and any time you change `icon.png`.
