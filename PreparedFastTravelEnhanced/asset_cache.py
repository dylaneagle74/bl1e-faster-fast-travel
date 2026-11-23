"""Hold the previous area's reusable assets through the next solo trip."""

from pathlib import Path

from unrealsdk import construct_object, find_all, find_object
from unrealsdk.unreal import WeakPointer


ASSET_CLASSES = ('SoundCue', 'Material', 'MaterialInstanceConstant',
                 'ParticleSystem', 'PhysicsAsset', 'AnimSet')
MAX_ASSETS = 5000
STARTUP_REFERENCER = 'Startup.ObjectReferencer_0'


def asset_package_names(cooked):
    packages = set()
    maps = set()
    for file in cooked.rglob('*'):
        suffix = file.suffix.casefold()
        if suffix == '.upk':
            packages.add(file.stem.casefold())
        elif suffix == '.umap':
            maps.add(file.stem.casefold())
    return packages - maps


class RecentAreaAssets:
    def __init__(self, cooked):
        self.packages = asset_package_names(cooked) if cooked is not None else set()
        self.parent = WeakPointer()
        self.holder = WeakPointer()
        self.previous_map = ''
        self.previous_assets = {}
        self.departing_map = ''
        self.departing_assets = {}

    def get_holder(self):
        holder = self.holder()
        if holder is not None:
            return holder
        try:
            parent = find_object('ObjectReferencer', STARTUP_REFERENCER)
        except ValueError:
            return None
        if parent is None:
            return None
        holder = construct_object('ObjectReferencer', parent)
        parent.ReferencedObjects = [*parent.ReferencedObjects, holder]
        self.parent.replace(parent)
        self.holder.replace(holder)
        return holder

    def capture(self):
        assets = {}
        for class_name in ASSET_CLASSES:
            for asset in find_all(class_name):
                path = asset._path_name().casefold()
                package, _, name = path.partition('.')
                if (package in self.packages and name and ':' not in name
                        and not name.startswith('default__') and path not in self.previous_assets):
                    assets[path] = asset
                    if len(assets) == MAX_ASSETS:
                        return assets
        return assets

    def begin(self, source, target):
        if not self.packages:
            return
        holder = self.get_holder()
        if holder is None:
            return
        self.departing_assets = self.capture()
        self.departing_map = source
        if self.previous_map != target:
            self.previous_assets = {}
            self.previous_map = ''
        holder.ReferencedObjects = [*self.previous_assets.values(), *self.departing_assets.values()]

    def finish(self, arrived):
        if not self.departing_map:
            return
        if not arrived:
            self.clear()
            return
        holder = self.holder()
        if holder is not None:
            holder.ReferencedObjects = list(self.departing_assets.values())
            self.previous_map = self.departing_map
            self.previous_assets = self.departing_assets
        self.departing_map = ''
        self.departing_assets = {}

    def clear(self):
        holder = self.holder()
        if holder is not None:
            holder.ReferencedObjects = []
            parent = self.parent()
            if parent is not None:
                parent.ReferencedObjects = [obj for obj in parent.ReferencedObjects if obj != holder]
        self.holder.replace(None)
        self.parent.replace(None)
        self.previous_map = self.departing_map = ''
        self.previous_assets = {}
        self.departing_assets = {}


sdk_dir = next((parent for parent in Path(__file__).parents if parent.name.casefold() == 'sdk_mods'), None)
recent_assets = RecentAreaAssets(sdk_dir.parent / 'WillowGame' / 'CookedPC' if sdk_dir else None)
