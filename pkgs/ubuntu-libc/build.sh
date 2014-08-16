#! /bin/bash

# Author: Joseph Lisee <jlisee@gmail.com>
# Copies all the Ubuntu libc files so we can bring them into our xpkg
# enviornment

dest_dir=$1

packages=(
    libc6
    libc6-dev
    libc-bin
    libc-dev-bin
)

for package in "${packages[@]}"; do
    for file in $(dpkg -L $package); do
        # Ignore the .
        if [ $file == "/." ]; then
            continue
        fi

        # Strip leading /usr
        if [[ $file == /usr* ]]; then
            dest_file=$dest_dir${file:4}
        else
            dest_file=$dest_dir$file
        fi

        # Transfer the files and open the directories
        if [ -d $file ]; then
            echo mkdir -p $file $dest_file
            mkdir -p $file $dest_file
        else
            echo cp $file $dest_file
            cp $file $dest_file
        fi
    done
done