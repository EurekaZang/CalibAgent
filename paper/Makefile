LATEXMK ?= latexmk

.PHONY: all clean figures simulation-audit

all: simulation-audit main.pdf

figures:
	../.venv/bin/python scripts/build_review_analyses.py
	../.venv/bin/python scripts/build_paper_figures.py
	../.venv/bin/python scripts/build_simulation_scientific_figures.py
	bash /home/eureka/.codex/skills/research-figure/scripts/compile_tikz.sh figures/calibagent_pipeline.tex 300

simulation-audit: figures
	../.venv/bin/python scripts/validate_simulation_figures.py

main.pdf: main.tex references.bib ieeeconf.cls figures/calibagent_pipeline.pdf figures/calibration_evidence.pdf figures/p5_simulation_response.pdf figures/p6_simulation_shift.pdf figures/navigation_results.pdf
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error main.tex

clean:
	$(LATEXMK) -C main.tex
