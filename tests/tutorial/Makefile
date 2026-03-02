# Regenerate tutorial test scripts from the Markdown source files.
#
# Run from the project root:
#   make -f tests/tutorial/Makefile
#
# Or from this directory:
#   make

PYTHON   ?= python3
EXTRACT  := tests/tutorial/extract_commands.py

# Map: output script → source Markdown file
SCRIPTS := \
    tests/tutorial/01_environment.sh:docs/tutorial/environment.md \
    tests/tutorial/02_deploy.sh:docs/tutorial/deploy.md \
    tests/tutorial/03_client.sh:docs/tutorial/integrate-with-client-applications.md

# Derive the list of output files for use as the default target.
OUTPUTS := $(foreach pair,$(SCRIPTS),$(word 1,$(subst :, ,$(pair))))

.PHONY: all
all: $(OUTPUTS)

# Pattern-independent explicit rules for each script.
define make_rule
$(word 1,$(subst :, ,$(1))): $(word 2,$(subst :, ,$(1))) $(EXTRACT)
	$(PYTHON) $(EXTRACT) $(word 2,$(subst :, ,$(1))) $(word 1,$(subst :, ,$(1)))
endef
$(foreach pair,$(SCRIPTS),$(eval $(call make_rule,$(pair))))

.PHONY: help
help:
	@echo "Usage: make -f tests/tutorial/Makefile [target]"
	@echo ""
	@echo "Targets:"
	@echo "  all   Regenerate all tutorial test scripts (default)"
	@echo "  help  Show this help message"
	@echo ""
	@echo "Generated scripts:"
	@$(foreach pair,$(SCRIPTS), \
	    echo "  $(word 1,$(subst :, ,$(pair)))  ←  $(word 2,$(subst :, ,$(pair)))";)
