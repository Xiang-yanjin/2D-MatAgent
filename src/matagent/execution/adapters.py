"""Explicit data conversions for future workflow execution; never model inference."""
def select_frame(trajectory, reference_structure, index=-1):
    from ase.io import read
    from pymatgen.io.ase import AseAtomsAdaptor
    if type(index) is not int:
        raise ValueError("Frame index must be an integer")
    atoms=read(str(trajectory),index=index)
    if atoms.get_chemical_symbols()!=[str(site.specie) for site in reference_structure]:
        raise ValueError("Trajectory species/order differ from the explicit reference")
    atoms.set_cell(reference_structure.lattice.matrix,scale_atoms=False)
    atoms.set_pbc(reference_structure.lattice.pbc)
    return {"structure":AseAtomsAdaptor.get_structure(atoms)}
