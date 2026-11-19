"""Automated Litematica schematic generator for Floppy's Encoded Floor Placer.

Combines:
1. ROM encoding (adapted from ./schematicConverter/main.py) that replaces
   placeholder beacons in the template's ROM region with colored shulker boxes
   while preserving all 7 template regions, block properties, and tile entities.
2. Conveyor arm auto-tiling for X (sub arm) and Z (main arm: start-tiling-endA-slime-endB).
"""

from __future__ import annotations

import argparse
from collections import Counter
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from litemapy import BlockState, Region, Schematic, TileEntity
from nbtlib import Byte, Compound, Int, List as NbtList, String

# All 15 shulker box colors representing hexit values 1..15
DATA_PALETTE: list[str] = [
    "minecraft:white_shulker_box",
    "minecraft:orange_shulker_box",
    "minecraft:magenta_shulker_box",
    "minecraft:light_blue_shulker_box",
    "minecraft:yellow_shulker_box",
    "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box",
    "minecraft:gray_shulker_box",
    "minecraft:light_gray_shulker_box",
    "minecraft:cyan_shulker_box",
    "minecraft:purple_shulker_box",
    "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box",
    "minecraft:green_shulker_box",
    "minecraft:red_shulker_box",
]

DEFAULT_PLACEHOLDER_BLOCK = "minecraft:beacon"

# Template part filenames & default schematics directory
DEFAULT_SCHEMATICS_DIR = Path(__file__).resolve().parent / "schematics"
TEMPLATE_FILE = "floor_placer_template.litematic"
DEFAULT_TEMPLATE_PATH = DEFAULT_SCHEMATICS_DIR / TEMPLATE_FILE
MAIN_ARM_TILING_FILE = "floor_placer_main_arm_tiling.litematic"
MAIN_ARM_ENDA_FILE = "floor_placer_main_arm_endA.litematic"
MAIN_ARM_ENDB_FILE = "floor_placer_main_arm_endB.litematic"
SUB_ARM_TILING_FILE = "floor_placer_sub_arm_tiling.litematic"

# Default tiling origins in template world coordinates (derived from Conveyer arm region)
# Conveyer arm in template spans X=[14..33], Y=[0..6], Z=[55..74].
# Existing sub_arm_tiling ends at X=33 -> next tile starts at (34, 0, 55).
# Existing main_arm_tiling ends at Z=74 -> next tile starts at (19, 0, 75).
DEFAULT_SUB_ARM_START = (34, 0, 55)
DEFAULT_MAIN_ARM_START = (19, 0, 75)

# Z-axis main arm length model (always a multiple of 32: 32 * n)
Z_MULTIPLE = 32
Z_START_LENGTH = 14
Z_TILE_LENGTH = 11
Z_ENDA_LENGTH = 2
Z_ENDB_LENGTH = 1
Z_MIN_SLIME_GAP = -1
Z_MAX_SLIME_GAP = 6
Z_MAX_LAST_TILE_TRIM = 3
REDSTONE_BLOCKS_PER_Z_UNIT = 2

# X-axis sub arm length model
X_TILE_LENGTH = 11
# Base X length set to 0 by default so tiling is generous; adjust once tested in-game.
DEFAULT_X_BASE_LENGTH = 0

# Relative (x, y) of the 1-block-thick slime column connecting endA and endB
SLIME_COLUMN_LOCAL_XY = (2, 1)


@dataclass(frozen=True)
class ArmPlan:
    """Computed tiling counts and lengths for both conveyor arms."""

    target_x: int
    target_z: int
    effective_z: int
    z_multiple_n: int
    redstone_block_count: int
    n_sub_tiles: int
    actual_x: int
    n_main_tiles: int
    last_tile_trim: int
    slime_gap: int
    actual_z: int


def is_valid_z_length(z: int) -> bool:
    """Return True if z is a positive multiple of 32."""
    return z > 0 and z % Z_MULTIPLE == 0


