"""Boss content builder.

A boss is **not** a new class — it's the combination of:

1. an `oCDtEnemyDefinition` (UID `0x176debb7`, lib `0x1414118c0`)
   carrying the "boss" bit in its `oCCustomFlagList`,
2. an `oCDtBossTimerUiControllerEntityCpnt` component
   (ctor `0x140368970`) attached to that enemy / its arena anchor,
3. an `oCDtBossTimerUiControllerEntityCpntSettings` record
   (ctor `0x140368860`, deserialize `0x140368e90`) providing the
   four picker slots (target anchor, intro cinematic, music cue,
   guaranteed reward),
4. a spawn-trigger registration: the arena's existing camp filter
   has to match the boss enemy's flag bitfield. The level-load
   pipeline at MOD_HOOKS stage 3 (`Enemies settings loading`) and
   stage 12 (`Generate enemy camps`, named-event keyed by
   `PTR_DAT_1412c09e0`) does the rest — modders don't fire a custom
   "boss spawn" event.

See `docs/_re/kinds/bosses.md` for the full layout / address table /
gaps. Until TLS injection lands and we can construct these records
at runtime, this builder stages a per-piece manifest under
`<out>/_pending_bosses/<id>/` so the next-phase apply pipeline can
materialize cooked-asset bytes.

The four piece-files mirror the four parts of the chain above and
ride the same `cloned_from: <base>` + `synthesized: {offset: value}`
audit model items.py / enemies.py use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..content import ContentDef, SchemaNotMined
from . import _common as C

# Offsets confirmed against FUN_140368860 (ctor),
# FUN_140368e90 (deserialize), FUN_140368fc0 (resolve).
# See docs/_re/kinds/bosses.md for the full table.
_BOSSTIMER_PICKER_OFFSETS: dict[str, int] = {
    # picker 1: arena anchor / target entity to attach to
    "arena_anchor": 0x0F8,
    # picker 2: intro cinematic / intro entity   # TODO: confirm
    "intro": 0x138,
    # array/scalar slot (per-phase HP cutoffs?)   # TODO: confirm
    "phases_array": 0x178,
    # picker 3: FMOD music cue                   # TODO: confirm
    "music_cue": 0x250,
    # array/scalar slot (boss-room flag list?)   # TODO: confirm
    "fight_flags": 0x290,
    # picker 4: guaranteed reward (oCDtRewardDefinition)
    # gated by version tag 0x17e9a0ae
    "reward": 0x310,
}

# Version tag the deserializer checks for the +0x310 reward picker.
# Records without this tag silently skip the reward field.
_BOSSTIMER_REWARD_VERSION_TAG = 0x17E9A0AE

# Singleton addresses (informational; mod-runtime will resolve at apply time).
_ENEMY_LIBRARY_SINGLETON = 0x1414118C0
_ENEMY_DEF_UID = 0x176DEBB7
_ENEMY_DEF_SIZE = 0x350


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Stage a boss encounter as a five-file manifest.

    Required fields:
        name          — internal id slug (used as resource-path name).
        display_name  — user-facing string; goes into the text bank as
                        `RSMM_<mod>_<id>_name`.
        base          — vanilla boss id to clone for unmined fields
                        (HP curves, animation refs, AI, etc.). Required
                        until enemy + bosstimer schemas are fully mined.
        arena         — level / map id where the encounter lives. The
                        arena's existing camp must accept the boss
                        flag bit — see `spawn.json.flag_tag` below.

    Optional:
        music_cue     — FMOD event path for boss music.
        intro_text    — intro cinematic / barks key. Tied to picker 2.
        hp            — override the cloned base's max HP.
        phases        — list of phase dicts. Each phase may carry
                          `hp_pct`   (float, 0..1, when to enter phase)
                          `barks`    (list[str], intro line ids)
                          `add_tags` (list[str], flag-list bits to
                                      flip on entering the phase)
                        Unknown phase fields are stashed under
                        `extra` so the apply pipeline can pass them
                        through to the cooked bytes once schema-mined.
        reward        — id of an `oCDtRewardDefinition` to register as
                        the guaranteed drop (picker 4 at +0x310).
                        Requires the version tag
                        `0x17e9a0ae` to be present in the cooked
                        bytes; the manifest writes this for us.
        flag_tag      — explicit flag-bit (0..63) to set on the boss
                        enemy's `oCCustomFlagList`. Defaults to the
                        bit found on the cloned base; if `base` is
                        ambiguous, this MUST be supplied.

    Returns:
        list[Path]   — every staged file under
                      `<out_dir>/_pending_bosses/<id>/`.
    """
    C.validate_id("boss", defn.id)
    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        # No `base` ⇒ no donor for HP curves, AI, animation refs,
        # mesh, etc. We could in principle synthesize from raw
        # fields, but until the full enemy + bosstimer schemas are
        # mined we can't guarantee the cooked bytes load.
        raise SchemaNotMined(
            f"boss {defn.id}: needs a 'base' (vanilla boss id) to clone "
            f"for HP curves, AI, animation refs, and the boss-flag bit. "
            f"Full synthesis blocked on enemy + boss-fight-controller "
            f"schema RE — see docs/_re/kinds/bosses.md."
        )

    name = str(defn.fields.get("name") or defn.id)
    display_name = str(defn.fields.get("display_name") or name)
    text_key_name = f"RSMM_{mod_id}_{defn.id}_name"
    arena = defn.fields.get("arena")
    music_cue = defn.fields.get("music_cue")
    intro_text = defn.fields.get("intro_text")
    hp = defn.fields.get("hp")
    phases = defn.fields.get("phases") or []
    reward = defn.fields.get("reward")
    flag_tag = defn.fields.get("flag_tag")

    if not isinstance(phases, list):
        raise ValueError(f"boss {defn.id}: 'phases' must be a list, got {type(phases).__name__}")

    out_root = out_dir / "_pending_bosses" / C.slug_id(defn.id)
    written: list[Path] = []

    # 1) Top-level boss manifest — what the UI / docs surface.
    written.append(C.write_json(out_root / "boss.json", {
        "schema": "rsmm.boss.v1",
        "kind": "boss",
        "id": defn.id,
        "mod": mod_id,
        "name": name,
        "display_name": display_name,
        "display_name_key": text_key_name,
        "base": base,
        "arena": arena,
        "music_cue": music_cue,
        "intro_text": intro_text,
        "hp": hp,
        "phases": phases,
        "reward": reward,
        "flag_tag": flag_tag,
        "schema_version": defn.schema_version,
        # Pointers into the per-piece manifests below — kept
        # explicit so the apply pipeline can be driven from
        # boss.json alone without scanning the directory.
        "pieces": {
            "enemy": "enemy.json",
            "bosstimer": "bosstimer.json",
            "reward": "reward.json",
            "spawn": "spawn.json",
        },
    }))

    # 2) oCDtEnemyDefinition clone — HP/damage scalars + the boss
    #    flag bit. Unknown fields ride the cloned-from-base donor.
    enemy_synthesized: dict[str, Any] = {}
    if hp is not None:
        # TODO: confirm — enemy max-HP offset inside oCDtEnemyDefinition;
        # awaiting enemy-schema mining.
        enemy_synthesized["max_hp"] = hp
    if flag_tag is not None:
        enemy_synthesized["flag_bit"] = int(flag_tag)
    written.append(C.write_json(out_root / "enemy.json", {
        "schema": "rsmm.enemy_clone.v1",
        "id": defn.id,
        "name": name,
        "display_name": display_name,
        "cloned_from": base,
        "library_singleton": hex(_ENEMY_LIBRARY_SINGLETON),
        "uid": hex(_ENEMY_DEF_UID),
        "record_size": hex(_ENEMY_DEF_SIZE),
        "synthesized": enemy_synthesized,
        # An empty `flag_bit` here means "inherit base's flag list
        # verbatim" — the cloned bytes already carry the boss bit.
        "flag_bit_inherited_from_base": flag_tag is None,
    }))

    # 3) oCDtBossTimerUiControllerEntityCpntSettings — the four
    #    picker slots + the version tag for the reward picker.
    bosstimer_synthesized: dict[str, Any] = {}
    if arena is not None:
        bosstimer_synthesized[hex(_BOSSTIMER_PICKER_OFFSETS["arena_anchor"])] = {
            "type": "picker",
            "target": arena,
            # TODO: confirm — meta-class for arena anchor pickers.
            "meta_class": "oCEntity",
        }
    if intro_text is not None:
        bosstimer_synthesized[hex(_BOSSTIMER_PICKER_OFFSETS["intro"])] = {
            "type": "picker",
            "target": intro_text,
            "meta_class": "oCEntity",  # TODO: confirm
        }
    if phases:
        bosstimer_synthesized[hex(_BOSSTIMER_PICKER_OFFSETS["phases_array"])] = {
            "type": "array",
            "entries": phases,
            "note": (
                "TODO: confirm encoding once "
                "oCDtBossTimerUiControllerEntityCpntSettings schema "
                "callback is mined"
            ),
        }
    if music_cue is not None:
        bosstimer_synthesized[hex(_BOSSTIMER_PICKER_OFFSETS["music_cue"])] = {
            "type": "picker",
            "target": music_cue,
            # TODO: confirm — MelodyDefinition? FMOD event?
            "meta_class": "MelodyDefinition",
        }
    if reward is not None:
        bosstimer_synthesized[hex(_BOSSTIMER_PICKER_OFFSETS["reward"])] = {
            "type": "picker",
            "target": reward,
            "meta_class": "oCDtRewardDefinition",
            "version_tag": hex(_BOSSTIMER_REWARD_VERSION_TAG),
            "note": (
                "+0x310 picker is gated by version tag 0x17e9a0ae in "
                "FUN_140368e90; cooked bytes MUST emit this tag for "
                "the picker to deserialize."
            ),
        }
    written.append(C.write_json(out_root / "bosstimer.json", {
        "schema": "rsmm.bosstimer.v1",
        "id": defn.id,
        "cloned_from": base,
        "settings_class": "oCDtBossTimerUiControllerEntityCpntSettings",
        "runtime_class": "oCDtBossTimerUiControllerEntityCpnt",
        "settings_ctor": "0x140368860",
        "settings_deserialize": "0x140368e90",
        "settings_resolve": "0x140368fc0",
        "runtime_ctor": "0x140368970",
        "runtime_dtor": "0x140368ab0",
        "runtime_vftable": "0x14147ff74",
        "picker_offsets": {k: hex(v) for k, v in _BOSSTIMER_PICKER_OFFSETS.items()},
        "reward_version_tag": hex(_BOSSTIMER_REWARD_VERSION_TAG),
        "synthesized": bosstimer_synthesized,
    }))

    # 4) Reward stub — either a clone-of-existing reward, or a
    #    pointer the apply pipeline resolves against the
    #    `oCDtRewardDefinition` library (singleton 0x141412e00).
    written.append(C.write_json(out_root / "reward.json", {
        "schema": "rsmm.reward_ref.v1",
        "id": defn.id,
        "reward_id": reward,
        # If `reward` is None, the boss inherits the cloned base's
        # reward setup — usually one or more
        # oCDtRewardEntitySelectorToSpawnEntityCpntSettings attached
        # to the boss entity. Apply pipeline must NOT clear the
        # base's reward selectors in that case.
        "inherited_from_base": reward is None,
        "library_singleton": hex(0x141412E00),
        "selector_class": "oCDtRewardEntitySelectorToSpawnEntityCpntSettings",
    }))

    # 5) Spawn trigger — there is NO explicit "fire this event"
    #    step. The boss spawns via the level-load pipeline:
    #    stage 3 (Enemies settings loading) admits the enemy if
    #    its flag bitfield matches; stage 12 (Generate enemy camps)
    #    is what actually creates the entity. We document the
    #    contract here for the apply pipeline so the arena's
    #    camp filter ends up matching.
    written.append(C.write_json(out_root / "spawn.json", {
        "schema": "rsmm.spawn.v1",
        "id": defn.id,
        "arena": arena,
        "flag_tag": flag_tag,
        "trigger_mechanism": "level_load_camp_filter",
        "named_events": {
            "fight_start": {
                "string": "BOSS_FIGHTING_START",
                "string_address": "0x140ef1758",
                "key_global": "0x1412c0430",
            },
            "fight_stop": {
                "string": "BOSS_FIGHTING_STOP",
                "string_address": "0x140ef1798",
            },
            "activated": {
                "string": "BOSS_ACTIVATED",
                "string_address": "0x140ef1860",
                "key_global": "0x1412bfcb8",
            },
            "defeated": {
                "string": "BOSS_DEFEATED",
                "string_address": "0x140ef1788",
            },
        },
        "level_load_stages": {
            "filter_stage": 3,
            "spawn_stage": 12,
            "spawn_event_key_global": "PTR_DAT_1412c09e0",
        },
        "notes": [
            # TODO: confirm — exact flag bit index for the boss tag;
            # currently inherits from the cloned base.
            "Bosses are not spawned by a direct factory call; the engine"
            " walks oCTLibrary<oCDtEnemyDefinition> at level load and"
            " the arena's camp filter selects them by flag bitfield."
            " Modders therefore do not need to fire any named event"
            " themselves.",
        ],
    }))

    # 6) Text-bank seed — EN-locale display-name override. The mod's
    #    own lang/<locale>.toml files override this at merge time.
    written.append(C.write_json(out_root / "i18n.json", {
        "schema": "rsmm.boss_i18n.v1",
        "mod": mod_id,
        "boss_id": defn.id,
        "strings": {text_key_name: display_name},
        "fallback_locale": "EN",
    }))

    return written
