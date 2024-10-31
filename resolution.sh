#! /bin/bash

for file in /sys/class/drm/card*-*; do
    if [ $(wc -m < $file/modes) -ne 0 ]; then
        echo $file
        sed '1!d' "$file/modes"
    fi;
done