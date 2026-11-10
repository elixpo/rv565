# File-type registration

Files that teach other software to recognise `.rv565` files. Each is also
being proposed upstream; the status is tracked in `docs/ROADMAP.md`.

| Directory | What | Use it locally |
| --- | --- | --- |
| `file/` | `file(1)` / libmagic signature, and the upstream patch | `file -m contrib/file/rv565.magic clip.rv565` |
| `freedesktop/` | shared-mime-info type `video/x-rv565` for Linux desktops | see the comment at the top of `rv565.xml` |
| `pronom/` | Fields for a PRONOM (UK National Archives) format record | — |
| `kaitai/` | [Kaitai Struct](https://kaitai.io) description, for parsers in many languages and the Web IDE's hex view | open `kaitai/rv565.ksy` in https://ide.kaitai.io with a clip |
| `ffmpeg/` | FFmpeg decoder, encoder, demuxer and muxer (patch, built and FATE-tested) | build steps in `ffmpeg/README.md` |

The `file(1)`, shared-mime-info and PRONOM entries use the same signature: `RV5`, version byte `6`, a frame rate of
1–30 at offset 8, and the zlib header byte `0x78` at offset 16.
