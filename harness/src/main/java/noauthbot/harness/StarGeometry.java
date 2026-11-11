package noauthbot.harness;

import cc.ioctl.neoauth3bot.chiral.Molecule;
import org.jetbrains.skija.Font;
import org.jetbrains.skija.FontMetrics;
import org.jetbrains.skija.Rect;

import java.util.ArrayList;
import java.util.List;

// cloning the float arithmetic of MoleculeRender.doDrawMolecule, step by step. DO NOT simplify
final class StarGeometry {

    record Star(int atom, float originX, float originY, float centerX, float centerY) {
    }

    private record Point(float x, float y) {
    }

    static List<Star> place(Molecule molecule, List<Integer> chirals, float[] atomX, float[] atomY,
                            float fontSize, float gridFontSize) {
        try (Font font = new Font(Fonts.roboto(), gridFontSize)) {
            // doDrawMolecule reads the metrics while the font still has the grid-label size
            float baselineShift = baselineShift(font.getMetrics());
            font.setSize(fontSize);
            float starWidth = font.measureTextWidth("*");
            Rect starBounds = font.measureText("*");

            List<Star> stars = new ArrayList<>(chirals.size());
            for (int atomIndex : chirals) {
                Point origin = origin(font, starWidth, baselineShift, molecule.getAtom(atomIndex),
                        atomX[atomIndex - 1], atomY[atomIndex - 1]);
                stars.add(new Star(atomIndex - 1, origin.x(), origin.y(),
                        origin.x() + (starBounds.getLeft() + starBounds.getRight()) / 2,
                        origin.y() + (starBounds.getTop() + starBounds.getBottom()) / 2));
            }
            return stars;
        }
    }

    private static float baselineShift(FontMetrics metrics) {
        return (metrics.getBottom() - metrics.getTop()) / 2 - metrics.getBottom();
    }

    private static Point origin(Font font, float starWidth, float baselineShift, Molecule.Atom atom, float x, float y) {
        if (LabelJson.isLabeled(atom)) {
            return new Point(x - font.measureTextWidth(atom.element) / 2 - starWidth / 2f, y + baselineShift);
        }
        float gap = 2 * (starWidth / 4 + font.getSize() / 4);
        Point center = beside(atom.spareSpace, x, y, gap);
        return new Point(center.x() - starWidth / 2, center.y() + baselineShift);
    }

    private static Point beside(int spareSpace, float x, float y, float gap) {
        if (spareSpace == Molecule.DIRECTION_BOTTOM) return new Point(x, y + gap);
        if (spareSpace == Molecule.DIRECTION_LEFT) return new Point(x - gap, y);
        if (spareSpace == Molecule.DIRECTION_TOP) return new Point(x, y - gap);
        return new Point(x + gap, y);
    }

    private StarGeometry() {
    }
}
