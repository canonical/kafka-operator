# Regenerate tutorial test scripts from the Markdown source files.
#
# Each tutorial page is written in Markdown. Shell commands inside ```shell
# fenced code blocks are extracted by extract_commands.py and written into
# numbered .sh scripts that the spread test suite can execute directly.
#
# Run from the project root:
#   make -f tests/tutorial/Makefile
#
# Or from this directory:
#   make

# ---------------------------------------------------------------------------
# Python interpreter
# ---------------------------------------------------------------------------
# The ?= operator sets PYTHON only if it hasn't already been set by the
# caller, so you can override it on the command line:
#   make PYTHON=python3.12 all
PYTHON   ?= python3

# ---------------------------------------------------------------------------
# Path variables
# ---------------------------------------------------------------------------
# Make remembers the name of every Makefile it reads in MAKEFILE_LIST.
# lastword picks the current file, abspath turns it into an absolute path,
# and dir strips the filename, leaving the directory (with a trailing /).
# This means THIS_DIR is always correct regardless of where you run make from.
THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# Walk two levels up from tests/tutorial/ to reach the project root.
ROOT     := $(abspath $(THIS_DIR)/../..)

# Full path to the extraction script.
EXTRACT  := $(THIS_DIR)extract_commands.py

# ---------------------------------------------------------------------------
# Script → Markdown mapping (SCRIPTS)
# ---------------------------------------------------------------------------
# Each entry is a colon-separated pair:  output.sh:source.md
# To add a new tutorial page, append another line here in the same format.
SCRIPTS := \
    $(THIS_DIR)01_environment.sh:$(ROOT)/docs/tutorial/environment.md \
    $(THIS_DIR)02_deploy.sh:$(ROOT)/docs/tutorial/deploy.md \
    $(THIS_DIR)03_client.sh:$(ROOT)/docs/tutorial/integrate-with-client-applications.md \
    $(THIS_DIR)04_passwords.sh:$(ROOT)/docs/tutorial/manage-passwords.md \
    $(THIS_DIR)05_encryption.sh:$(ROOT)/docs/tutorial/enable-encryption.md \
    $(THIS_DIR)06_kafka_connect.sh:$(ROOT)/docs/tutorial/use-kafka-connect.md \
    $(THIS_DIR)07_rebalance.sh:$(ROOT)/docs/tutorial/rebalance-partitions.md \
    $(THIS_DIR)08_cleanup.sh:$(ROOT)/docs/tutorial/cleanup.md

# Build a plain list of just the output (.sh) file paths.
# $(foreach …) iterates over SCRIPTS; $(word 1, …) after splitting on ':'
# picks the left-hand side (the script path) from each pair.
OUTPUTS := $(foreach pair,$(SCRIPTS),$(word 1,$(subst :, ,$(pair))))

# ---------------------------------------------------------------------------
# rel — convert an absolute path back to a root-relative path
# ---------------------------------------------------------------------------
# Usage: $(call rel,/absolute/path/to/file)
# Returns: path/to/file  (relative to ROOT, no leading /)
#
# Why this matters: extract_commands.py writes the source path into a comment
# at the top of each generated script. Using relative paths keeps those
# comments portable — they won't contain your personal home directory.
rel = $(patsubst $(ROOT)/%,%,$(1))

# ---------------------------------------------------------------------------
# Target: all  (default)
# ---------------------------------------------------------------------------
# .PHONY tells make that 'all' is not a real file, just a label for a group
# of actions. Without this, make might get confused if a file named 'all'
# happened to exist.
#
# 'all' depends on every output script listed in OUTPUTS. Make only
# regenerates a script when its source Markdown file (or extract_commands.py
# itself) is newer, so unchanged files are skipped automatically.
.PHONY: all
all: $(OUTPUTS)

# ---------------------------------------------------------------------------
# Per-script build rules (generated with define … endef)
# ---------------------------------------------------------------------------
# Makefile's 'define' block lets us write a reusable template.
# For each pair in SCRIPTS, $(eval $(call make_rule,…)) expands the template
# and registers a concrete rule like:
#
#   tests/tutorial/01_environment.sh: docs/tutorial/environment.md extract_commands.py
#       cd <ROOT> && python3 extract_commands.py <source.md> <output.sh>
#
# We cd to ROOT before running the script so that the paths written into the
# generated file headers are root-relative (see 'rel' above).
define make_rule
$(word 1,$(subst :, ,$(1))): $(word 2,$(subst :, ,$(1))) $(EXTRACT)
	cd $(ROOT) && $(PYTHON) $(call rel,$(EXTRACT)) $(call rel,$(word 2,$(subst :, ,$(1)))) $(call rel,$(word 1,$(subst :, ,$(1))))
endef
$(foreach pair,$(SCRIPTS),$(eval $(call make_rule,$(pair))))

# ---------------------------------------------------------------------------
# Target: extract
# ---------------------------------------------------------------------------
# Unlike 'all', this target runs extract_commands.py on every file in SCRIPTS
# unconditionally — it does not check whether the output is already up to date.
# Use this when you want to force a full regeneration regardless of timestamps,
# for example after changing extract_commands.py itself.
#
# The semicolon after each command is required: $(foreach …) expands to a
# single recipe line, so the semicolon separates consecutive shell commands.
.PHONY: extract
extract:
	$(foreach pair,$(SCRIPTS), \
	    cd $(ROOT) && $(PYTHON) $(call rel,$(EXTRACT)) $(call rel,$(word 2,$(subst :, ,$(pair)))) $(call rel,$(word 1,$(subst :, ,$(pair))));)

# ---------------------------------------------------------------------------
# Target: help
# ---------------------------------------------------------------------------
# Prints a short usage summary.
.PHONY: help
help:
	@echo "Usage: make -f tests/tutorial/Makefile [target]"
	@echo ""
	@echo "Targets:"
	@echo "  all       Regenerate scripts that are out of date (default)"
	@echo "  extract   Unconditionally regenerate all scripts"
	@echo "  test      Run the full tutorial suite (abort on first failure)"
	@echo "  test-continue  Run all stages even if earlier ones fail"
	@echo "  test-debug     Run with -debug: drop into a shell on failure"
	@echo "  help      Show this help message"
	@echo ""
	@echo "Generated scripts:"
	@$(foreach pair,$(SCRIPTS), \
	    echo "  $(word 1,$(subst :, ,$(pair)))  ←  $(word 2,$(subst :, ,$(pair)))";)

# ---------------------------------------------------------------------------
# Spread configuration
# ---------------------------------------------------------------------------
SPREAD     ?= spread
SPREAD_JOB ?= multipass:ubuntu-24.04-64:tests/tutorial/

# ---------------------------------------------------------------------------
# Target: test  (default run — abort on first failure)
# ---------------------------------------------------------------------------
.PHONY: test
test: extract
	$(SPREAD) -abend -vv $(SPREAD_JOB)

# ---------------------------------------------------------------------------
# Target: test-continue  (run all stages even if some fail)
# ---------------------------------------------------------------------------
.PHONY: test-continue
test-continue: extract
	$(SPREAD) -vv $(SPREAD_JOB)

# ---------------------------------------------------------------------------
# Target: test-debug  (abort on first failure, drop into VM shell)
# ---------------------------------------------------------------------------
.PHONY: test-debug
test-debug: extract
	$(SPREAD) -abend -vv -debug $(SPREAD_JOB)
