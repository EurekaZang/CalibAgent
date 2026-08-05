# ICRA manuscript build

This directory contains the anonymous ICRA 2027 submission manuscript. It uses
the official IEEE Robotics and Automation Society `ieeeconf` package in US
Letter, 10-point, conference mode. The vendored `ieeeconf.cls` is kept
unchanged from the current [PaperPlaza LaTeX support package](https://ras.papercept.net/conferences/support/tex.php).

## Build and audit

From this directory, run:

```bash
make
```

The build regenerates the quantitative figures, validates their evidence
sources, compiles the LaTeX manuscript in `build/`, creates a PDF 1.4
submission artifact at `main.pdf`, embeds all fonts, downsamples raster images
to the PaperPlaza resolutions, linearizes the PDF, and runs the compliance
audit.

To rebuild only the manuscript and its submission PDF:

```bash
make main.pdf
make compliance-audit
```

Required command-line tools are `latexmk`, `pdflatex`, `bibtex`, Ghostscript,
`pdfinfo`, `pdffonts`, `pdfdetach`, and `pdftoppm`. The repository Python
environment is expected at `../.venv` when running from this directory.

The compliance checker enforces the anonymous IEEE conference class settings,
the eight-page limit, US Letter size, absence of manual template-spacing and
margin changes, PDF 1.4 compatibility, disabled security, linearization, the
PaperPlaza file-size limit, embedded fonts, and absence of Type 3 fonts. Do not
edit the class file or compress the manuscript by changing margins, font size,
line spacing, caption spacing, or float spacing; use concise prose and normal
figure sizing instead.

The conference's current submission requirements are stated on the
[ICRA 2027 call for papers](https://2027.ieee-icra.org/contribute/call-for-icra-2027-papers-now-accepting-submissions/),
and PDF requirements are documented by PaperPlaza under
[compliance](https://ras.papercept.net/conferences/support/general.php) and
[page/font/file settings](https://ras.papercept.net/conferences/support/page.php).
