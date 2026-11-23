# Faster Fast Travel for Borderlands GOTY Enhanced

Faster Fast Travel is a Willow1 PythonSDK mod for Windows. It loads valid solo New-U destinations and standard on-foot area exits directly, and skips repeated missing-file checks during area changes and save loads. The native helper targets the 64-bit Steam Enhanced executable from build 9171464.

## Install

Install the [Willow1 PythonSDK](https://bl-sdk.github.io/willow1-mod-db/), then get `PreparedFastTravelEnhanced.sdkmod` from this repository’s Releases tab. Close the game and copy the zipped package into the Enhanced edition’s `sdk_mods` folder. The mod appears as **Faster Fast Travel** in the Mods menu.

See the [mod documentation](PreparedFastTravelEnhanced/README.md) for settings and supported transitions.

## Build from source

Install Python 3.11 or newer and put a Windows x64 MinGW-w64 GCC toolchain on `PATH`. Run this from the repository root.

```powershell
python build_sdkmod.py
```

Use `--cc` to select a different GCC executable. The script compiles the native helper and writes `dist/PreparedFastTravelEnhanced.sdkmod`.
