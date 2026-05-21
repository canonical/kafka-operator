.PHONY: pack clean

# The 'pack' command sequence
pack:
	@cp -ra ../common/ .common
	@charmcraft pack -v

# A cleanup command to remove the build directory
clean:
	rm -rf .common
	@charmcraft clean
