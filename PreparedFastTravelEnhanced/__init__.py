"""Accelerate confirmed solo loads in Borderlands GOTY Enhanced."""

from dataclasses import dataclass
from time import perf_counter

from unrealsdk import find_object
from mods_base import ENGINE, BoolOption, Game, build_mod, get_pc, hook
from unrealsdk.hooks import Type, add_hook, has_hook, remove_hook
from unrealsdk.unreal import WeakPointer

from . import first_load
from . import area_exit
from .asset_cache import recent_assets


TRAVEL_TIMEOUT = 30.0
PREPARE_TIMEOUT = 0.5
PREPARE_ACTION_CLASS = 'WillowSeqAct_PrepareMapChangeFromDefinition'
PREPARE_ACTION_PATH = f'Loader.TheWorld:PersistentLevel.Main_Sequence.{PREPARE_ACTION_CLASS}_1'
SELECT = 'WillowGame.FastTravelGFxHelper:ExecuteTeleport'
VIEWPORT_RENDER = 'WillowGame.WillowGameViewportClient:PostRender'
RENDER_HOOK = f'{__name__}:prioritize_loading'
WORLD_LOAD_HOOK = f'{__name__}:finish_world_load'
EXIT_RESTORE_HOOK = f'{__name__}:restore_exit_action'
PREPARE_WORLD = 'Engine.WorldInfo:PrepareMapChange'
TRANSITION_MAPS = ('loader', 'fakeentry')


@dataclass
class Travel:
    owner: WeakPointer
    destination: str
    expires: float
    prepare_action: WeakPointer | None = None
    restore_at: float = 0.0
    last_queue: tuple[str, ...] = ()
    requested_holding: bool = False


@dataclass
class WorldLoad:
    destination: str
    expires: float
    requested_block: bool = False


@dataclass
class AreaExit:
    prepare_action: WeakPointer | None
    restore_at: float


selection_depth = 0
travel = None
world_load = None
pending_exit = None


def update_previous_area_cache(_option, enabled):
    if not enabled:
        recent_assets.clear()


cache_previous_area = BoolOption(
    'Cache previous area',
    False,
    description='Keep reusable assets from the area you leave to speed up the return trip.',
    on_change_anytime=update_previous_area_cache,
)


def local_player():
    try:
        return get_pc(possibly_loading=True)
    except IndexError:
        return None


def solo(world):
    return (world is not None and int(world.NetMode) in (0, 2)
            and world.Game is not None and world.Game.NumPlayers == 1)


def skip_intermediate_map(pending, world):
    current_map = world.GetMapName(True).casefold()
    if (current_map in ('fakeentry', pending.destination) or world.IsPreparingMapChange()
            or ENGINE.bShouldCommitPendingMapChange or int(ENGINE.LevelChangeState) != 0):
        return

    try:
        action = find_object(PREPARE_ACTION_CLASS, PREPARE_ACTION_PATH)
    except ValueError:
        return
    if action is None or not action.bTransitionToFakeEntry:
        return

    # The shared New-U sequence activates on the next tick with the game's level list.
    pending.prepare_action = WeakPointer(action)
    pending.restore_at = perf_counter() + PREPARE_TIMEOUT
    action.bTransitionToFakeEntry = False


def restore_prepare_action(pending):
    if pending.prepare_action is not None:
        action = pending.prepare_action()
        pending.prepare_action = None
        if action is not None:
            action.bTransitionToFakeEntry = True


def restore_exit_action():
    global pending_exit
    if pending_exit is not None:
        restore_prepare_action(pending_exit)
        pending_exit = None
        remove_hook(VIEWPORT_RENDER, Type.POST, EXIT_RESTORE_HOOK)


def expire_exit_action(_viewport, _args, _ret, _fn):
    if pending_exit is not None and perf_counter() >= pending_exit.restore_at:
        restore_exit_action()


@hook('WillowGame.Behavior_CheckMapChangeConditions:MapChangeEvent')
def allow_direct_exit(behavior, args, _ret, _fn):
    global pending_exit
    if (pending_exit is not None or travel is not None or world_load is not None or not first_load.installed
            or behavior.MapChangeCustomEvent.casefold() != 'changemap'):
        return
    pc = local_player()
    if pc is None or not solo(pc.WorldInfo):
        return
    world = pc.WorldInfo
    if world.IsPreparingMapChange() or ENGINE.bShouldCommitPendingMapChange or int(ENGINE.LevelChangeState) != 0:
        return
    actor = args.CustomEventInterface
    if actor is None or actor.Class.Name != 'WillowInteractiveObject' or actor.WorldInfo != world:
        return
    action = area_exit.prepare_action(actor, world.GetMapName(True).casefold())
    if action is None:
        return

    add_hook(VIEWPORT_RENDER, Type.POST, EXIT_RESTORE_HOOK, expire_exit_action)
    if has_hook(VIEWPORT_RENDER, Type.POST, EXIT_RESTORE_HOOK):
        pending_exit = AreaExit(WeakPointer(action), perf_counter() + PREPARE_TIMEOUT)
        action.bTransitionToFakeEntry = False


@hook(PREPARE_WORLD, Type.POST_UNCONDITIONAL)
def restore_exit_after_preparing(_world, _args, _ret, _fn):
    restore_exit_action()


def stop_tracking(arrived=False):
    global travel
    if travel is not None:
        restore_prepare_action(travel)
        first_load.end()
        recent_assets.finish(arrived)
        travel = None
        remove_hook(VIEWPORT_RENDER, Type.POST, RENDER_HOOK)


