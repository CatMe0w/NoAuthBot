from dataclasses import dataclass

import numpy as np


@dataclass
class MoleculeGraph:
    elements: list[str]
    charges: list[int]
    hydrogens: list[int]  # per atom: bonded hydrogen atoms
    neighbours: list[list[tuple[int, int]]]  # per atom: (heavy neighbour, bond order)

    @classmethod
    def from_label(cls, label: dict) -> "MoleculeGraph":
        elements, charges = label["atoms"]["element"], label["atoms"]["charge"]
        bonded: list[list[tuple[int, int]]] = [[] for _ in elements]
        for first, second, order in zip(label["bonds"]["a"], label["bonds"]["b"], label["bonds"]["order"]):
            bonded[first].append((second, order))
            bonded[second].append((first, order))
        hydrogens = [sum(elements[other] == "H" for other, _ in atom_bonds) for atom_bonds in bonded]
        neighbours = [
            [(other, order) for other, order in atom_bonds if elements[other] != "H"] for atom_bonds in bonded
        ]
        return cls(elements, charges, hydrogens, neighbours)

    @property
    def heavy_atoms(self) -> list[int]:
        return [atom for atom, element in enumerate(self.elements) if element != "H"]


def atom_colours(graph: MoleculeGraph, depths: tuple[int, ...]) -> tuple[list[int], np.ndarray]:
    atoms = graph.heavy_atoms
    palette: dict = {}
    colours = {atom: palette.setdefault(own_features(graph, atom), len(palette)) for atom in atoms}
    table = np.zeros((len(atoms), len(depths)), dtype=np.int64)
    for depth in range(1, max(depths) + 1):
        palette = {}
        colours = {atom: palette.setdefault(neighbourhood(graph, colours, atom), len(palette)) for atom in atoms}
        for column, wanted in enumerate(depths):
            if wanted == depth:
                table[:, column] = [colours[atom] for atom in atoms]
    return atoms, table


def own_features(graph: MoleculeGraph, atom: int) -> tuple:
    return graph.elements[atom], graph.charges[atom], graph.hydrogens[atom]


def neighbourhood(graph: MoleculeGraph, colours: dict[int, int], atom: int) -> tuple:
    return colours[atom], tuple(sorted((order, colours[other]) for other, order in graph.neighbours[atom]))
