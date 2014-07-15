#!/bin/sh

# This script creates an OS X app bundle and puts that into a disk image ready
# for installing

python package.py bdist_esky

cd dist
unzip Souma-*.zip

# Create disk image
hdiutil create -srcfolder Souma.app Souma.dmg

# Clean up
# rm -R ./dist
# rm -R ./build
# rm ./distribute-*
# rm -R ./Souma.egg-info
# rm -R ../dist
# rm -R ../build
