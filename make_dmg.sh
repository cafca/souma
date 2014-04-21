#!/bin/sh

# This script creates an OS X app bundle and puts that into a disk image ready
# for installing

rm ../Souma.dmg

# Create app bundle
echo "Creating app bundle"
python package.py py2app

# Create disk image
echo "Creating disk image"
cd ..
hdiutil create -srcfolder dist/Souma.app Souma.dmg
cd souma

# Clean up
rm -R ./dist
rm -R ./build
rm ./distribute-*
rm -R ./Souma.egg-info
rm -R ../dist
rm -R ../build
