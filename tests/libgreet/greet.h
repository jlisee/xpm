#ifndef GREET_H
#define GREET_H

namespace greet {

// Prints a basic creating
void say_hello();

// Says hello from it's install location (embedded at build time)
void say_install();

// Says hello from path where the install location is sub string of string
// embedded in the binary.
void say_long_install();

// Reads the greeting from a text file
void say_config_install();

// Print a binary command with the install path in it twice
void print_double_install();

}

#endif