def prioritize_loading(_viewport, _args, _ret, _fn):
    pending = travel
    if pending is None:
        return
    now = perf_counter()
    if now >= pending.expires:
        stop_tracking()
        return
    if pending.prepare_action is not None and now >= pending.restore_at:
        restore_prepare_action(pending)

    pc = local_player()
    if pc is None or pc.WorldInfo is None:
        return
    world = pc.WorldInfo
    if pending.owner() != pc or not solo(world):
        stop_tracking()
        return

    if world.IsPreparingMapChange():
        queue = tuple(name.casefold() for name in ENGINE.LevelsToLoadForPendingMapChange)
        if not queue:
            return
        restore_prepare_action(pending)
        if queue[0] not in ('fakeentry', pending.destination):
            stop_tracking()
        elif queue != pending.last_queue:
            pending.last_queue = queue
            if not world.IsMapChangeReady():
                pc.ClientSetBlockOnAsyncLoading()
        return

    pending.last_queue = ()
    if world.GetMapName(True).casefold() == pending.destination:
        restore_prepare_action(pending)
        if pc.bIsInHolding and not pending.requested_holding:
            pending.requested_holding = True
            pc.ClientSetBlockOnAsyncLoading()
        elif pc.Pawn is not None and not pc.bIsInHolding and not pc.bCinematicMode:
            stop_tracking(arrived=True)


def stop_world_load():
    global world_load
    if world_load is not None:
        world_load = None
        first_load.end()
        remove_hook(VIEWPORT_RENDER, Type.POST, WORLD_LOAD_HOOK)


def monitor_world_load(_viewport, _args, _ret, _fn):
    pending = world_load
    if pending is None:
        return
    if perf_counter() >= pending.expires:
        stop_world_load()
        return

    pc = local_player()
    if pc is None or pc.WorldInfo is None:
        return
    world = pc.WorldInfo
    if not solo(world):
        stop_world_load()
        return

    current = world.GetMapName(True).casefold()
    if world.IsPreparingMapChange():
        queue = ENGINE.LevelsToLoadForPendingMapChange
        if len(queue) and queue[0].casefold() != pending.destination:
            stop_world_load()
        elif (len(queue) and not pending.requested_block and not world.IsMapChangeReady()
              and (current in TRANSITION_MAPS or pc.bCinematicMode)):
            pending.requested_block = True
            pc.ClientSetBlockOnAsyncLoading()
    elif current != pending.destination or (pc.Pawn is not None and not pc.bIsInHolding and not pc.bCinematicMode):
        stop_world_load()


@hook(PREPARE_WORLD)
def prepare_world_load(world, args, _ret, _fn):
    global world_load
    if travel is not None or not first_load.installed or not len(args.LevelNames):
        return
    destination = args.LevelNames[0].casefold()
    if destination in ('', 'none', 'entry', 'menumap', *TRANSITION_MAPS):
        return
    pc = local_player()
    if pc is None or world != pc.WorldInfo or not solo(world) or destination == world.GetMapName(True).casefold():
        return
    if world_load is not None and world_load.destination == destination:
        return

    # Both the initial save loader and regular exits submit their destination here.
    stop_world_load()
    if not world.IsPreparingMapChange():
        add_hook(VIEWPORT_RENDER, Type.POST, WORLD_LOAD_HOOK, monitor_world_load)
        if has_hook(VIEWPORT_RENDER, Type.POST, WORLD_LOAD_HOOK):
            recent_assets.clear()
            world_load = WorldLoad(destination, perf_counter() + TRAVEL_TIMEOUT)
            first_load.begin()


@hook(SELECT)
def start_selection(_helper, _args, _ret, _fn):
    global selection_depth
    selection_depth += 1


@hook(SELECT, Type.POST_UNCONDITIONAL)
def finish_selection(_helper, _args, _ret, _fn):
    global selection_depth
    selection_depth = max(0, selection_depth - 1)


@hook('WillowGame.WillowGameInfo:TravelToOutpost')
def track_travel(game, args, _ret, _fn):
    global travel
    stop_tracking()
    if not selection_depth:
        recent_assets.clear()
        return
    pc = local_player()
    if pc is None:
        return
    world = pc.WorldInfo
    if not solo(world) or world.Game != game:
        return

    destination = pc.GetPersistentMapFromTeleporter(args.OutpostName).casefold()
    if destination in ('', 'none'):
        return
    restore_exit_action()
    stop_world_load()
    add_hook(VIEWPORT_RENDER, Type.POST, RENDER_HOOK, prioritize_loading)
    # Some SDK builds report failure after appending a callback to an existing hook list.
    if not has_hook(VIEWPORT_RENDER, Type.POST, RENDER_HOOK):
        return
    travel = Travel(WeakPointer(pc), destination, perf_counter() + TRAVEL_TIMEOUT)
    skip_intermediate_map(travel, world)
    if travel.prepare_action is not None:
        first_load.begin()
        if cache_previous_area.value:
            recent_assets.begin(world.GetMapName(True).casefold(), destination)


@hook('Engine.PlayerController:ClientTravel')
def clear_on_client_travel(pc, _args, _ret, _fn):
    if travel is not None and travel.owner() == pc:
        stop_tracking()
    if pc == local_player():
        restore_exit_action()
        stop_world_load()
        recent_assets.clear()


def on_enable():
    first_load.install()


def on_disable():
    global selection_depth
    selection_depth = 0
    restore_exit_action()
    stop_tracking()
    stop_world_load()
    recent_assets.clear()
    first_load.remove()


mod = build_mod(supported_games=Game.BL1E, auto_enable=True)
if not mod.settings_file.exists():
    mod.enable()
