package noauthbot.harness;

import cc.ioctl.neoauth3bot.chiral.Molecule;

import java.util.ArrayList;
import java.util.List;

// compareChain is exponential and effectively NEVER returns on some molecules. Count its recursion first
public final class ChainBudget {

    // recursion calls * bond count, a few seconds of the original
    static final long BUDGET = 300_000_000L;

    public static final class IntractableException extends Exception {
        public IntractableException(String message) {
            super(message);
        }
    }

    private static final class Exhausted extends RuntimeException {
        Exhausted() {
            super(null, null, false, false);
        }
    }

    private final Molecule molecule;
    private final int atomCount;
    private final int[][] bondsOfAtom; // 1-based, as in the generator
    private final boolean[] loneHydrogen;
    private final long maxCalls;
    private long calls;

    private ChainBudget(Molecule molecule) {
        this.molecule = molecule;
        atomCount = molecule.atomCount();
        List<List<Integer>> bonds = new ArrayList<>();
        for (int atom = 0; atom <= atomCount; atom++) bonds.add(new ArrayList<>());
        for (int bond = 1; bond <= molecule.bondCount(); bond++) {
            Molecule.Bond b = molecule.getBond(bond);
            bonds.get(b.from).add(bond);
            bonds.get(b.to).add(bond);
        }
        bondsOfAtom = new int[atomCount + 1][];
        loneHydrogen = new boolean[atomCount + 1];
        for (int atom = 1; atom <= atomCount; atom++) {
            bondsOfAtom[atom] = bonds.get(atom).stream().mapToInt(Integer::intValue).toArray();
            loneHydrogen[atom] = "H".equals(molecule.getAtom(atom).element) && bondsOfAtom[atom].length == 1;
        }
        maxCalls = Math.max(1, BUDGET / Math.max(1, molecule.bondCount()));
    }

    public static void check(Molecule molecule) throws IntractableException {
        ChainBudget budget = new ChainBudget(molecule);
        int depth = (int) (3 + Math.sqrt(molecule.atomCount()));
        try {
            for (int center = 1; center <= budget.atomCount; center++) {
                int[] substituents = budget.substituents(center);
                if (substituents == null) continue;
                for (int i = 0; i < substituents.length; i++) {
                    for (int j = 0; j < substituents.length; j++) {
                        if (i != j) budget.compare(center, center, substituents[i], substituents[j], depth);
                    }
                }
            }
        } catch (Exhausted e) {
            throw new IntractableException("compareChain budget exceeded (atoms=" + budget.atomCount
                    + ", bonds=" + molecule.bondCount() + ")");
        }
    }

    private int otherEnd(int bond, int atom) {
        Molecule.Bond b = molecule.getBond(bond);
        return b.from == atom ? b.to : b.from;
    }

    private int[] substituents(int center) {
        Molecule.Atom atom = molecule.getAtom(center);
        if (!"C".equals(atom.element)) return null;
        int hydrogens = atom.hydrogenCount;
        List<Integer> heavy = new ArrayList<>(4);
        for (int bond : bondsOfAtom[center]) {
            if (molecule.getBond(bond).type > 1) return null;
            if (loneHydrogen[otherEnd(bond, center)]) {
                hydrogens++;
            } else {
                heavy.add(bond);
            }
        }
        if (!ChiralAmbiguity.stereocenterShape(heavy.size(), hydrogens)) return null;

        return heavy.stream().mapToInt(Integer::intValue).toArray();
    }

    private record Branch(int hydrogens, List<Integer> heavyBonds) {
    }

    private Branch branch(int atom, int cameFrom) {
        int hydrogens = molecule.getAtom(atom).hydrogenCount;
        List<Integer> heavy = new ArrayList<>(4);
        for (int bond : bondsOfAtom[atom]) {
            int next = otherEnd(bond, atom);
            if (next == cameFrom) continue;
            if (loneHydrogen[next]) {
                hydrogens++;
            } else {
                heavy.add(bond);
            }
        }
        return new Branch(hydrogens, heavy);
    }

    private boolean compare(int from1, int from2, int chain1, int chain2, int depth) {
        if (++calls > maxCalls) throw new Exhausted();
        if (molecule.getBond(chain1).type != molecule.getBond(chain2).type) return false;
        int atom1 = otherEnd(chain1, from1), atom2 = otherEnd(chain2, from2);
        if (!molecule.getAtom(atom1).element.equals(molecule.getAtom(atom2).element)) return false;
        Branch branch1 = branch(atom1, from1), branch2 = branch(atom2, from2);
        if (branch1.hydrogens() != branch2.hydrogens()) return false;
        if (branch1.heavyBonds().size() != branch2.heavyBonds().size()) return false;
        if (depth < 0) return true;
        for (int next1 : branch1.heavyBonds()) {
            boolean matched = false;
            for (int next2 : branch2.heavyBonds()) {
                if (compare(atom1, atom2, next1, next2, depth - 1)) {
                    matched = true;
                    break;
                }
            }
            if (!matched) return false;
        }
        return true;
    }
}
