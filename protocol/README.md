# HWLINK schema

`hwlink.fbs` is the single source for the HWLINK protocol (SRS Appendix A.5,
LNK-011/012). It is shared with the firmware, bootloader, demo application,
factory station and host tools.

Generate the checked-in Python bindings with:

```bash
python scripts/gen_protocol.py --flatc /path/to/flatc
```

The generated package is `src/hwval_studio/protocol/generated/hwlink`. The
generation script rewrites flatc's absolute nested imports to relative imports
so the package can be bundled by PyInstaller.

Schema rules: append-only within major version 1; raise the minor version on
every change; never remove or reorder fields (LNK-013). `header_crc32` was
appended to `ImageHeader` for protocol minor 1 so the host and BOOT validate
the same 256-byte header.
