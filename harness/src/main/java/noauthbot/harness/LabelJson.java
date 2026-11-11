package noauthbot.harness;

import cc.ioctl.neoauth3bot.chiral.Molecule;
import cc.ioctl.neoauth3bot.chiral.MoleculeRender;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

final class LabelJson {

    private record Geometry(float visualCellWidth, float visualCellHeight, float gridFontSize,
                            float[] atomX, float[] atomY) {

        static Geometry of(Molecule molecule, MoleculeRender.MoleculeRenderConfig config) {
            float visualCellWidth = (float) config.width / config.gridCountX;
            float visualCellHeight = (float) config.height / config.gridCountY;
            float gridFontSize = Math.min(Math.min(visualCellWidth, visualCellHeight) / 2.0f, config.fontSize);
            int atomCount = molecule.atomCount();
            float[] atomX = new float[atomCount];
            float[] atomY = new float[atomCount];
            for (int i = 0; i < atomCount; i++) {
                atomX[i] = config.transformX(molecule, molecule.atomX(i + 1));
                atomY[i] = config.transformY(molecule, molecule.atomY(i + 1));
            }
            return new Geometry(visualCellWidth, visualCellHeight, gridFontSize, atomX, atomY);
        }

        // the generator answers/grades with cells of W // 5 by H // 3 px but draws the grid lines at W / 5 and H / 3,
        // so the cell a human sees can differ from the grader's (grid_shift)
        int visualCell(int atomIndex) {
            int column = (int) Math.floor(atomX[atomIndex - 1] / visualCellWidth);
            int row = (int) Math.floor(atomY[atomIndex - 1] / visualCellHeight);
            return Layout.cell(column, row);
        }
    }

    static Json open(SdfReader.Record record, String variant, long seed, String key, Map<String, String> versionInfo,
                     Molecule molecule, Layout layout) {
        Geometry geometry = Geometry.of(molecule, layout.config());
        List<Integer> chirals = new ArrayList<>(layout.chirals());
        Collections.sort(chirals);

        Json json = new Json().beginObject();
        json.key("key").value(key);
        json.key("cid").value(record.cid);
        json.key("variant").value(variant);
        json.key("seed").value(Long.toUnsignedString(seed));
        Provenance.write(json, versionInfo);
        json.key("index_base").value(0);
        writeCanvas(json, molecule, layout.config(), geometry);
        writeAtoms(json, molecule, geometry);
        writeBonds(json, molecule);
        writeChirality(json, molecule, chirals);
        writeCells(json, layout, chirals, geometry);
        if (Sample.VARIANT_STAR.equals(variant)) {
            writeStars(json, StarGeometry.place(molecule, chirals, geometry.atomX(), geometry.atomY(),
                    layout.config().fontSize, geometry.gridFontSize()));
        }
        writePubchem(json, record);
        return json;
    }

    // MoleculeRender draws the element symbol of every atom excl. plain carbon
    static boolean isLabeled(Molecule.Atom atom) {
        return !(atom.element.equals("C") && atom.charge == 0 && atom.unpaired == 0
                && (atom.showFlag & Molecule.SHOW_FLAG_EXPLICIT) == 0);
    }

    private static void writeCanvas(Json json, Molecule molecule, MoleculeRender.MoleculeRenderConfig config,
                                    Geometry geometry) {
        json.key("width").value(config.width);
        json.key("height").value(config.height);
        json.key("scale").value(config.scaleFactor);
        json.key("font_size").value(config.fontSize);
        json.key("grid_font_size").value(geometry.gridFontSize());
        json.key("avg_bond_length").value(molecule.getAverageBondLength());
        json.key("grid").beginObject()
                .key("cols").value(config.gridCountX)
                .key("rows").value(config.gridCountY)
                .key("answer_cell_w").value(config.width / config.gridCountX)
                .key("answer_cell_h").value(config.height / config.gridCountY)
                .key("visual_cell_w").value(geometry.visualCellWidth())
                .key("visual_cell_h").value(geometry.visualCellHeight())
                .endObject();
    }

    private static void writeAtoms(Json json, Molecule molecule, Geometry geometry) {
        int atomCount = molecule.atomCount();
        json.key("atoms").beginObject();
        json.key("element").beginArray();
        for (int i = 1; i <= atomCount; i++) json.value(molecule.getAtom(i).element);
        json.endArray();
        json.key("x").beginArray();
        for (float x : geometry.atomX()) json.value(x);
        json.endArray();
        json.key("y").beginArray();
        for (float y : geometry.atomY()) json.value(y);
        json.endArray();
        json.key("charge").beginArray();
        for (int i = 1; i <= atomCount; i++) json.value(molecule.getAtom(i).charge);
        json.endArray();
        json.key("labeled").beginArray();
        for (int i = 1; i <= atomCount; i++) json.value(isLabeled(molecule.getAtom(i)));
        json.endArray();
        json.key("spare").beginArray();
        for (int i = 1; i <= atomCount; i++) json.value(molecule.getAtom(i).spareSpace);
        json.endArray();
        json.endObject();
    }

    private static void writeBonds(Json json, Molecule molecule) {
        int bondCount = molecule.bondCount();
        json.key("bonds").beginObject();
        json.key("a").beginArray();
        for (int i = 1; i <= bondCount; i++) json.value(molecule.getBond(i).from - 1);
        json.endArray();
        json.key("b").beginArray();
        for (int i = 1; i <= bondCount; i++) json.value(molecule.getBond(i).to - 1);
        json.endArray();
        json.key("order").beginArray();
        for (int i = 1; i <= bondCount; i++) json.value(molecule.getBond(i).type);
        json.endArray();
        json.endObject();
    }

    private static void writeChirality(Json json, Molecule molecule, List<Integer> chirals) {
        json.key("chiral_atoms").beginArray();
        for (int atom : chirals) json.value(atom - 1);
        json.endArray();
        json.key("chiral_ambiguous").beginArray();
        for (int atom = 1; atom <= molecule.atomCount(); atom++) {
            double fraction = ChiralAmbiguity.chiralFraction(molecule, atom);
            if (fraction > 0 && fraction < 1) json.beginArray().value(atom - 1).value(fraction).endArray();
        }
        json.endArray();
    }

    private static void writeCells(Json json, Layout layout, List<Integer> chirals, Geometry geometry) {
        json.key("answer_cells").beginArray();
        for (int cell : layout.answerCells()) json.value(Layout.cellName(cell));
        json.endArray();
        json.key("chiral_visual_cells").beginArray();
        for (int atom : chirals) json.value(Layout.cellName(geometry.visualCell(atom)));
        json.endArray();
    }

    private static void writeStars(Json json, List<StarGeometry.Star> stars) {
        json.key("stars").beginArray();
        for (StarGeometry.Star star : stars) {
            json.beginObject()
                    .key("atom").value(star.atom())
                    .key("origin_x").value(star.originX())
                    .key("origin_y").value(star.originY())
                    .key("center_x").value(star.centerX())
                    .key("center_y").value(star.centerY())
                    .endObject();
        }
        json.endArray();
    }

    private static void writePubchem(Json json, SdfReader.Record record) {
        json.key("pubchem").beginObject();
        for (String tag : SdfReader.TAGS) {
            if (tag.equals("PUBCHEM_COMPOUND_CID")) continue;
            json.key(tag.substring("PUBCHEM_".length()).toLowerCase()).value(record.tag(tag));
        }
        json.endObject();
    }

    private LabelJson() {
    }
}
