# FFmpeg support (patch, not yet submitted)

`0001-avcodec-avformat-add-RV565-decoder-encoder-demuxer-a.patch` adds to
FFmpeg:

- `rv565` decoder: zlib inflate to `rgb565be`, rejecting frames that do not
  inflate to exactly width × height pixels.
- `rv565` encoder: one zlib stream per frame (`-compression_level 0-9`).
- `rv565` demuxer: probe on the signature, O(1) seeking through an index of
  frame records.
- `rv565` muxer: writes the header and patches the frame count at the end
  (needs seekable output).
- A FATE round-trip test (`fate-lavf-rv565`), docs, Changelog and version bumps.

It applies to FFmpeg master as of 2026-10-27 (e2740a3) and has **not been
built yet**.

## Build and test

```bash
git clone https://github.com/FFmpeg/FFmpeg.git && cd FFmpeg
git am /path/to/rv565/contrib/ffmpeg/0001-*.patch
./configure --enable-zlib --disable-doc
make -j"$(nproc)"

# The patch adds the FATE test but not its reference file; generate it once:
make fate-lavf-rv565 GEN=1
git add tests/ref/lavf/rv565 && git commit --amend --no-edit

# Round trip against the library's test vector and a real clip
./ffprobe -hide_banner /path/to/rv565/tests/data/testpattern.rv565
./ffmpeg -i /path/to/rv565/tests/data/testpattern.rv565 -f framemd5 -
./ffmpeg -i input.mp4 -vf scale=180:135 -r 24 -t 10 out.rv565
python3 /path/to/rv565/tools/rv565.py verify out.rv565
./ffplay out.rv565
```

## Submitting

Send when there is usage to point to (see Stage 3 in `docs/ROADMAP.md`):
`git send-email` to ffmpeg-devel@ffmpeg.org, or a pull request on
code.ffmpeg.org, whichever FFmpeg currently asks for. Offer
`tests/data/testpattern.rv565` and a short real clip for samples.ffmpeg.org.
