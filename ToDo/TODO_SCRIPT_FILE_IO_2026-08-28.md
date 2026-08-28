# Script file I/O

- [x] format
- [x] export single
- [x] export all
- [x] import single
- [x] import all
- [x] overwrite safety
- [x] atomic import
- [x] run file
- [x] decode/raw
- [x] Ctrl+C
- [x] path resolution
- [x] completion
- [x] EN/RU help
- [x] README
- [x] automated tests
- [x] manual roundtrip
- [ ] CI

## Definition of Done

- [x] `.rtus` v1 format implemented
- [x] import/export and direct execution implemented
- [x] file and stored-script overwrite safety implemented
- [x] failed bulk import leaves `scripts.ini` unchanged
- [x] relative paths use CWD
- [x] paths with spaces covered by automated tests
- [x] manual Windows export/import roundtrip performed
- [x] full pytest green (`195 passed, 7 skipped`)
- [ ] exact-head CI green
