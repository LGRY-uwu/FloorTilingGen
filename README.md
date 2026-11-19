# FloorTilingGen

Automated Litematica schematic generator for **Floppy's Encoded Floor Placer** (Minecraft).

It takes a base machine template and:
1. Encodes a 16×1×16 floor pattern into the machine's **ROM** (replacing placeholder beacons with shulker boxes filled with water bottles for comparator signal strengths 1–15, sorted from most-used to least-used block).
2. Populates the **Storage** double chests (27×64 items each) and places visual indicator blocks above the front observers.
3. Automatically tiles the **Sub arm (`+X`)** and **Main arm (`+Z`)** to the requested floor dimensions (with Z always snapped to a multiple of 32 and the counter dropper's redstone block count set to `2n`).

## Requirements

- Python 3.10+
- `litemapy`

```bash
pip install -r requirements.txt
```

## Usage

### GUI (Recommended)

```bash
python floor_placer_gui.py
```

1. *(Optional)* Select a 16×1×16 `.litematic` floor pattern (up to 15 block types).
2. Choose **X Length** and **Z Length** (multiples of 32; any custom Z input is snapped to the nearest multiple of 32).
3. Choose the output `.litematic` path and click **Generate Schematic**.

### CLI

```bash
python floor_placer_gen.py -x 64 -z 288 -p schematics/floor_pattern_test.litematic -o output.litematic
```

Run `python floor_placer_gen.py --help` for all options (including custom arm start offsets).

## Files

- `floor_placer_gui.py` — Tkinter GUI frontend
- `floor_placer_gen.py` — Core schematic generator & CLI
- `schematics/` — Base template, arm tiling parts, and sample pattern (`.litematic`)

## Credits

- ROM beacon-to-shulker encoding logic is adapted from [UpsideDownFoxxo/schematicConverter](https://github.com/UpsideDownFoxxo/schematicConverter).
