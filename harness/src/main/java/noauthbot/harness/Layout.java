package noauthbot.harness;

import cc.ioctl.neoauth3bot.chiral.ChiralCarbonHelper;
import cc.ioctl.neoauth3bot.chiral.Molecule;
import cc.ioctl.neoauth3bot.chiral.MoleculeRender;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;

record Layout(MoleculeRender.MoleculeRenderConfig config, HashSet<Integer> chirals, List<Integer> answerCells) {

    static final int CANVAS_SIZE = 720;
    private static final int GRID_COLUMNS = 5;
    private static final int GRID_ROWS = 3;

    // clone of production path (AuthUserInterface.kt:261-275), same order and types
    static Layout of(Molecule molecule) {
        MoleculeRender.MoleculeRenderConfig config = MoleculeRender.calculateRenderRect(molecule, CANVAS_SIZE);
        config.gridCountX = GRID_COLUMNS;
        config.gridCountY = GRID_ROWS;
        config.drawGrid = true;
        HashSet<Integer> chirals = ChiralCarbonHelper.getMoleculeChiralCarbons(molecule);
        return new Layout(config, chirals, cellsOf(molecule, config, chirals));
    }

    private static List<Integer> cellsOf(Molecule molecule, MoleculeRender.MoleculeRenderConfig config,
                                         HashSet<Integer> chirals) {
        HashSet<Integer> cells = new HashSet<>(5);
        for (Integer atom : chirals) {
            int cellWidth = config.width / config.gridCountX;
            int cellHeight = config.height / config.gridCountY;
            float x = config.transformX(molecule, molecule.atomX(atom));
            float y = config.transformY(molecule, molecule.atomY(atom));
            cells.add(cell((int) (x / cellWidth), (int) (y / cellHeight)));
        }
        List<Integer> sorted = new ArrayList<>(cells);
        Collections.sort(sorted);
        return sorted;
    }

    static int cell(int column, int row) {
        return (column << 4) | row;
    }

    static String cellName(int cell) {
        return new StringBuilder().appendCodePoint('A' + (cell >> 4)).appendCodePoint('1' + (cell & 0x0f)).toString();
    }
}
