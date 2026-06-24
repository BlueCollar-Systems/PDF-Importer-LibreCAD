# QA-2026-06-24 — SketchUp 2017 Make Installer Website Policy

**Date:** 2026-06-24  
**Question:** May BlueCollar host `sketchupmake-2017-2-2555-90782-en-x64.exe` on the website?  
**Local file cited:** `C:\Users\Rowdy Payton\Desktop\SketchUp 2024\sketchupmake-2017-2-2555-90782-en-x64.exe`  
**Decision:** **DO NOT redistribute the installer.**

---

## Legal / business analysis

### Sources checked on 2026-06-24

- Trimble Offering Terms: licensed software is licensed, not sold; the customer license is non-transferable/non-sublicensable, and restrictions include not providing access to, distributing, selling, or sublicensing the offering to a third party. Source: https://www.trimble.com/en/legal/offering-terms/terms
- SketchUp official product downloads page: current official download page lists recent SketchUp desktop installers, not SketchUp Make 2017. Source: https://sketchup.trimble.com/en/download/all
- Trimble Trademark Usage Guidelines: Trimble marks may be referenced appropriately, but use must not imply sponsorship/manufacture by Trimble, and website links to Trimble domains are allowed with redirect notice. Source: https://www.trimble.com/en/legal/trademark-guidelines

### 1. Copyright and redistribution

SketchUp (including **SketchUp Make 2017**) is proprietary software owned by **Trimble Inc.** The installer is a copyrighted binary, not freeware that permits third-party re-hosting. Unless BlueCollar holds a **written redistribution license** from Trimble (none on file), publishing the `.exe` on `bluecollar-systems.com` or in the GitHub website repo would be unauthorized distribution.

### 2. End-user license (EULA)

Trimble’s SketchUp EULA historically restricts copying and distribution of the software and installer. Users may install from Trimble-provided channels or copies they lawfully obtained; a fabricator’s old desktop copy does **not** grant BlueCollar the right to republish it to the public.

### 3. Trademark

“SketchUp” and related marks are Trimble trademarks. Hosting the installer could imply sponsorship or official partnership. Use **nominative references** only (“compatible with SketchUp Make 2017”) and link to Trimble/help pages — not bundled binaries.

### 4. Liability

Hosting an unsigned/old installer creates security, malware-scanning, and support liability (wrong build, locale, corrupted download). Trimble no longer markets Make 2017; BlueCollar would become the de facto support channel for install failures.

### 5. Product sunset

SketchUp Make was discontinued; Trimble does not offer official Make 2017 downloads on current product pages. That **increases** legal risk of bootleg redistribution — not a gap BlueCollar should fill with its own CDN.

---

## Recommended public messaging

| Do | Don’t |
|----|-------|
| State **“SketchUp Make 2017+ supported”** in COMPATIBILITY/README | Upload `sketchupmake-2017-*.exe` to website or releases |
| Link to [Trimble SketchUp help / product site](https://help.sketchup.com/) for current install guidance | Imply Trimble endorses BlueCollar hosting |
| Document **“use an installer you already own or obtain from Trimble”** | Email/DM installer files to customers from company storage |
| Keep RBZ download on GitHub Releases (our extension only) | Bundle SketchUp inside RBZ or portable ZIP |

---

## Alternative: COMPATIBILITY install steps (no binary)

Publish in **PDF-Importer-SketchUp** `README.md` / `COMPATIBILITY.md`:

1. User must obtain SketchUp Make 2017 or SketchUp Pro 2017+ through lawful means (existing license, IT image, or Trimble guidance).
2. Install SketchUp locally (admin on machine).
3. Download **PDF Vector Importer RBZ** from GitHub Releases only.
4. Extension Manager → Install Extension → select RBZ → restart SketchUp.
5. Optional: run bundled Poppler fetch script documented in repo.

Website `index.html` already notes Make 2017 is **not redistributed** from BlueCollar.

---

## Internal file on desktop

The cited `.exe` on the tester’s desktop may be kept for **internal QA** only. It must not be committed to git, uploaded to Cloudflare Pages, or attached to releases.

---

## Sign-off

| Role | Ruling |
|------|--------|
| QA / product | **No website hosting** of SketchUp installer |
| Engineering | Link + compatibility docs only |
| Website | One-line notice on toolkit card (done 2026-06-24) |
