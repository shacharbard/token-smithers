#!/usr/bin/env bash
# PreToolUse hook: Redirect Read on large images to sips resize suggestion.
# Exit 0 = allow, Exit 2 = block with suggestion.

source "$(dirname "$0")/_common.sh"

read_stdin
file_path=$(json_field "file_path")

# If no file path, allow
if [[ -z "$file_path" ]]; then
  exit 0
fi

# Get the filename (basename)
filename=$(basename "$file_path")
# Get extension (lowercase)
ext="${filename##*.}"
ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

# SVG is text-based, allow
if [[ "$ext" == "svg" ]]; then
  exit 0
fi

# Check if this is a bitmap image
case "$ext" in
  png|jpg|jpeg|gif|webp|bmp|tiff) ;;
  *) exit 0 ;;  # Not an image, allow
esac

# Screenshots always suggest resize regardless of size
case "$filename" in
  screenshot*|Screenshot*|"Screen Shot"*|"screen shot"*)
    echo "REDIRECT: This looks like a screenshot. Resize before reading to save tokens: sips --resampleWidth 512 '$file_path' --out /tmp/resized.png && Read /tmp/resized.png" >&2
    exit 2 ;;
esac

# Check file size (> 500KB = 512000 bytes)
if [[ -f "$file_path" ]]; then
  file_size=$(stat -f%z "$file_path" 2>/dev/null || stat -c%s "$file_path" 2>/dev/null || echo "0")
  if [[ "$file_size" -gt 512000 ]]; then
    echo "REDIRECT: Image is ${file_size} bytes. Resize before reading to save tokens: sips --resampleWidth 512 '$file_path' --out /tmp/resized.png && Read /tmp/resized.png" >&2
    exit 2
  fi
fi

# Small image, allow
exit 0
