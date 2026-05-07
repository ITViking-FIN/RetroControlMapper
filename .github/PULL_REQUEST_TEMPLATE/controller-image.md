<!-- Use this template when contributing a new controller image. -->
<!-- For other PRs, the default template applies. -->

## Controller details

- **VID:PID:** `XXXX:XXXX` (4-char hex, uppercase)
- **Manufacturer + model:** e.g. "8BitDo Ultimate 2 Wireless"
- **Connection mode:** USB / Bluetooth / 2.4GHz dongle / ?
- **Reported XInput?** yes / no
  (run `py rbcf_gui.py`, plug in, look at the device card —
   "XInput" badge means yes)

## Image source

- [ ] My own photo
- [ ] Manufacturer marketing image (link: ___)
- [ ] Wikimedia Commons (link: ___)
- [ ] Other: ___

If it's not your own photo, please confirm:
- [ ] Licence permits redistribution / modification

## What this PR adds

- [ ] `gui/img/known/<VID>_<PID>.{jpg,png}` (the cleaned image)
- [ ] Entry in `controller_catalog.yaml` (new VID:PID or updated existing)
- [ ] Optionally: raw source photo in `gui/img/contrib/` for archival

## Pipeline used

- [ ] `py rbcf.py submit-controller --vid X --pid Y --image P --silhouette` (dark-on-light)
- [ ] `py rbcf.py submit-controller ... --remove-bg` (uniform background)
- [ ] `py rbcf.py submit-controller ...` (tight crop, kept background)
- [ ] Manual cleanup with another tool — describe: ___

## Testing

- [ ] I verified the controller is detected by the GUI (`/api/devices`)
- [ ] I confirmed the image renders cleanly in the device-bar card
- [ ] No PII or other identifying details visible in the photo

## Notes for reviewers

(anything unusual about this controller — e.g. shares a VID:PID with a
different model in a different USB mode, has firmware-mode switching,
non-standard button layout, etc.)
