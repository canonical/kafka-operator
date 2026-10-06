#!/bin/bash

# don't retry if not in CI
if [ "x$CI" = "x" ]; then
  $@
  exit $?
fi

if [ "x$RETRIES" = "x" ]; then
  retries=3
else
  retries=$RETRIES
fi

count=0

until "$@"; do
  exit=$?
  wait=300
  ((count++))
  if [ $count -lt $retries ]; then
    echo "Attempt $count/$retries exited with code: $exit. retrying in $wait seconds..."
    sleep $wait
  else
    echo "Attempt $count/$retries exited with code: $exit. Failed!"
    exit $exit
  fi
done
