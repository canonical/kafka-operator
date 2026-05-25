.PHONY: pack clean

# The 'pack' command sequence
pack:
	@mkdir -p build
	@rsync -av --exclude build . ./build/
	@cp -ra ../common/ build/.common
	@charmcraft pack -v -p build -o .

# A cleanup command to remove the build directory
clean:
	rm -rf build
	@charmcraft clean