def nearest_valid_z(raw_z: int) -> int:
    """Return the nearest positive multiple of 32 to raw_z (ties round up)."""
    if raw_z <= Z_MULTIPLE:
        return Z_MULTIPLE
    lower = (raw_z // Z_MULTIPLE) * Z_MULTIPLE
    upper = math.ceil(raw_z / Z_MULTIPLE) * Z_MULTIPLE
    if (raw_z - lower) < (upper - raw_z):
        return lower
    return upper


def compute_arm_plan(
    target_x: int,
    target_z: int,
    x_base: int = DEFAULT_X_BASE_LENGTH,
) -> ArmPlan:
    """Compute sub-arm tile count (generous) and main-arm tile/gap counts."""
    if target_x < 0 or target_z <= 0:
        raise ValueError("target_x must be >= 0 and target_z must be > 0")

    # X axis: generous tiling along +X, each tile adds 11 blocks, no end stop.
    rem_x = max(0, target_x - x_base)
    n_sub_tiles = math.ceil(rem_x / X_TILE_LENGTH) if rem_x > 0 else 0
    actual_x = x_base + n_sub_tiles * X_TILE_LENGTH

    # Z axis: must ALWAYS be an exact multiple of 32 (32 * n, n >= 1)
    # Reach = start(14) + 11*n_main - trim(0..3) + endA(2) + gap(-1..6) + endB(1)
    min_z = Z_START_LENGTH + Z_ENDA_LENGTH + Z_ENDB_LENGTH  # 17
    z_multiple_n = max(1, math.ceil(target_z / Z_MULTIPLE))
    effective_z = z_multiple_n * Z_MULTIPLE
    actual_z = effective_z

    # Solve 17 + 11*n_main + delta = effective_z with delta = gap - trim in [-4..6]
    rem_z = effective_z - min_z
    n_main_tiles, delta = divmod(rem_z, Z_TILE_LENGTH)
    if delta > Z_MAX_SLIME_GAP:
        n_main_tiles += 1
        delta -= Z_TILE_LENGTH  # now in [-4..-1]

    if delta >= 0:
        last_tile_trim = 0
        slime_gap = delta
    elif delta >= -Z_MAX_LAST_TILE_TRIM and n_main_tiles >= 1:
        last_tile_trim = -delta
        slime_gap = 0
    else:
        slime_gap = Z_MIN_SLIME_GAP
        last_tile_trim = slime_gap - delta  # e.g. delta=-4 -> gap=-1, trim=3

    redstone_block_count = REDSTONE_BLOCKS_PER_Z_UNIT * z_multiple_n

    return ArmPlan(
        target_x=target_x,
        target_z=target_z,
        effective_z=effective_z,
        z_multiple_n=z_multiple_n,
        redstone_block_count=redstone_block_count,
        n_sub_tiles=n_sub_tiles,
        actual_x=actual_x,
        n_main_tiles=n_main_tiles,
        last_tile_trim=last_tile_trim,
        slime_gap=slime_gap,
        actual_z=actual_z,
    )


def _region_world_bounds(region: Region) -> tuple[int, int, int, int, int, int]:
    """Return (min_x, max_x, min_y, max_y, min_z, max_z) in schematic world coords."""
    xs = [region.x + p[0] for p in region.allblockpos()]
    ys = [region.y + p[1] for p in region.allblockpos()]
    zs = [region.z + p[2] for p in region.allblockpos()]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _iter_world_blocks(region: Region) -> Iterable[tuple[int, int, int, BlockState]]:
    """Yield (world_x, world_y, world_z, blockstate) for all non-air blocks in region."""
    for p in region.allblockpos():
        block = region[p]
        if block.id != "minecraft:air":
            yield region.x + p[0], region.y + p[1], region.z + p[2], block


def _load_single_region(path: Path) -> Region:
    """Load a schematic that contains a single region and return that region."""
    schem = Schematic.load(str(path))
    if not schem.regions:
        raise ValueError(f"No regions found in {path}")
    return next(iter(schem.regions.values()))


def _extract_normalized_blocks(
    region: Region,
) -> list[tuple[int, int, int, BlockState]]:
    """Return non-air blocks as (rel_x, rel_y, rel_z, BlockState) relative to region's min corner."""
    min_x, _, min_y, _, min_z, _ = _region_world_bounds(region)
    return [
        (wx - min_x, wy - min_y, wz - min_z, block)
        for wx, wy, wz, block in _iter_world_blocks(region)
    ]


def _build_tight_region(
    blocks_by_pos: dict[tuple[int, int, int], BlockState],
) -> Region:
    """Create a Region with the exact minimal bounding box containing blocks_by_pos."""
    xs = [pos[0] for pos in blocks_by_pos]
    ys = [pos[1] for pos in blocks_by_pos]
    zs = [pos[2] for pos in blocks_by_pos]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)

    region = Region(
        min_x,
        min_y,
        min_z,
        max_x - min_x + 1,
        max_y - min_y + 1,
        max_z - min_z + 1,
    )
    for (wx, wy, wz), block in blocks_by_pos.items():
        region[wx - min_x, wy - min_y, wz - min_z] = block
    return region


