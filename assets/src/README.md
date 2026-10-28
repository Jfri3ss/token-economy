# Graphics sources

The SVGs here are the sources for the PNGs in `assets/`. To re-render after an edit, serve this folder with `python3 render_server.py 8803`, open `http://localhost:8803/render.html` in a browser that has the Inter font installed, and run this in the console:

```js
await render("banner.svg", 2560, 800); await render("how-it-works.svg", 2560, 1040); await render("social-preview.svg", 1280, 640)
```

The PNGs land in `out/`. Copy them to `assets/`. `icon.png` is `icon.svg` at 512×512. The social preview must stay 1280×640 and under 1 MB for GitHub.
