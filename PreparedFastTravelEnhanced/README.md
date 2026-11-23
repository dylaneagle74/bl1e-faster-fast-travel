# Faster Fast Travel

For Borderlands GOTY Enhanced with the Willow1 PythonSDK. Put `PreparedFastTravelEnhanced.sdkmod` in the game's `sdk_mods` folder. It replaces Prepared Fast Travel and uses the same setting in the Mods menu.

In solo play, open any New-U fast travel station and choose your destination as usual. Once you confirm, Faster Fast Travel tells the engine to load the destination directly when the New-U loading sequence is available. The game builds the destination's level list and handles arrival normally. The mod also gives those loads priority in the engine.

The engine may pause rendering during the confirmed trip. Direct trips can briefly hold parts of both areas in memory.

On the supported 64-bit Steam Enhanced executable, the mod avoids retrying missing package and localization file lookups during confirmed New-U travel, area exits, and loading a save. The mod gives pending destination loads priority once the game is in a transition map or has entered cinematic mode for the change.

Standard on-foot gates with a single linked map change load the destination directly. The gate still selects the spawn point and the game loads the authored destination level list. Vehicle exits and other gate sequences use their usual transition.

Turn on **Cache previous area** in the mod menu to retain reusable audio and materials for the return trip. It defaults to off to minimize work on the first trip.

Disable Faster Fast Travel in the Mods menu to return to the normal loading behavior.