def _stamp_blocks(
    blocks_by_pos: dict[tuple[int, int, int], BlockState],
    rel_blocks: list[tuple[int, int, int, BlockState]],
    origin_xyz: tuple[int, int, int],
) -> None:
    """Stamp pre-normalized non-air blocks at origin_xyz."""
    ox, oy, oz = origin_xyz
    for rx, ry, rz, block in rel_blocks:
        blocks_by_pos[(ox + rx, oy + ry, oz + rz)] = block


def update_redstone_block_dropper(
    template_schem: Schematic,
    redstone_count: int,
) -> tuple[str, tuple[int, int, int]]:
    """Set the redstone_block item count in the template's counter dropper to 2*n."""
    if redstone_count <= 0 or redstone_count > 9 * 64:
        raise ValueError(
            f"redstone_count ({redstone_count}) must be between 1 and {9 * 64} (dropper capacity)"
        )

    for rname, region in template_schem.regions.items():
        for te in region.tile_entities:
            if str(te.data.get("id", "")) != "minecraft:dropper":
                continue
            items = te.data.get("Items", [])
            if any(str(it.get("id", "")) == "minecraft:redstone_block" for it in items):
                new_items = []
                remaining = redstone_count
                slot = 0
                while remaining > 0:
                    stack = min(64, remaining)
                    new_items.append(
                        Compound(
                            {
                                "Slot": Byte(slot),
                                "id": String("minecraft:redstone_block"),
                                "count": Int(stack),
                            }
                        )
                    )
                    remaining -= stack
                    slot += 1
                te.data["Items"] = NbtList[Compound](new_items)
                wx = region.x + te.position[0]
                wy = region.y + te.position[1]
                wz = region.z + te.position[2]
                return rname, (wx, wy, wz)

    raise KeyError("Could not find a dropper containing 'minecraft:redstone_block' in template")


def _stamp_trimmed_main_tile(
    blocks_by_pos: dict[tuple[int, int, int], BlockState],
    rel_blocks: list[tuple[int, int, int, BlockState]],
    origin_xyz: tuple[int, int, int],
    trim: int,
) -> None:
    """Stamp main_arm_tiling at origin_xyz, shortening its z=2..3 slime rod by trim (0..3)."""
    if trim == 0:
        _stamp_blocks(blocks_by_pos, rel_blocks, origin_xyz)
        return

    ox, oy, oz = origin_xyz
    for rx, ry, rz, block in rel_blocks:
        if rz <= 1:
            tz = oz + rz
        elif rz in (2, 3):
            if rz > 3 - trim:
                continue
            tz = oz + rz
        else:
            tz = oz + rz - trim
        blocks_by_pos[(ox + rx, oy + ry, tz)] = block


