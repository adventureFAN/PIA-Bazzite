# Third-party notices

## Private Internet Access CA certificate

PIA Bazzite includes `pia-ca.rsa.4096.crt` from the official
`pia-foss/manual-connections` repository.

Copyright (C) 2020 Private Internet Access, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Python, Qt/PySide, and bundled Python packages

The AppImage bundles CPython, Qt/PySide6 and the Python runtime dependency tree
used by PIA Bazzite. During every AppImage build, PIA Bazzite generates
`usr/share/doc/pia-bazzite/third-party-python/COMPONENTS.txt` from the exact
installed build environment and copies license, COPYING, NOTICE and AUTHORS
files when the installed distribution supplies them. Per-component package
metadata is stored beside those files.

PySide6-Essentials package metadata declares the open-source alternatives
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. Because wheel metadata does
not consistently expose the corresponding open-source license text files, the
AppImage also ships pinned copies of the canonical GNU LGPLv3, GPLv3 and GPLv2
texts under `third-party-python/PySide6-Qt/`. This avoids making release
compliance depend on a wheel-layout detail.

This generated and bundled material is provided to make the contents of the
binary package inspectable. The authoritative license terms remain those
published and shipped by each upstream project.
