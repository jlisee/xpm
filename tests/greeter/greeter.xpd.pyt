name: greeter
version: 1.0.0
dependencies:
 - libgreet==1.0.0  # Need to print things
 - faketools # Needed for configuration

files:
  md5-%(filehash)s:
    url: file://%(filepath)s

configure:
  ./configure --prefix=%(prefix)s

build:
  make -j%(jobs)s

install:
  make install
