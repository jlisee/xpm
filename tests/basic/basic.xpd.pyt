name: basic
version: 1.0.0
description: Basic C hello world program

# Not gonna do real build dependencies for these yet
#build-dependencies:
#  - make

files:
  md5-%(filehash)s:
    url: file://%(filepath)s

build:
  make

install:
  make install DESTDIR=%(prefix)s
