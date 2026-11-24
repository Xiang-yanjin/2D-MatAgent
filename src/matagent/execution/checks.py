"""Scientific outcomes are independent of node process status."""

from pathlib import Path
import math
import numpy as np


def array(value, shape=None):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing or non-numeric evidence")
    values = np.asarray(value, dtype=float)
    if (
        not values.size
        or not np.isfinite(values).all()
        or (shape and values.shape != shape)
    ):
        raise ValueError(f"Expected finite values of shape {shape}, got {values.shape}")
    return values


def check_result(kind, raw, params, count):
    if not isinstance(raw, dict) or raw.get("error") or raw.get("success") is False:
        raise ValueError(
            str(raw.get("error") if isinstance(raw, dict) else "Missing result object")
        )
    if raw.get("status") in ("failed", "blocked", "cancelled"):
        raise ValueError(str(raw.get("status")))
    if raw.get("status") == "skipped":
        return {"outcome": "skipped", "reason": raw.get("skip_reason")}
    if kind == "optimization":
        info = raw["optimization_info"]
        limit = float(params.get("fmax", 0.01))
        residual = float(array(info["generalized_fmax"]))
        converged = info.get("converged")
        if type(converged) is not bool or converged != (residual <= limit):
            raise ValueError(
                "optimization_info.converged disagrees with generalized_fmax/fmax"
            )
        if len(raw["optimized_structure"]["sites"]) != count:
            raise ValueError("optimized structure site count changed")
        return {
            "outcome": "converged" if converged else "unconverged",
            "converged": converged,
            "energy_eV": float(array(info["final_energy"])),
            "atomic_fmax_eV_per_A": float(array(info["atomic_fmax"])),
            "generalized_fmax_eV_per_A": residual,
            "threshold_eV_per_A": limit,
            "source": "raw.json#optimization_info",
        }
    if kind == "single_point":
        forces = array(raw["forces"], (count, 3))
        stress = raw.get("stress")
        if stress is not None and array(stress).shape not in ((3, 3), (6,)):
            raise ValueError("Unexpected stress tensor shape")
        return {
            "energy_eV": float(array(raw["energy"])),
            "atomic_fmax_eV_per_A": float(np.linalg.norm(forces, axis=1).max()),
            "stress_available": stress is not None,
            "source": "raw.json#energy,forces,stress",
        }
    if kind == "molecular_dynamics":
        steps = params.get("steps", 1000)
        if raw["n_steps"] != steps or raw["total_frames"] != steps:
            raise ValueError("MD returned an incomplete integration")
        frames = None
        if params.get("save_trajectory", True):
            from ase.io import iread

            frames = sum(1 for _ in iread(raw["trajectory_file"], index=":"))
            if frames != math.ceil(steps / params.get("checkpoint_interval", 100)):
                raise ValueError(
                    "Saved trajectory frame count disagrees with checkpoint interval"
                )
        return {
            "integrator": "VelocityVerlet",
            "steps": steps,
            "saved_frames": frames,
            "initial_temperature_K": raw["temperature"],
            "timestep_fs": raw["timestep"],
        }
    if kind == "symmetry":
        if type(raw.get("screening_passed")) is not bool or not raw.get(
            "symmetry_info"
        ):
            raise ValueError("Missing symmetry_info or screening_passed")
        return {
            "screening_passed": raw["screening_passed"],
            "source": "raw.json#symmetry_info",
        }
    if kind == "vasp_extract":
        value = raw["extraction_results"]
        if not isinstance(value, (dict, list)):
            raise ValueError("Missing extraction_results")
        return {"extraction_results": value}
    if kind == "elastic":
        array(raw["elastic_tensor"], (6, 6))
        if params.get("check_stability", True) and not raw.get("stability_info"):
            raise ValueError("Missing elastic stability criterion evidence")
        units = "GPa"
        if raw.get("is_2d"):
            array(raw["elastic_tensor_2d_Nm"], (3, 3))
            if float(array(raw["cell_c_angstrom"])) <= 0:
                raise ValueError("Invalid out-of-plane length for layer stiffness")
            units = "N/m"
        return {
            "screening_passed": raw.get("is_stable"),
            "in_plane_units": units,
            "cell_c_angstrom": raw.get("cell_c_angstrom"),
            "criteria": raw.get("stability_info"),
        }
    if kind == "eos":
        data = raw["eos_data"]
        energies = array(data["energies"])
        axis = "in_plane_areas" if raw.get("is_2d_material") else "volumes"
        samples = array(data[axis], energies.shape)
        if samples.ndim != 1 or len(samples) < 3 or np.any(samples <= 0):
            raise ValueError("Insufficient or invalid EOS samples")
        return {
            "samples": len(samples),
            "energy_unit": "eV",
            "axis": axis,
            "axis_unit": "Å²" if axis == "in_plane_areas" else "Å³",
            "sampling": raw["calculation_parameters"],
            "source": "raw.json#eos_data",
        }
    if kind == "phonon":
        energies = array(raw["dos_data"]["energies"])
        array(raw["dos_data"]["weights"], energies.shape)
        info = raw.get("stability_info") or {}
        if params.get("check_stability", True) and (
            not info or info.get("error") or type(raw.get("is_stable")) != bool
        ):
            raise ValueError("Missing or failed phonon stability check")
        return {
            "supercell": raw["supercell"],
            "dos_kpts": raw["dos_kpts"],
            "dos_energy_unit": "eV",
            "screening_passed": (
                raw.get("is_stable") if params.get("check_stability", True) else None
            ),
            "screening": info,
            "zone_point_threshold_eV": params.get("spoints_threshold", -0.0025),
        }
    if kind == "bte":
        thermal = raw["kappa_results"]
        temperatures = array(thermal["temperatures"])
        for component in ("kappa_xx", "kappa_yy", "kappa_zz"):
            array(thermal[component], temperatures.shape)
        return {
            "temperature_K": temperatures.tolist(),
            "conductivity_unit": "W/(m·K)",
            "qpoints_mesh": raw["qpoints_mesh"],
            "source": "raw.json#kappa_results",
        }
    if "processing" in raw:
        details = raw["processing"]
        count = details.get("input_count")
        matched = details.get("matched")
        return {
            **details,
            "outcome": (
                "empty_input"
                if count == 0
                else "filtered_all" if matched == 0 else "returned"
            ),
            "source": "raw.json#processing",
            "stdout": raw["stdout"],
        }
    if not raw:
        raise ValueError("Empty backend result")
    return {"outcome": "returned", "source": "raw.json", "fields": sorted(raw)}
