# Media Organizer

Organizes photos and videos into a new folder **next to** the input folder, by
capture date, without ever moving, renaming or deleting an original file.

```bash
pip install .
media-organizer "./My Photos"
```

## 🚀 Usage

Media Organizer needs no mode flag: every run scans the input folder, writes the
organized files into `./My Photos_output/` and prints a report.

```bash
python main.py "./My Photos"
```

Example output:

```text
Scanning: ./My Photos

Found 1,247 photos and 12 videos.

Created files:

IMG_4821.jpg
  -> My Photos_output/2024/2024_07/20240714_163218.jpg

IMG_4822.jpg
  -> My Photos_output/2024/2024_07/20240714_170421_02.jpg

VID_0001.mp4
  -> My Photos_output/2024/2024_07/20240714_183000.mp4

vacation/DSC_1093.jpg
  -> My Photos_output/2023/2023_08/20230821_104532.jpg

Location tags:

IMG_4821.jpg
  + Berlin
  + Germany

Wrote 1,259 of 1,259 file(s) to My Photos_output.
No original file was moved, renamed or deleted.
Summary written to My Photos_output/summary.txt.
```

**The output folder is created beside the input folder, never inside it**, so the
input folder keeps exactly the files it had. Originals are copied, not touched.

For example:

```text
My Photos/
├── IMG_4821.jpg
├── IMG_4822.jpg
├── VID_0001.mp4
└── vacation/
    └── DSC_1093.jpg
```

After running:

```bash
python main.py "./My Photos"
```

the input folder is untouched and the result sits side by side with it:

```text
My Photos/                        My Photos_output/
├── IMG_4821.jpg                  ├── 2023/
├── IMG_4822.jpg                  │   └── 2023_08/
├── VID_0001.mp4                  │       └── 20230821_104532.jpg
└── vacation/                     ├── 2024/
    └── DSC_1093.jpg              │   └── 2024_07/
                                  │       ├── 20240714_163218.jpg
                                  │       ├── 20240714_170421_02.jpg
                                  │       └── 20240714_183000.mp4
                                  └── summary.txt
```

Because the results live outside the input folder, re-running the same command
never organizes its own output.

### Rules

1. The input folder is never modified: nothing is moved, renamed or deleted.
2. The organized copies go to `<input>_output`, a folder next to the input.
3. A relative `-o/--output` is resolved next to the input folder, not against the
   current working directory; only an absolute path puts the output elsewhere.
4. Existing files in the output folder are never silently overwritten.
5. Required output directories are created automatically.
6. Location tags can be written to the newly created output photos.

This means the original collection always remains intact, and re-running the
same command is safe: files that already exist with identical content are left
untouched.

---

## 📂 Output Structure

The default output structure is:

```text
{input}_output/
├── summary.txt
└── {year}/
    └── {year}_{month}/
        └── {year}{month}{day}_{time}[_{##}].{extension}
```

For example:

```text
My Photos_output/
└── 2024/
    └── 2024_07/
        ├── 20240714_163218.jpg
        ├── 20240714_163219.jpg
        ├── 20240714_170421.jpg
        └── 20240714_170421_02.jpg
```

The filename format is:

```text
YYYYMMDD_HHMMSS[_{##}].extension
```

The `_{##}` counter is **optional** and always **two digits**. The first file of
a timestamp keeps the plain name; only the additional files of that same
timestamp (and extension) are numbered, starting at `_02`:

- `20240714_170421.jpg` — first file with this timestamp
- `20240714_170421_02.jpg` — second file with the same timestamp
- `20240714_170421_03.jpg` — third file, and so on

The plain name counts as number 01, which is why the first duplicate is `_02`.

Files whose plain name is already taken in the output folder by a file with
different content also receive a counter, because existing files are never
overwritten. If the existing file is byte-identical, it is reused as is.

A different extension is a different name, so a photo and a video that share a
timestamp both keep a plain name:

```text
20240714_163218.jpg
20240714_163218.mp4
```

---

## 🗓️ Where the date comes from

| Media | Date source |
| --- | --- |
| JPEG, TIFF, PNG, HEIC, … | EXIF `DateTimeOriginal`, then `DateTimeDigitized`, then `DateTime`, then the file timestamp |
| MP4, MOV, M4V, 3GP, MTS, … | the creation time in the `moov/mvhd` box, then the file timestamp |
| MKV, AVI, WebM, … | the file timestamp (no external probe is used) |
| Any file without a usable date | the file timestamp |

Videos get no location tags, because their GPS data is not stored in a form this
tool can read without an external tool such as `ffprobe`.

---

## 📝 Summary File

Every run writes `{input}_output/summary.txt` (configurable with `--summary-name`):

```text
Media organizer summary
============================================================
input : My Photos
output: My Photos_output
run   : 2026-10-03 21:02:43

Found media
============================================================
photos           : 3
videos           : 2
total            : 5
duplicates       : 1 group(s) sharing a timestamp and extension, 3 file(s) involved
date range       : 2023-08-21 10:45:32 .. 2024-07-14 17:00:00

Result
============================================================
created          : 5
already present  : 0
renamed on clash : 0
duplicates       : 1
skipped          : 0
failed           : 0

Duplicates
============================================================
These files share a capture timestamp and extension, so only the first one of each group keeps the plain name.

20240714_163218 (.jpg) - 3 files
  a.jpg ->  2024/2024_07/20240714_163218.jpg
  b.jpg ->  2024/2024_07/20240714_163218_02.jpg
  c.jpg ->  2024/2024_07/20240714_163218_03.jpg

Created files
============================================================
IMG_4821.jpg          ->  2024/2024_07/20240714_163218.jpg
IMG_4822.jpg          ->  2024/2024_07/20240714_163218_02.jpg
VID_0001.mp4          ->  2024/2024_07/20240714_170000.mp4
vacation/DSC_1093.jpg ->  2023/2023_08/20230821_104532.jpg
```

The `Duplicates` section lists every group of files that shares one capture
timestamp (and extension), with the number each file received. It says `none`
when no two files compete for the same name. A photo and a video with the same
timestamp are not duplicates, because they get different file names.

Sections for unchanged files, skipped files, warnings and failures follow when
they are not empty.

---

## ⚙️ Options

```text
python main.py INPUT [-o OUTPUT] [--summary-name NAME] [--write-tags]
                     [--on-conflict {bump,skip}] [--geocoder MODE]
                     [--max-location-km KM] [--ext EXT] [--no-recursive]
                     [--limit N] [--max-display N] [--json] [--quiet]
```

| Option | Meaning |
| --- | --- |
| `-o`, `--output` | output folder; relative paths resolve next to the input folder, default `<input>_output` |
| `--summary-name` | name of the summary file, default `summary.txt` |
| `--write-tags` | also write the location tags into the new output photos |
| `--on-conflict` | `bump` (default) adds a `_02` suffix, `skip` leaves the file out |
| `--geocoder` | `auto` (default), `offline`, `nominatim` or `none` |
| `--max-location-km` | search radius of the offline city table in km, default `50.0` |
| `--ext` | only consider this extension; repeatable |
| `--no-recursive` | do not descend into subfolders |
| `--limit` | only process the first N files |
| `--max-display` | show at most N entries per report section |
| `--json` | print the run as JSON |
| `-q`, `--quiet` | print only a one line summary |

Exit codes: `0` success, `1` error, `2` usage error, `3` finished with failures.

---

## 🔄 How a run works

```text
                ┌──────────────┐
                │ Input folder │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │    Analyze   │  read dates, group duplicates
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │ <input>_out  │  sibling folder, copy and never overwrite
                │ summary      │
                └──────────────┘
```

At no point does the program move, rename or delete an original file.

---

## 🧪 Tests

```bash
python -m unittest discover -s tests -t .
```