def apply_conveyor_tiling(
    template_schem: Schematic,
    parts_dir: Path,
    plan: ArmPlan,
    sub_arm_start: tuple[int, int, int] = DEFAULT_SUB_ARM_START,
    main_arm_start: tuple[int, int, int] = DEFAULT_MAIN_ARM_START,
) -> None:
    """Add tight 'Conveyer sub arm' and 'Conveyer main arm' regions for tiled arms."""
    if "Conveyer arm" not in template_schem.regions:
        raise KeyError("Region 'Conveyer arm' not found in template schematic")

    # Tighten 'Conveyer arm' to non-air bounds (template has an empty air column at X=34)
    old_arm = template_schem.regions["Conveyer arm"]
    template_schem.regions["Conveyer arm"] = _build_tight_region(
        {(wx, wy, wz): block for wx, wy, wz, block in _iter_world_blocks(old_arm)}
    )

    # 1. Sub arm (+X strip) in its own tight region to avoid a huge X*Z air bounding box
    if plan.n_sub_tiles > 0:
        sub_blocks = _extract_normalized_blocks(
            _load_single_region(parts_dir / SUB_ARM_TILING_FILE)
        )
        sub_by_pos: dict[tuple[int, int, int], BlockState] = {}
        sx, sy, sz = sub_arm_start
        for i in range(plan.n_sub_tiles):
            _stamp_blocks(sub_by_pos, sub_blocks, (sx + i * X_TILE_LENGTH, sy, sz))
        template_schem.regions["Conveyer sub arm"] = _build_tight_region(sub_by_pos)

    # 2. Main arm (+Z strip) in its own tight region
    main_blocks = _extract_normalized_blocks(
        _load_single_region(parts_dir / MAIN_ARM_TILING_FILE)
    )
    end_a_blocks = _extract_normalized_blocks(
        _load_single_region(parts_dir / MAIN_ARM_ENDA_FILE)
    )
    end_b_blocks = _extract_normalized_blocks(
        _load_single_region(parts_dir / MAIN_ARM_ENDB_FILE)
    )

    main_by_pos: dict[tuple[int, int, int], BlockState] = {}
    mx, my, mz = main_arm_start
    for i in range(plan.n_main_tiles):
        trim = plan.last_tile_trim if i == plan.n_main_tiles - 1 else 0
        _stamp_trimmed_main_tile(
            main_by_pos,
            main_blocks,
            (mx, my, mz + i * Z_TILE_LENGTH),
            trim=trim,
        )

    # 3. Place endA -> slime column (-1..6) -> endB at the Z end of main arm
    z_end = mz + plan.n_main_tiles * Z_TILE_LENGTH - plan.last_tile_trim
    _stamp_blocks(main_by_pos, end_a_blocks, (mx, my, z_end))

    if plan.slime_gap > 0:
        slime_x = mx + SLIME_COLUMN_LOCAL_XY[0]
        slime_y = my + SLIME_COLUMN_LOCAL_XY[1]
        slime_block = BlockState("minecraft:slime_block")
        for dz in range(plan.slime_gap):
            main_by_pos[(slime_x, slime_y, z_end + Z_ENDA_LENGTH + dz)] = slime_block

    # endA is 2 blocks long in Z; if slime_gap == -1, endB overlaps 1 block to share the slime block
    _stamp_blocks(
        main_by_pos,
        end_b_blocks,
        (mx, my, z_end + Z_ENDA_LENGTH + plan.slime_gap),
    )

    template_schem.regions["Conveyer main arm"] = _build_tight_region(main_by_pos)


def _extract_pattern_grid(pattern_path: Path) -> list[list[list[str]]]:
    """Read a pattern schematic into a 3D list[x][y][z] of block IDs."""
    pat_schem = Schematic.load(str(pattern_path))
    pat_region = next(iter(pat_schem.regions.values()))
    min_x, max_x, min_y, max_y, min_z, max_z = _region_world_bounds(pat_region)
    w = max_x - min_x + 1
    h = max_y - min_y + 1
    l = max_z - min_z + 1

    grid = [[["" for _ in range(l)] for _ in range(h)] for _ in range(w)]
    for p in pat_region.allblockpos():
        wx = pat_region.x + p[0] - min_x
        wy = pat_region.y + p[1] - min_y
        wz = pat_region.z + p[2] - min_z
        grid[wx][wy][wz] = pat_region[p].id
    return grid


def _find_rom_beacons(
    rom_region: Region,
    placeholder_block: str = DEFAULT_PLACEHOLDER_BLOCK,
) -> tuple[list[int], list[int], list[int], dict[tuple[int, int, int], tuple[int, int, int]]]:
    """Locate placeholder beacons in ROM region and return sorted world axes + local coord map."""
    coord_map: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    xs_set, ys_set, zs_set = set(), set(), set()

    for p in rom_region.allblockpos():
        if rom_region[p].id == placeholder_block:
            wx = rom_region.x + p[0]
            wy = rom_region.y + p[1]
            wz = rom_region.z + p[2]
            coord_map[(wx, wy, wz)] = p
            xs_set.add(wx)
            ys_set.add(wy)
            zs_set.add(wz)

    if not coord_map:
        raise ValueError(f"No {placeholder_block!r} blocks found in ROM region")

    return sorted(xs_set), sorted(ys_set), sorted(zs_set), coord_map


