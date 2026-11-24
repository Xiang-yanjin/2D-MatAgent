"""Geometry, provenance and structure-tool regressions without calculators."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from matsimpy import Crystal, Lattice
from matsimpy.io import read, write

from matagent.assistant.agent import build_agent
from matagent.assistant.demo_provider import DemoProvider
from matagent.structures.geometry import rebuild, compare_structures
from matagent.structures.store import StructureStore


class StructureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.agent = build_agent(DemoProvider(), self.workspace)
        self.addCleanup(self.agent.close)
        self.store = StructureStore(self.workspace)

    def call(self, name, **kwargs):
        response = self.agent.call_tool(name, kwargs)
        self.assertTrue(response.ok, response.content())
        return response.content()

    def success(self, name, **kwargs):
        result = self.call(name, **kwargs)
        self.assertNotIn("error", result, result)
        return result

    def create(self, prototype="mos2", **kwargs):
        return self.success("create_structure", prototype=prototype, **kwargs)

    def external(self, crystal, name="input.json", **kwargs):
        file = self.root / name
        write(crystal, str(file))
        self.agent.structure_tools.begin_request(f"导入二维结构 {file}")
        return self.success("import_structure", source_file=str(file), **kwargs), file

    def test_three_prototypes_have_explicit_sources_and_geometry(self):
        listing = self.success("list_structure_prototypes")
        self.assertEqual({p["prototype"] for p in listing["prototypes"]}, {"mos2", "graphene", "hbn"})
        for name, counts, a in (("mos2", {"Mo": 1, "S": 2}, 3.16),
                                ("graphene", {"C": 2}, 2.46), ("hbn", {"B": 1, "N": 1}, 2.5)):
            with self.subTest(prototype=name):
                result = self.create(name)
                self.assertEqual(result["composition"], counts)
                self.assertEqual(result["cell_A"][0][0], a)
                self.assertTrue(result["source"]["source_commit"])
                crystal, record = self.store.load(result["structure_id"])
                self.assertEqual(tuple(crystal.pbc), (True, True, False))
                self.assertEqual(record["sha256"], hashlib.sha256((self.workspace / record["structure_file"]).read_bytes()).hexdigest())
        self.assertEqual(result["periodicity"]["source_pbc"], [True, True, True])
        self.assertEqual(result["periodicity"]["declared_pbc"], [True, True, False])

    def test_mos2_chain_keeps_parents_and_correct_vacuum_and_atom_order(self):
        original = self.create()
        before = (self.workspace / original["structure_file"]).read_bytes()
        expanded = self.success("make_structure_supercell", structure_id=original["structure_id"], repeats=[3, 3, 1])
        self.assertEqual(expanded["composition"], {"Mo": 9, "S": 18})
        changed = self.success("substitute_structure_sites", structure_id=expanded["structure_id"],
                               source_element="Mo", new_element="W")
        self.assertEqual(changed["composition"], {"Mo": 8, "S": 18, "W": 1})
        self.assertEqual(changed["operation"]["site_numbers"], [1])
        self.assertEqual(changed["operation"]["selection"]["class_size"], 9)
        vacuum = self.success("set_structure_vacuum", structure_id=changed["structure_id"], vacuum_gap_A=20)
        self.assertAlmostEqual(vacuum["layer_geometry"]["cell_height_A"], 23.12)
        crystal, _ = self.store.load(vacuum["structure_id"])
        self.assertAlmostEqual(min(crystal.cart_positions[:, 2]), 10)
        self.assertAlmostEqual(crystal.lattice.matrix[2, 2] - max(crystal.cart_positions[:, 2]), 10)
        for fmt in ("vasp", "cif", "json"):
            result = self.success("export_structure", structure_id=vacuum["structure_id"], format=fmt)
            exported = read(str(self.workspace / result["export"]["path"]), format=fmt)
            compare_structures(crystal, exported, cif=(fmt == "cif"))
            self.assertEqual(list(crystal.species), list(exported.species))
        self.assertEqual(before, (self.workspace / original["structure_file"]).read_bytes())
        self.assertEqual([v["operation"]["name"] for v in vacuum["lineage"]],
                         ["substitute_structure_sites", "make_structure_supercell", "create_structure"])
        self.assertEqual(vacuum["last_substitution"]["input_structure_id"], expanded["structure_id"])
        self.assertEqual(vacuum["last_substitution"]["output_structure_id"], changed["structure_id"])
        self.assertFalse((self.workspace / "runs").exists())

    def test_external_import_requires_path_and_preserves_source_and_unknown_pbc(self):
        original = self.create()
        crystal, _ = self.store.load(original["structure_id"])
        path = self.root / "external.vasp"
        write(crystal, str(path))
        before = path.read_bytes()
        blocked = self.call("import_structure", source_file=str(path))
        self.assertIn("error", blocked)
        self.agent.structure_tools.begin_request(f"导入文件 {path}")
        result = self.success("import_structure", source_file=str(path))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertIsNone(result["periodicity"]["source_pbc"])
        self.assertIsNone(result["periodicity"]["normal_axis"])
        self.assertEqual(result["periodicity"]["reader_pbc"], [True, True, True])
        self.assertIn("error", self.call("make_structure_supercell", structure_id=result["structure_id"], repeats=[2, 2, 1]))
        declared = self.success("import_structure", source_file=str(path), is_2d=True, normal_axis="c")
        self.assertEqual(declared["periodicity"]["effective_pbc"], [True, True, False])
        self.assertIsNone(declared["periodicity"]["source_pbc"])
        self.assertEqual(path.read_bytes(), before)

    def test_cif_and_json_import_metadata_and_constraints_survive_edits(self):
        reference, _ = self.store.load(self.create("hbn")["structure_id"])
        enriched = reference.with_metadata(sample="user-source").with_site_property(
            "selective_dynamics", [[False, False, False], [True, True, True]])
        imported, _ = self.external(enriched)
        self.assertEqual(imported["periodicity"]["source_pbc"], [True, True, False])
        expanded = self.success("make_structure_supercell", structure_id=imported["structure_id"], repeats=[2, 2, 1])
        automatic = self.call("substitute_structure_sites", structure_id=expanded["structure_id"], source_element="B", new_element="C")
        self.assertIn("error", automatic)
        changed = self.success("substitute_structure_sites", structure_id=expanded["structure_id"],
                               site_numbers=[1], source_element="B", new_element="C")
        final = self.success("set_structure_vacuum", structure_id=changed["structure_id"], vacuum_gap_A=20)
        result, _ = self.store.load(final["structure_id"])
        self.assertEqual(result.metadata["sample"], "user-source")
        self.assertEqual(list(result.site_properties[0]["selective_dynamics"]), [False, False, False])
        cif, path = self.external(reference, "input.cif", is_2d=True, normal_axis="c")
        self.assertEqual(cif["composition"], {"B": 1, "N": 1})
        self.assertEqual(cif["source"]["format"], "cif")

    def test_multiple_inequivalent_sites_require_selection_without_editing(self):
        base = self.create()
        expanded = self.success("make_structure_supercell", structure_id=base["structure_id"], repeats=[3, 3, 1])
        first = self.success("substitute_structure_sites", structure_id=expanded["structure_id"],
                             source_element="Mo", new_element="W")
        before = set(self.store.root.iterdir())
        result = self.success("substitute_structure_sites", structure_id=first["structure_id"],
                              source_element="Mo", new_element="W")
        self.assertTrue(result["needs_clarification"])
        self.assertGreater(len(result["equivalent_groups"]), 1)
        self.assertEqual(before, set(self.store.root.iterdir()))

    def test_invalid_indices_repeats_and_unknown_ids_do_not_create_structures(self):
        sid = self.create()["structure_id"]
        before = set(self.store.root.iterdir())
        cases = [("make_structure_supercell", {"structure_id": sid, "repeats": [2, 2, 2]}),
                 ("make_structure_supercell", {"structure_id": sid, "repeats": [0, 2, 1]}),
                 ("substitute_structure_sites", {"structure_id": sid, "new_element": "W", "site_numbers": [0]}),
                 ("substitute_structure_sites", {"structure_id": sid, "new_element": "W", "site_numbers": [4]}),
                 ("substitute_structure_sites", {"structure_id": sid, "new_element": "W", "site_numbers": [1, 1]}),
                 ("set_structure_vacuum", {"structure_id": sid, "vacuum_gap_A": -1}),
                 ("inspect_structure", {"structure_id": "str-20990101T000000Z-000000000000"}),
                 ("create_structure", {"prototype": "unverified-prototype"})]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                self.assertIn("error", self.call(name, **args))
        self.assertEqual(before, set(self.store.root.iterdir()))

    def test_wrapped_layer_is_unfolded_but_ambiguous_gap_and_tilt_are_rejected(self):
        crystal, _ = self.store.load(self.create()["structure_id"])
        cart = crystal.cart_positions.copy()
        cart[:, 2] = np.mod(cart[:, 2] + 10, 20)
        wrapped = rebuild(crystal, cart=cart)
        imported, _ = self.external(wrapped)
        vacuum = self.success("set_structure_vacuum", structure_id=imported["structure_id"], vacuum_gap_A=20)
        self.assertAlmostEqual(vacuum["layer_geometry"]["material_thickness_A"], 3.12)
        ambiguous = Crystal(["C", "C"], [[0, 0, .25], [0, 0, .75]], Lattice.hexagonal(2.46, 20),
                            pbc=[True, True, False])
        imported, _ = self.external(ambiguous)
        self.assertIn("error", self.call("set_structure_vacuum", structure_id=imported["structure_id"], vacuum_gap_A=20))
        matrix = crystal.lattice.matrix.copy()
        matrix[2, 0] = 1
        tilted = rebuild(crystal, cell=matrix)
        imported, _ = self.external(tilted)
        self.assertIn("error", self.call("set_structure_vacuum", structure_id=imported["structure_id"], vacuum_gap_A=20))

    def test_export_does_not_overwrite_or_escape_and_detects_tampering(self):
        sid = self.create()["structure_id"]
        existing = self.workspace / "user.vasp"
        existing.write_text("user data")
        for path in (str(existing), str(self.root / "outside.vasp")):
            self.assertIn("error", self.call("export_structure", structure_id=sid, output_file=path))
        self.assertEqual(existing.read_text(), "user data")
        result = self.success("export_structure", structure_id=sid)
        again = self.success("export_structure", structure_id=sid)
        self.assertEqual(result["export"]["sha256"], again["export"]["sha256"])
        self.assertEqual(len(again["exports"]), 1)
        file = self.workspace / result["export"]["path"]
        file.write_text("changed")
        self.assertIn("error", self.call("export_structure", structure_id=sid))
        crystal, record = self.store.load(sid)
        (self.workspace / record["structure_file"]).write_text("{}")
        self.assertIn("error", self.call("inspect_structure", structure_id=sid))

    def test_roundtrip_does_not_wrap_the_nonperiodic_axis(self):
        reference, _ = self.store.load(self.create()["structure_id"])
        shifted = rebuild(reference, cart=reference.cart_positions + reference.lattice.matrix[2])
        with self.assertRaises(ValueError):
            compare_structures(reference, shifted)
