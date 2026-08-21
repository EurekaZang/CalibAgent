# Real-Go2 DCLP source frames

These PNG files are the unprocessed source frames selected for the paired
long-exposure comparison. They are decoded at the native video dimensions
as 16-bit RGB PNGs. No crop, resizing, masking, brightness adjustment,
annotation, or foreground extraction has been applied.

- `direct_*.png`: DRL-DCLP direct velocity commands (`uncalib.mp4`).
- `gauge_*.png`: DRL-DCLP followed by GAUGE (`calib.mp4`).
- The two conditions use the same 11 requested elapsed times.
- Exact decoded timestamps and source-frame indices are in `manifest.json`.

| Order | Requested time (s) | Direct frame | GAUGE frame |
|---:|---:|---|---|
| 01 | 0.80 | `direct_01_t0p793333_f00024.png` | `gauge_01_t0p788333_f00024.png` |
| 02 | 1.64 | `direct_02_t1p626667_f00049.png` | `gauge_02_t1p655000_f00050.png` |
| 03 | 2.48 | `direct_03_t2p493333_f00075.png` | `gauge_03_t2p488333_f00075.png` |
| 04 | 3.32 | `direct_04_t3p326667_f00100.png` | `gauge_04_t3p321667_f00100.png` |
| 05 | 4.16 | `direct_05_t4p160000_f00125.png` | `gauge_05_t4p156667_f00125.png` |
| 06 | 5.00 | `direct_06_t4p995000_f00150.png` | `gauge_06_t4p990000_f00150.png` |
| 07 | 5.84 | `direct_07_t5p828333_f00175.png` | `gauge_07_t5p823333_f00175.png` |
| 08 | 6.68 | `direct_08_t6p695000_f00201.png` | `gauge_08_t6p690000_f00201.png` |
| 09 | 7.52 | `direct_09_t7p528333_f00226.png` | `gauge_09_t7p523333_f00226.png` |
| 10 | 8.36 | `direct_10_t8p361667_f00251.png` | `gauge_10_t8p358333_f00251.png` |
| 11 | 9.20 | `direct_11_t9p196667_f00276.png` | `gauge_11_t9p191667_f00276.png` |