def _water_bottle_count_for_signal(signal_strength: int) -> int:
    """Return the minimum number of non-stackable water bottles for comparator signal 1..15."""
    if not 1 <= signal_strength <= 15:
        raise ValueError(f"Signal strength must be 1..15, got {signal_strength}")
    if signal_strength == 1:
        return 1
    return math.ceil((signal_strength - 1) * 27 / 14)


def _make_shulker_tile_entity(nx: int, ny: int, nz: int, signal_strength: int) -> TileEntity:
    """Create a shulker box TileEntity filled from slot 0 with water bottles for signal 1..15."""
    bottle_count = _water_bottle_count_for_signal(signal_strength)
    items = NbtList[Compound](
        [
            Compound(
                {
                    "Slot": Byte(slot),
                    "id": String("minecraft:potion"),
                    "count": Int(1),
                    "components": Compound(
                        {
                            "minecraft:potion_contents": Compound(
                                {"potion": String("minecraft:water")}
                            )
                        }
                    ),
                }
            )
            for slot in range(bottle_count)
        ]
    )
    return TileEntity(
        Compound(
            {
                "id": String("minecraft:shulker_box"),
                "x": Int(nx),
                "y": Int(ny),
                "z": Int(nz),
                "Items": items,
            }
        )
    )


# Storage chest & indicator coordinates in 'Storage' region
# Signal strength 1..15 maps to world Z = 27 down to 13 (wz = 28 - signal_strength).
STORAGE_CHEST_XS = (2, 3)
STORAGE_CHEST_Y = 11
STORAGE_INDICATOR_X = 4
STORAGE_INDICATOR_Y = 11
STORAGE_Z_BASE = 28


def _make_filled_chest_tile_entity(
    nx: int,
    ny: int,
    nz: int,
    item_id: str,
    stack_size: int = 64,
) -> TileEntity:
    """Create a chest TileEntity filled across all 27 slots with item_id."""
    items = NbtList[Compound](
        [
            Compound(
                {
                    "Slot": Byte(slot),
                    "id": String(item_id),
                    "count": Int(stack_size),
                }
            )
            for slot in range(27)
        ]
    )
    return TileEntity(
        Compound(
            {
                "id": String("minecraft:chest"),
                "x": Int(nx),
                "y": Int(ny),
                "z": Int(nz),
                "Items": items,
            }
        )
    )


def populate_storage_chests(
    template_schem: Schematic,
    layer_palette: list[str],
) -> None:
    """Fill Storage double chests and place indicator blocks above observers for layer_palette."""
    if "Storage" not in template_schem.regions:
        raise KeyError("Region 'Storage' not found in template schematic")

    storage = template_schem.regions["Storage"]
    st_min_x, _, st_min_y, _, st_min_z, _ = _region_world_bounds(storage)
    te_by_pos: dict[tuple[int, int, int], TileEntity] = {
        te.position: te for te in storage.tile_entities
    }

    for idx, bid in enumerate(layer_palette):
        signal_strength = idx + 1
        wz = STORAGE_Z_BASE - signal_strength

        for wx in STORAGE_CHEST_XS:
            nx = wx - st_min_x
            ny = STORAGE_CHEST_Y - st_min_y
            nz = wz - st_min_z
            te_by_pos[(nx, ny, nz)] = _make_filled_chest_tile_entity(nx, ny, nz, bid)

        ind_lx = STORAGE_INDICATOR_X - storage.x
        ind_ly = STORAGE_INDICATOR_Y - storage.y
        ind_lz = wz - storage.z
        storage[ind_lx, ind_ly, ind_lz] = BlockState(bid)

    storage.tile_entities[:] = list(te_by_pos.values())


