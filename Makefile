PLUGIN_DIR := $(shell pwd)

.PHONY: dev test

# Launch claude with this plugin loaded locally
dev:
	claude --plugin-dir $(PLUGIN_DIR)

# Run test suite
test:
	bash tests/test-model-router.sh
