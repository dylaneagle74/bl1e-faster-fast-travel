"""Find the native prepare action for a standard on-foot area exit."""


def single_link(node):
    linked = [entry.LinkedOp for output in node.OutputLinks if not output.bDisabled
              for entry in output.Links if entry.LinkedOp is not None]
    return linked[0] if len(linked) == 1 else None


def prepare_action(actor, current_map):
    if actor is None or actor.Class.Name != 'WillowInteractiveObject':
        return None
    definition = actor.InteractiveObjectDefinition
    if definition is None or definition._path_name().casefold() != 'gd_mapchangeobjects.default_mapchanger':
        return None

    events = [node for node in actor.GeneratedEvents if node is not None
              and node.Class.Name == 'WillowSeqEvent_CustomEvent' and node.EventName.casefold() == 'changemap']
    if len(events) != 1:
        return None

    # These exits use SetInt to select the normal arrival point before preparing the map.
    select_spawn = single_link(events[0])
    if select_spawn is None or select_spawn.Class.Name != 'SeqAct_SetInt':
        return None
    prepare = single_link(select_spawn)
    if prepare is None or prepare.Class.Name != 'WillowSeqAct_PrepareMapChangeFromDefinition':
        return None
    if not prepare.bTransitionToFakeEntry or prepare.bAllowVehicles:
        return None
    if prepare.DefaultMap.casefold() in ('', 'none', 'entry', 'fakeentry', 'loader', 'menumap', current_map):
        return None
    commit = single_link(prepare)
    if commit is None or commit.Class.Name != 'SeqAct_CommitMapChange':
        return None
    return prepare