def encode_pattern_into_rom(
    template_schem: Schematic,
    pattern_path: Path,
    placeholder_block: str = DEFAULT_PLACEHOLDER_BLOCK,
    include_palette_region: bool = True,
) -> list[list[str]]:
    """Encode pattern_path into template_schem's 'ROM' region, returning per-layer palettes."""
    if "ROM" not in template_schem.regions:
        raise KeyError("Region 'ROM' not found in template schematic")

    rom_region = template_schem.regions["ROM"]
    xs, ys, zs, coord_map = _find_rom_beacons(rom_region, placeholder_block)
    pattern = _extract_pattern_grid(pattern_path)

    pw, ph, pl = len(pattern), len(pattern[0]), len(pattern[0][0])
    rw, rh, rl = len(xs), len(ys), len(zs)

    if ph != rh:
        raise ValueError(f"Pattern height ({ph}) does not match ROM layers ({rh})")

    # Match schematicConverter axis orientation: swap x/z if needed to fit ROM dimensions
    transpose_xz = False
    if (pw > rw or pl > rl) and (pl <= rw and pw <= rl):
        transpose_xz = True
        pw, pl = pl, pw
    elif pw != rw or pl != rl:
        if pw <= rw and pl <= rl:
            pass
        elif pl <= rw and pw <= rl:
            transpose_xz = True
            pw, pl = pl, pw
        else:
            raise ValueError(
                f"Pattern size ({pw}x{ph}x{pl}) exceeds ROM capacity ({rw}x{rh}x{rl})"
            )

    rom_min_x, _, rom_min_y, _, rom_min_z, _ = _region_world_bounds(rom_region)
    te_by_pos: dict[tuple[int, int, int], TileEntity] = {
        te.position: te for te in rom_region.tile_entities
    }

    palettes: list[list[str]] = []
    for y in range(ph):
        counts: Counter[str] = Counter()
        first_seen: dict[str, int] = {}
        for x in range(pw):
            for z in range(pl):
                bid = pattern[z][y][x] if transpose_xz else pattern[x][y][z]
                counts[bid] += 1
                if bid not in first_seen:
                    first_seen[bid] = len(first_seen)

        # Most frequently used blocks map to lower signal strengths (1 -> 15)
        layer_palette = sorted(
            counts.keys(),
            key=lambda bid: (-counts[bid], first_seen[bid]),
        )

        if len(layer_palette) > len(DATA_PALETTE):
            raise ValueError(
                f"Too many block types on layer {y}: {len(layer_palette)} (max {len(DATA_PALETTE)})"
            )
        palettes.append(layer_palette)

        for x in range(pw):
            for z in range(pl):
                bid = pattern[z][y][x] if transpose_xz else pattern[x][y][z]
                color_idx = layer_palette.index(bid)
                shulker_id = DATA_PALETTE[color_idx]
                wx, wy, wz = xs[x], ys[y], zs[z]
                local_pos = coord_map.get((wx, wy, wz))
                if local_pos is None:
                    raise KeyError(f"Missing ROM beacon at ({wx}, {wy}, {wz})")
                rom_region[local_pos] = BlockState(shulker_id)

                nx = wx - rom_min_x
                ny = wy - rom_min_y
                nz = wz - rom_min_z
                te_by_pos[(nx, ny, nz)] = _make_shulker_tile_entity(
                    nx, ny, nz, signal_strength=color_idx + 1
                )

        if include_palette_region:
            palette_region = Region(0, ys[y], -3 - y * 2, len(layer_palette), 1, 2)
            for idx, bid in enumerate(layer_palette):
                palette_region[idx, 0, 0] = BlockState(bid)
                palette_region[idx, 0, 1] = BlockState(DATA_PALETTE[idx])
                palette_region.tile_entities.append(
                    _make_shulker_tile_entity(idx, 0, 1, signal_strength=idx + 1)
                )
            template_schem.regions[f"palette for layer {y}"] = palette_region

    rom_region.tile_entities[:] = list(te_by_pos.values())
    return palettes


