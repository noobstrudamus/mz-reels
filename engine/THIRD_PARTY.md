# Third-party credits (engine)

## Lemo-Opuscar: "Halftone Dossier" look (`meta.look = "dossier"`, default since 2026-11-01)

- Source: https://github.com/lemomo-ai/lemo-opuscar, `styles/halftone-dossier/STYLE.md`
- Licence: MIT, Copyright (c) 2026 LemoLab (code). Demo films and stills are CC BY 4.0; none are used here.
- What we use: the style's grammar (printed cream paper, overprinted halftone dot fields, hard misregistered
  shadows, flat inks with heavy ink outlines, rough stamps, manila file folders, dot-wipe cuts, case/exhibit HUD).
  The drawing code in `reel.html` (paperURL, halftone, dossier, wipeSeek) is our own re-implementation for the
  1080x1920 reel template; no files, fonts, images or audio were copied from the repository.
- Reference checkout for future styling work: `git clone --depth 1 https://github.com/lemomo-ai/lemo-opuscar`
  (read `AGENTS.md`, `DIRECTOR.md`, `styles/<slug>/STYLE.md`). Not needed at render time.

MIT licence text of the source project:

    Copyright (c) 2026 LemoLab

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
    documentation files (the "Software"), to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
    to permit persons to whom the Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial portions
    of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
    THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
    CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
