LATEXMK ?= latexmk
GHOSTSCRIPT ?= gs
PYTHON ?= ../.venv/bin/python
BUILD_DIR ?= build
SOURCE_DATE_EPOCH ?= 1785888000

export SOURCE_DATE_EPOCH

RAW_PDF := $(BUILD_DIR)/main.pdf
PAPER_INPUTS := main.tex references.bib ieeeconf.cls \
	figures/GAUGE.drawo.png \
	figures/calibration_evidence.pdf \
	figures/closed_loop_response.pdf \
	figures/shift_recovery_results.pdf \
	figures/navigation_results.pdf \
	figures/real_go2_navigation.pdf \
	figures/real_dclp_long_exposure.png

.PHONY: all clean figures simulation-audit compliance-audit

all: simulation-audit main.pdf compliance-audit

figures:
	$(PYTHON) scripts/build_review_analyses.py
	$(PYTHON) scripts/build_paper_figures.py
	$(PYTHON) scripts/build_simulation_scientific_figures.py
	$(PYTHON) scripts/build_real_navigation_figure.py
	$(PYTHON) scripts/build_real_dclp_long_exposure.py

simulation-audit: figures
	$(PYTHON) scripts/validate_simulation_figures.py

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(RAW_PDF): $(PAPER_INPUTS) | $(BUILD_DIR)
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -outdir=$(BUILD_DIR) main.tex

main.pdf: $(RAW_PDF) Makefile
	$(GHOSTSCRIPT) -q -dBATCH -dNOPAUSE -sDEVICE=pdfwrite \
		-dCompatibilityLevel=1.4 -dPDFSETTINGS=/prepress -dFastWebView=true \
		-dDetectDuplicateImages=true -dCompressFonts=true \
		-dSubsetFonts=true -dEmbedAllFonts=true \
		-dDownsampleColorImages=true -dColorImageDownsampleType=/Bicubic \
		-dColorImageResolution=300 \
		-dDownsampleGrayImages=true -dGrayImageDownsampleType=/Bicubic \
		-dGrayImageResolution=300 \
		-dDownsampleMonoImages=true -dMonoImageDownsampleType=/Bicubic \
		-dMonoImageResolution=600 -r600 -dAutoRotatePages=/None \
		-sOutputFile=$@ $(RAW_PDF) >$(BUILD_DIR)/ghostscript.log 2>&1 || \
		{ cat $(BUILD_DIR)/ghostscript.log >&2; exit 1; }

compliance-audit: main.pdf
	$(PYTHON) scripts/check_ieeeconf_compliance.py \
		--tex main.tex --pdf main.pdf --class ieeeconf.cls --log $(BUILD_DIR)/main.log

clean:
	$(LATEXMK) -C -outdir=$(BUILD_DIR) main.tex
	$(RM) main.pdf
