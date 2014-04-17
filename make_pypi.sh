#!/bin/sh

# This script uploads Souma to the Python Pachage Index (PYPI)

# Create app bundle
echo "Uploading to package index"
python setup.py sdist upload --sign

# Clean up
rm -R ./dist
rm -R ./build
rm ./distribute-*
rm -R ./Souma.egg-info
