package noauthbot.harness;

import cc.ioctl.neoauth3bot.chiral.ChiralCarbonHelper;
import cc.ioctl.neoauth3bot.chiral.Molecule;

import java.util.ArrayList;
import java.util.List;

// compareChain is not symmetric, so the generator's answer depends on substituent iteration order
public final class ChiralAmbiguity {

    public static double chiralFraction(Molecule molecule, int center) {
        int[] substituents = substituentBonds(molecule, center);
        if (substituents == null) return 0;
        int count = substituents.length;

        // isChiralCarbon calls compareChain(earlier, later) along one order of the substituents
        // (1-2-3-4 for four, 1-3-2 for three), and that order follows the molblock's bond order.
        // Every permutation stands for one possible bond order.
        boolean[][] same = new boolean[count][count];
        for (int i = 0; i < count; i++) {
            for (int j = 0; j < count; j++) {
                if (i == j) continue;
                same[i][j] = ChiralCarbonHelper.compareChain(molecule, center, substituents[i], substituents[j]);
            }
        }

        int[] order = new int[count];
        for (int i = 0; i < count; i++) order[i] = i;
        int orders = 0, chiralOrders = 0;
        do {
            orders++;
            if (!anyEarlierMatchesLater(same, order)) chiralOrders++;
        } while (nextPermutation(order));
        return (double) chiralOrders / orders;
    }

    // clone of isChiralCarbon's shape test
    static boolean stereocenterShape(int heavySubstituents, int hydrogens) {
        return heavySubstituents == 4 && hydrogens == 0 || heavySubstituents == 3 && hydrogens == 1;
    }

    private static int[] substituentBonds(Molecule molecule, int center) {
        Molecule.Atom atom = molecule.getAtom(center);
        if (!"C".equals(atom.element)) return null;
        Molecule.Bond[] bonds = molecule.getAtomDeclaredBonds(center);
        for (Molecule.Bond bond : bonds) {
            if (bond.type > 1) return null;
        }
        int hydrogens = atom.hydrogenCount;
        List<Molecule.Bond> heavy = new ArrayList<>(4);
        for (Molecule.Bond bond : bonds) {
            int other = bond.from == center ? bond.to : bond.from;
            boolean loneHydrogen = "H".equals(molecule.getAtom(other).element)
                    && molecule.getAtomDeclaredBonds(other).length == 1;
            if (loneHydrogen) {
                hydrogens++;
            } else {
                heavy.add(bond);
            }
        }
        if (!stereocenterShape(heavy.size(), hydrogens)) return null;

        int[] ids = new int[heavy.size()];
        for (int i = 0; i < ids.length; i++) ids[i] = molecule.getBondId(heavy.get(i));
        return ids;
    }

    private static boolean anyEarlierMatchesLater(boolean[][] same, int[] order) {
        for (int earlier = 0; earlier < order.length; earlier++) {
            for (int later = earlier + 1; later < order.length; later++) {
                if (same[order[earlier]][order[later]]) return true;
            }
        }
        return false;
    }

    private static boolean nextPermutation(int[] values) {
        int pivot = values.length - 2;
        while (pivot >= 0 && values[pivot] >= values[pivot + 1]) pivot--;
        if (pivot < 0) return false;
        int successor = values.length - 1;
        while (values[successor] <= values[pivot]) successor--;
        swap(values, pivot, successor);
        for (int left = pivot + 1, right = values.length - 1; left < right; left++, right--) swap(values, left, right);
        return true;
    }

    private static void swap(int[] values, int i, int j) {
        int t = values[i];
        values[i] = values[j];
        values[j] = t;
    }
}
