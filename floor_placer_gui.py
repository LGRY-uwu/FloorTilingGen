"""Tkinter GUI wrapper for Floppy's Encoded Floor Placer schematic generator."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from floor_placer_gen import (
    DATA_PALETTE,
    DEFAULT_MAIN_ARM_START,
    DEFAULT_SUB_ARM_START,
    TEMPLATE_FILE,
    _extract_pattern_grid,
    _water_bottle_count_for_signal,
    generate_floor_placer,
    nearest_valid_z,
)

X_LENGTH_OPTIONS = [str(2**i) for i in range(4, 14)]  # 16 .. 8192
Z_LENGTH_OPTIONS = [str(2**i) for i in range(5, 14)]  # 32 .. 8192


class FloorPlacerGUI:
    """Beginner-friendly Tkinter UI for generating Floor Placer schematics."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Floppy's Encoded Floor Placer Generator")
        self.root.geometry("680x580")
        self.root.minsize(620, 520)

        self.base_dir = Path(__file__).resolve().parent
        self.schematics_dir = self.base_dir / "schematics"

        self.pattern_var = tk.StringVar(value="")
        self.pattern_info_var = tk.StringVar(value="None selected (arm tiling only)")
        self.x_len_var = tk.StringVar(value="32")
        self.z_len_var = tk.StringVar(value="64")
        self.z_notice_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(
            value=str(self.base_dir / "floor_placer_generated.litematic")
        )
        self.template_var = tk.StringVar(value=str(self.schematics_dir / TEMPLATE_FILE))
        self.parts_dir_var = tk.StringVar(value=str(self.schematics_dir))
        self.advanced_open = tk.BooleanVar(value=False)

        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        # 1. Pattern selection
        pat_frame = ttk.LabelFrame(main, text="1. Floor Pattern (.litematic)", padding=10)
        pat_frame.pack(fill=tk.X, pady=(0, 8))

        pat_row = ttk.Frame(pat_frame)
        pat_row.pack(fill=tk.X)
        ttk.Entry(pat_row, textvariable=self.pattern_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(pat_row, text="Browse...", command=self._browse_pattern).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(pat_row, text="Clear", command=self._clear_pattern).pack(
            side=tk.LEFT
        )
        ttk.Label(
            pat_frame,
            textvariable=self.pattern_info_var,
            foreground="#444444",
        ).pack(anchor=tk.W, pady=(6, 0))

        # 2. Floor dimensions
        dim_frame = ttk.LabelFrame(main, text="2. Floor Dimensions (X × Z)", padding=10)
        dim_frame.pack(fill=tk.X, pady=(0, 8))

        dim_row = ttk.Frame(dim_frame)
        dim_row.pack(fill=tk.X)

        ttk.Label(dim_row, text="X Length:").pack(side=tk.LEFT)
        ttk.Combobox(
            dim_row,
            textvariable=self.x_len_var,
            values=X_LENGTH_OPTIONS,
            width=8,
        ).pack(side=tk.LEFT, padx=(6, 20))

        ttk.Label(dim_row, text="Z Length (multiple of 32):").pack(side=tk.LEFT)
        z_combo = ttk.Combobox(
            dim_row,
            textvariable=self.z_len_var,
            values=Z_LENGTH_OPTIONS,
            width=8,
        )
        z_combo.pack(side=tk.LEFT, padx=(6, 0))
        z_combo.bind("<FocusOut>", lambda _e: self._snap_z_length())
        z_combo.bind("<Return>", lambda _e: self._snap_z_length())
        z_combo.bind("<<ComboboxSelected>>", lambda _e: self._snap_z_length())

        ttk.Label(
            dim_frame,
            textvariable=self.z_notice_var,
            foreground="#b35900",
        ).pack(anchor=tk.W, pady=(6, 0))

        # 3. Output path
        out_frame = ttk.LabelFrame(main, text="3. Output Schematic (.litematic)", padding=10)
        out_frame.pack(fill=tk.X, pady=(0, 8))

        out_row = ttk.Frame(out_frame)
        out_row.pack(fill=tk.X)
        ttk.Entry(out_row, textvariable=self.output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(out_row, text="Save As...", command=self._browse_output).pack(
            side=tk.LEFT
        )

        # Optional advanced settings toggle
        adv_toggle = ttk.Checkbutton(
            main,
            text="Show Advanced Settings (Template / Parts Directory)",
            variable=self.advanced_open,
            command=self._toggle_advanced,
        )
        adv_toggle.pack(anchor=tk.W, pady=(0, 4))

        self.adv_frame = ttk.LabelFrame(main, text="Advanced Settings", padding=8)
        row_t = ttk.Frame(self.adv_frame)
        row_t.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row_t, text="Template:", width=10).pack(side=tk.LEFT)
        ttk.Entry(row_t, textvariable=self.template_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(row_t, text="Browse", command=self._browse_template).pack(side=tk.LEFT)

        row_p = ttk.Frame(self.adv_frame)
        row_p.pack(fill=tk.X)
        ttk.Label(row_p, text="Parts Dir:", width=10).pack(side=tk.LEFT)
        ttk.Entry(row_p, textvariable=self.parts_dir_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(row_p, text="Browse", command=self._browse_parts_dir).pack(side=tk.LEFT)

        # Generate button
        self.gen_btn = ttk.Button(
            main,
            text="Generate Schematic",
            command=self._on_generate,
        )
        self.gen_btn.pack(fill=tk.X, pady=(6, 8), ipady=6)

        # Log output
        log_frame = ttk.LabelFrame(
            main,
            text="Output Log & Block Mapping (Most Used -> Signal 1..15)",
            padding=8,
        )
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=12, state=tk.DISABLED, font=("Consolas", 9)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _toggle_advanced(self) -> None:
        if self.advanced_open.get():
            self.adv_frame.pack(fill=tk.X, pady=(0, 6), before=self.gen_btn)
        else:
            self.adv_frame.pack_forget()

    def _browse_pattern(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Pattern .litematic File",
            initialdir=str(self.base_dir),
            filetypes=[("Litematica files", "*.litematic"), ("All files", "*.*")],
        )
        if path:
            self.pattern_var.set(path)
            self._inspect_pattern(Path(path))

    def _clear_pattern(self) -> None:
        self.pattern_var.set("")
        self.pattern_info_var.set("None selected (arm tiling only)")

    def _inspect_pattern(self, path: Path) -> None:
        try:
            grid = _extract_pattern_grid(path)
            pw, ph, pl = len(grid), len(grid[0]), len(grid[0][0])
            counts = Counter(grid[x][0][z] for x in range(pw) for z in range(pl))
            n_types = len(counts)
            top_block, top_cnt = counts.most_common(1)[0]
            warn = " (Warning: > 15 block types!)" if n_types > 15 else ""
            self.pattern_info_var.set(
                f"Size: {pw}×{ph}×{pl}, {n_types} block types{warn} | Most used: {top_block} ({top_cnt})"
            )
        except Exception as exc:
            self.pattern_info_var.set(f"Failed to read pattern: {exc}")

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save Generated .litematic File",
            initialdir=str(self.base_dir),
            initialfile="floor_placer_generated.litematic",
            defaultextension=".litematic",
            filetypes=[("Litematica files", "*.litematic"), ("All files", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def _browse_template(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Template .litematic File",
            initialdir=str(self.base_dir),
            filetypes=[("Litematica files", "*.litematic"), ("All files", "*.*")],
        )
        if path:
            self.template_var.set(path)

    def _browse_parts_dir(self) -> None:
        path = filedialog.askdirectory(
            title="Select Arm Parts Directory",
            initialdir=str(self.base_dir),
        )
        if path:
            self.parts_dir_var.set(path)

    def _snap_z_length(self) -> None:
        raw = self.z_len_var.get().strip()
        if not raw:
            return
        try:
            val = int(raw)
        except ValueError:
            self.z_notice_var.set("Invalid Z length: please enter an integer.")
            return

        snapped = nearest_valid_z(val)
        if snapped != val:
            self.z_len_var.set(str(snapped))
            self.z_notice_var.set(
                f"Notice: Z length adjusted from {val} to {snapped} "
                f"(nearest multiple of 32)."
            )
        else:
            self.z_notice_var.set("")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _on_generate(self) -> None:
        self._snap_z_length()
        try:
            tx = int(self.x_len_var.get().strip())
            tz = int(self.z_len_var.get().strip())
            if tx < 0 or tz <= 0:
                raise ValueError("X must be >= 0 and Z must be > 0.")
        except ValueError as exc:
            messagebox.showerror("Invalid Input", f"Invalid X/Z dimensions.\n{exc}")
            return

        out_path = Path(self.output_var.get().strip())
        tmpl_path = Path(self.template_var.get().strip())
        parts_dir = Path(self.parts_dir_var.get().strip())
        pat_raw = self.pattern_var.get().strip()
        pat_path = Path(pat_raw) if pat_raw else None

        if not tmpl_path.exists():
            messagebox.showerror("File Not Found", f"Template file not found:\n{tmpl_path}")
            return
        if pat_path is not None and not pat_path.exists():
            messagebox.showerror("File Not Found", f"Pattern file not found:\n{pat_path}")
            return

        self._clear_log()
        self._append_log("Generating schematic...")
        self.gen_btn.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                plan, palettes = generate_floor_placer(
                    target_x=tx,
                    target_z=tz,
                    output_path=out_path,
                    pattern_path=pat_path,
                    template_path=tmpl_path,
                    parts_dir=parts_dir,
                    sub_arm_start=DEFAULT_SUB_ARM_START,
                    main_arm_start=DEFAULT_MAIN_ARM_START,
                )

                counts = Counter()
                if pat_path is not None:
                    grid = _extract_pattern_grid(pat_path)
                    for x in range(len(grid)):
                        for z in range(len(grid[0][0])):
                            counts[grid[x][0][z]] += 1

                self.root.after(
                    0, lambda: self._on_success(out_path, plan, palettes, counts)
                )
            except Exception as exc:
                self.root.after(0, lambda err=exc: self._on_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self, out_path: Path, plan, palettes, counts: Counter) -> None:
        self.gen_btn.configure(state=tk.NORMAL)
        self._append_log(f"Saved: {out_path}")
        self._append_log(
            f"Redstone blocks in dropper: {plan.redstone_block_count} (2 * {plan.z_multiple_n})"
        )
        if palettes:
            self._append_log("")
            self._append_log("Signal | Bottles | Shulker    | Count | Block ID")
            self._append_log("-" * 68)
            for idx, bid in enumerate(palettes[0]):
                ss = idx + 1
                bottles = _water_bottle_count_for_signal(ss)
                shulker = DATA_PALETTE[idx].replace("minecraft:", "").replace("_shulker_box", "")
                cnt = counts.get(bid, 0)
                self._append_log(
                    f" SS={ss:2d} | {bottles:7d} | {shulker:<10s} | {cnt:5d} | {bid}"
                )
        messagebox.showinfo("Done", f"Schematic generated successfully!\n{out_path}")

    def _on_error(self, exc: Exception) -> None:
        self.gen_btn.configure(state=tk.NORMAL)
        self._append_log(f"Error: {exc}")
        messagebox.showerror("Generation Failed", str(exc))


def main() -> None:
    root = tk.Tk()
    FloorPlacerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