def generate_floor_placer(
    target_x: int,
    target_z: int,
    output_path: Path,
    pattern_path: Path | None = None,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    parts_dir: Path = DEFAULT_SCHEMATICS_DIR,
    sub_arm_start: tuple[int, int, int] = DEFAULT_SUB_ARM_START,
    main_arm_start: tuple[int, int, int] = DEFAULT_MAIN_ARM_START,
    x_base: int = DEFAULT_X_BASE_LENGTH,
    placeholder_block: str = DEFAULT_PLACEHOLDER_BLOCK,
    include_palette_region: bool = True,
) -> tuple[ArmPlan, list[list[str]] | None]:
    """Generate a complete floor placer litematic with tiled arms and optional ROM pattern."""
    schem = Schematic.load(str(template_path))
    plan = compute_arm_plan(target_x=target_x, target_z=target_z, x_base=x_base)

    apply_conveyor_tiling(
        template_schem=schem,
        parts_dir=parts_dir,
        plan=plan,
        sub_arm_start=sub_arm_start,
        main_arm_start=main_arm_start,
    )
    update_redstone_block_dropper(schem, plan.redstone_block_count)

    palettes = None
    if pattern_path is not None:
        palettes = encode_pattern_into_rom(
            template_schem=schem,
            pattern_path=pattern_path,
            placeholder_block=placeholder_block,
            include_palette_region=include_palette_region,
        )
        if palettes:
            populate_storage_chests(schem, palettes[0])

    schem.save(str(output_path))
    return plan, palettes


def _parse_xyz(raw: str) -> tuple[int, int, int]:
    parts = [int(p.strip()) for p in raw.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"Expected 'x,y,z', got {raw!r}")
    return parts[0], parts[1], parts[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Floppy's Encoded Floor Placer litematic with ROM encoding and arm tiling."
    )
    parser.add_argument("-x", "--x-length", type=int, required=True, help="Target X length (sub arm)")
    parser.add_argument("-z", "--z-length", type=int, required=True, help="Target Z length (main arm)")
    parser.add_argument("-p", "--pattern", type=Path, default=None, help="Optional pattern .litematic to encode into ROM")
    parser.add_argument("-o", "--output", type=Path, default=Path("floor_placer_generated.litematic"), help="Output .litematic path")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH, help="Template .litematic path")
    parser.add_argument("--parts-dir", type=Path, default=DEFAULT_SCHEMATICS_DIR, help="Directory containing arm part .litematic files")
    parser.add_argument("--sub-start", type=_parse_xyz, default=DEFAULT_SUB_ARM_START, help="Sub arm tiling start x,y,z")
    parser.add_argument("--main-start", type=_parse_xyz, default=DEFAULT_MAIN_ARM_START, help="Main arm tiling start x,y,z")
    parser.add_argument("--x-base", type=int, default=DEFAULT_X_BASE_LENGTH, help="Base X length before sub_arm_tiling")
    parser.add_argument("--placeholder", default=DEFAULT_PLACEHOLDER_BLOCK, help="Placeholder block ID in ROM")
    parser.add_argument("--no-palette-region", action="store_true", help="Do not add palette helper regions")

    args = parser.parse_args()
    plan, palettes = generate_floor_placer(
        target_x=args.x_length,
        target_z=args.z_length,
        output_path=args.output,
        pattern_path=args.pattern,
        template_path=args.template,
        parts_dir=args.parts_dir,
        sub_arm_start=args.sub_start,
        main_arm_start=args.main_start,
        x_base=args.x_base,
        placeholder_block=args.placeholder,
        include_palette_region=not args.no_palette_region,
    )

    print(f"Saved: {args.output}")
    if plan.effective_z != plan.target_z:
        print(
            f"Note: Z length {plan.target_z} rounded up to multiple of 32 -> {plan.effective_z} (n={plan.z_multiple_n})"
        )
    print(
        f"Sub arm (X): target={plan.target_x} -> {plan.n_sub_tiles} tiles (+{plan.n_sub_tiles * X_TILE_LENGTH}), "
        f"configured reach={plan.actual_x} (start={args.sub_start})"
    )
    print(
        f"Main arm (Z): target={plan.effective_z} (32*{plan.z_multiple_n}) -> "
        f"{plan.n_main_tiles} tiles (last_trim={plan.last_tile_trim}) + slime_gap={plan.slime_gap}, "
        f"actual Z={plan.actual_z} (start={args.main_start})"
    )
    print(
        f"Dropper redstone_block count: {plan.redstone_block_count} (2 * {plan.z_multiple_n})"
    )
    if palettes is not None:
        for layer_idx, layer_pal in enumerate(palettes):
            print(f"ROM layer {layer_idx} palette ({len(layer_pal)} blocks):")
            for idx, bid in enumerate(layer_pal):
                print(f"  {bid} -> {DATA_PALETTE[idx]}")


if __name__ == "__main__":
    main()
